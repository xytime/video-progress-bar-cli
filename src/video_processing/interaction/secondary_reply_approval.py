"""视频号二级回复 Telegram 审批流程与安全门禁。

实现：
- 单一显式配置审批人与私聊目标校验（严格白名单，不自动推断）
- 服务端 Token 绑定与一次性消费
- HTML 转义防注入
- callback_data 64 字节 Telegram API 边界防御
- 离线测试替身 (FakeApprovalTransport)

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-17 | Antigravity | M3.5: 新增真实 TelegramApprovalTransport（对接 telegram_delivery.send_text 回执账本）与 build_default_approval_transport，支持持久化 approval_message_id |
| 1.1.0 | 2026-10-17 | Antigravity | 收回裸 SQL 为 db.get_audience_comment、强制要求可信审批传输通道并拒绝 local_operator/local-cli 伪身份 (R3/R4) |
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现二级回复 Telegram 审批发送、防重放消费、HTML 转义与 64B callback_data 防护 |
"""

from __future__ import annotations

import datetime
import html
import logging
import secrets
from typing import Any, Callable, Dict, List, Optional, Tuple

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.telegram_delivery import send_text as send_telegram_text

logger = logging.getLogger(__name__)

MAX_TELEGRAM_CALLBACK_BYTES = 64
DISALLOWED_LOCAL_APPROVER_IDS = ("local_operator", "unconfigured")
DISALLOWED_LOCAL_CHAT_PREFIXES = ("local-cli:", "unconfigured")


class ApprovalTransportError(Exception):
    """审批通知发送异常。"""


class FakeApprovalTransport:
    """用于测试与离线演示的 Fake Telegram 传输客户端。"""

    allow_fixture_drafts = True

    def __init__(self) -> None:
        self.sent_messages: List[Dict[str, Any]] = []

    def send_approval_message(
        self,
        *,
        chat_id: str,
        text: str,
        inline_keyboard: List[List[Dict[str, str]]],
    ) -> bool:
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "inline_keyboard": inline_keyboard,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        return True


class TelegramApprovalTransport:
    """真实 Telegram Bot API 审批卡片传输通道（对接 telegram_delivery.send_text 账本）。

    严格执行失败关闭（Fail-Closed）：
    - 拒绝发送 rule_secondary_provider 等离线夹具草稿（allow_fixture_drafts = False）；
    - 拒绝未配置 token 或使用 local-cli: 伪会话前缀；
    - 仅当 Telegram API 返回 ok=True 且携带非空 message_id（state == 'ACCEPTED'）时视为派发成功。
    """

    allow_fixture_drafts = False

    def __init__(
        self,
        *,
        db: Optional[PipelineDB] = None,
        token: Optional[str] = None,
        send_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._db = db
        self._token = token
        self._send_fn = send_fn or send_telegram_text

    def send_approval_message(
        self,
        *,
        chat_id: str,
        text: str,
        inline_keyboard: List[List[Dict[str, str]]],
        task_id: Optional[int] = None,
    ) -> str:
        clean_chat = str(chat_id or "").strip()
        if not clean_chat or any(clean_chat.lower().startswith(p) for p in DISALLOWED_LOCAL_CHAT_PREFIXES):
            raise ApprovalTransportError(f"非法的审批私聊目标 chat_id: {clean_chat}")
        bot_token = str(self._token if self._token is not None else (settings.telegram_bot_token or "")).strip()
        if not bot_token:
            raise ApprovalTransportError("TELEGRAM_BOT_TOKEN_NOT_CONFIGURED")

        result = self._send_fn(
            text,
            parse_mode="HTML",
            chat_id=clean_chat,
            token=bot_token,
            reply_markup={"inline_keyboard": inline_keyboard},
            workflow="wechat_secondary_reply_approval",
            step="approval_card",
            ref_key=f"secondary_reply_task:{task_id or 0}",
            db=self._db,
        )
        state = getattr(result, "state", None)
        message_id = str(getattr(result, "message_id", "") or "").strip()
        error = getattr(result, "error", None)
        if state != "ACCEPTED" or not message_id:
            raise ApprovalTransportError(
                f"Telegram 审批卡片未获平台受理: state={state}, error={error or 'missing_message_id'}"
            )
        return message_id


def build_default_approval_transport(db: Optional[PipelineDB] = None) -> Optional[TelegramApprovalTransport]:
    """当已配置真实 telegram_bot_token 时构造默认 TelegramApprovalTransport，否则返回 None。"""
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return None
    return TelegramApprovalTransport(db=db, token=token)


def format_approval_html_and_keyboard(
    *,
    task_id: int,
    platform_post_id: str,
    comment_nickname: str,
    comment_content: str,
    chinese_reply: str,
    english_reply: str,
    style: str,
    reason_code: str,
    token: str,
) -> Tuple[str, List[List[Dict[str, str]]]]:
    """生成带有 HTML 转义和防超长 callback_data 的审批消息与按钮。"""
    # 严格 HTML 转义
    esc_nick = html.escape(comment_nickname or "匿名观众")
    esc_content = html.escape(comment_content or "")
    esc_zh = html.escape(chinese_reply or "")
    esc_en = html.escape(english_reply or "")
    esc_style = html.escape(style or "")
    esc_reason = html.escape(reason_code or "")
    short_post_id = html.escape(platform_post_id[:24] + "..." if len(platform_post_id) > 24 else platform_post_id)

    lines = [
        "📬 <b>视频号二级回复待审批</b>",
        f"🎬 <b>作品 ID</b>: <code>{short_post_id}</code>",
        f"👤 <b>观众昵称</b>: {esc_nick}",
        f"💬 <b>观众评论</b>:\n<blockquote>{esc_content}</blockquote>",
        f"🎨 <b>回复风格</b>: {esc_style} ({esc_reason})",
        "📝 <b>拟回复正文 (双语)</b>:",
        f"<blockquote>{esc_zh}\n{esc_en}</blockquote>",
        "<i>请在有效期限内审批；若评论或草稿重新生成，当前按钮将自动失效。</i>",
    ]
    message_text = "\n".join(lines)

    # 构造 callback_data: rep:{task_id}:{token_16}:{action}
    # 严格保证 callback_data 的 UTF-8 字节数 <= 64 字节！
    short_token = token  # 使用完整 token（22 字符，callback_data 仍 < 64 字节），禁止截断前缀匹配
    app_data = f"rep:{task_id}:{short_token}:app"
    rej_data = f"rep:{task_id}:{short_token}:rej"

    if len(app_data.encode("utf-8")) > MAX_TELEGRAM_CALLBACK_BYTES:
        raise ValueError(f"Approval callback_data exceeds Telegram 64-byte limit: {app_data}")
    if len(rej_data.encode("utf-8")) > MAX_TELEGRAM_CALLBACK_BYTES:
        raise ValueError(f"Rejection callback_data exceeds Telegram 64-byte limit: {rej_data}")

    keyboard = [
        [
            {"text": "✅ 批准发送", "callback_data": app_data},
            {"text": "❌ 拒绝", "callback_data": rej_data},
        ]
    ]

    return message_text, keyboard


def is_authorized_approver(approver_id: str, admin_ids_override: Optional[str] = None) -> bool:
    """检查审批人是否在系统管理员白名单中（显式拒绝 local_operator 等非人类占位身份）。"""
    clean_id = str(approver_id or "").strip()
    if not clean_id or clean_id == "local_operator":
        return False
    admin_str = admin_ids_override if admin_ids_override is not None else (settings.telegram_admin_ids or "")
    admin_list = [a.strip() for a in admin_str.split(",") if a.strip() and a.strip() != "local_operator"]
    return clean_id in admin_list


def dispatch_approval_request(
    db: PipelineDB,
    task_id: int,
    transport: Optional[Any] = None,
    expiry_hours: int = 2,
    approver_telegram_id: Optional[str] = None,
    approver_chat_id: Optional[str] = None,
    admin_ids_override: Optional[str] = None,
    expected_account_key: Optional[str] = None,
    ttl_minutes: Optional[int] = None,
    now_utc: Optional[datetime.datetime] = None,
) -> Tuple[bool, str]:
    """向指定审批人派发二级回复人工审批请求。

    失败关闭铁律：
    未配置审批人、审批人不在白名单内、chat_id 为本地伪造前缀或未接通可信传输通道时，
    任务必须停留在 PENDING_REVIEW，不广播、不暗中回退“第一管理员”或伪造发送成功。
    """
    configured_approver = str(approver_telegram_id or settings.wechat_reply_approver_telegram_id or "").strip()
    configured_chat = str(approver_chat_id or settings.wechat_reply_approver_chat_id or "").strip()

    if not configured_approver or not configured_chat:
        logger.info(
            "[SecondaryReplyApproval] 未显式配置 wechat_reply_approver_telegram_id 或 wechat_reply_approver_chat_id，任务留在待审核状态。"
        )
        return False, "APPROVER_NOT_CONFIGURED"

    if configured_chat.startswith("local-cli:"):
        logger.warning("[SecondaryReplyApproval] 拒绝使用 local-cli: 伪造会话 ID 派发审批请求: %s", configured_chat)
        return False, "INVALID_APPROVER_CHAT_ID"

    if not is_authorized_approver(configured_approver, admin_ids_override=admin_ids_override):
        logger.warning(
            "[SecondaryReplyApproval] 配置的审批人 %s 不在 telegram_admin_ids 白名单内，拒绝派发！",
            configured_approver,
        )
        return False, "APPROVER_NOT_IN_WHITELIST"

    if transport is None:
        logger.info("[SecondaryReplyApproval] 未接通外部可信审批传输通道，保持待审核状态。")
        return False, "APPROVAL_TRANSPORT_UNAVAILABLE"

    task = db.get_secondary_reply_task(task_id)
    if not task:
        return False, "TASK_NOT_FOUND"
    if expected_account_key is not None and (not expected_account_key or task.get("account_key") != expected_account_key):
        return False, "ACCOUNT_MISMATCH"
    if task.get("provider") == "rule_secondary_provider" and not getattr(transport, "allow_fixture_drafts", True):
        return False, "FIXTURE_PROVIDER_DRAFT_NOT_APPROVABLE"

    # 获取观众评论原文（经 PipelineDB 封装方法）
    audience_comment = db.get_audience_comment(
        task["account_key"], task["platform_post_id"], task["comment_id"]
    )
    nick = audience_comment.get("nickname", "观众") if audience_comment else "观众"
    content = audience_comment.get("content", "") if audience_comment else ""

    # 1. 生成不可预测随机 Token 与过期时间
    token = secrets.token_urlsafe(16)
    ttl_delta = (
        datetime.timedelta(minutes=max(1, int(ttl_minutes)))
        if ttl_minutes is not None
        else datetime.timedelta(hours=expiry_hours)
    )
    base_now = now_utc or datetime.datetime.now(datetime.timezone.utc)
    if base_now.tzinfo is None:
        base_now = base_now.replace(tzinfo=datetime.timezone.utc)
    expires_dt = base_now + ttl_delta
    expires_iso = expires_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 2. 服务端绑定 Token
    bound = db.bind_reply_task_approval_request(
        task_id=task_id,
        approval_token=token,
        expires_at_iso=expires_iso,
        approver_id=configured_approver,
        approver_chat_id=configured_chat,
        expected_account_key=expected_account_key,
    )
    if not bound:
        return False, "FAILED_TO_BIND_TOKEN"

    # 3. 构造转义消息与按钮
    msg_html, keyboard = format_approval_html_and_keyboard(
        task_id=task_id,
        platform_post_id=task["platform_post_id"],
        comment_nickname=nick,
        comment_content=content,
        chinese_reply=task["chinese_reply"],
        english_reply=task["english_reply"],
        style=task["style"],
        reason_code=task["reason_code"],
        token=token,
    )

    # 4. 发送通知
    try:
        try:
            send_res = transport.send_approval_message(
                chat_id=configured_chat,
                text=msg_html,
                inline_keyboard=keyboard,
                task_id=task_id,
            )
        except TypeError:
            send_res = transport.send_approval_message(
                chat_id=configured_chat,
                text=msg_html,
                inline_keyboard=keyboard,
            )
        if not send_res:
            return False, "TRANSPORT_REJECTED"
        if isinstance(send_res, str) and send_res.strip():
            db.record_reply_task_approval_message_id(task_id, send_res.strip())
        return True, "DISPATCHED"
    except Exception as exc:
        logger.error("[SecondaryReplyApproval] 审批消息推送异常: %s", exc)
        return False, f"TRANSPORT_ERROR: {exc}"


def handle_approval_callback(
    db: PipelineDB,
    callback_data: str,
    user_id: str,
    chat_id: str,
    admin_ids_override: Optional[str] = None,
    expected_account_key: Optional[str] = None,
) -> Tuple[bool, str]:
    """处理审批按钮回调并原子执行状态机消费。"""
    # 格式: rep:{task_id}:{token}:{action}
    parts = (callback_data or "").split(":")
    if len(parts) != 4 or parts[0] != "rep":
        return False, "INVALID_CALLBACK_FORMAT"

    try:
        task_id = int(parts[1])
    except ValueError:
        return False, "INVALID_TASK_ID"

    callback_token = parts[2]
    if not callback_token:
        return False, "TOKEN_MISMATCH"
    action_code = parts[3]
    action = "APPROVE" if action_code == "app" else ("REJECT" if action_code == "rej" else None)
    if not action:
        return False, f"INVALID_ACTION_CODE: {action_code}"

    # 审批人白名单校验（显式拒绝 local_operator 等自封身份）
    if not is_authorized_approver(user_id, admin_ids_override=admin_ids_override):
        logger.warning("[SecondaryReplyApproval] 非法用户 %s 试图点击审批按钮，拒绝！", user_id)
        return False, "UNAUTHORIZED_USER"

    task = db.get_secondary_reply_task(task_id)
    if not task:
        return False, "TASK_NOT_FOUND"

    # chat 身份必须由可信回调传入；缺失或为 local-cli: 伪造前缀一律拒绝
    clean_chat = str(chat_id or "").strip()
    if not clean_chat or clean_chat.startswith("local-cli:"):
        return False, "CHAT_MISMATCH"

    return db.consume_reply_task_approval(
        task_id=task_id,
        token=callback_token,
        approver_id=str(user_id).strip(),
        chat_id=clean_chat,
        action=action,
        expected_account_key=expected_account_key,
    )

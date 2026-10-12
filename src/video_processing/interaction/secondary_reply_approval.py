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
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现二级回复 Telegram 审批发送、防重放消费、HTML 转义与 64B callback_data 防护 |
"""

from __future__ import annotations

import datetime
import html
import logging
import secrets
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings
from video_processing.db.database import PipelineDB

logger = logging.getLogger(__name__)

MAX_TELEGRAM_CALLBACK_BYTES = 64


class ApprovalTransportError(Exception):
    """审批通知发送异常。"""


class FakeApprovalTransport:
    """用于测试与离线演示的 Fake Telegram 传输客户端。"""

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
    """检查审批人是否在系统管理员白名单中。"""
    if not approver_id:
        return False
    admin_str = admin_ids_override or settings.telegram_admin_ids or ""
    admin_list = [a.strip() for a in admin_str.split(",") if a.strip()]
    return str(approver_id).strip() in admin_list


def dispatch_approval_request(
    db: PipelineDB,
    task_id: int,
    transport: Optional[Any] = None,
    expiry_hours: int = 2,
    approver_telegram_id: Optional[str] = None,
    approver_chat_id: Optional[str] = None,
    admin_ids_override: Optional[str] = None,
) -> Tuple[bool, str]:
    """向指定审批人派发二级回复人工审批请求。

    失败关闭铁律：
    未配置审批人或审批人不在白名单内时，任务必须停留在 PENDING_REVIEW，
    不广播、不暗中回退“第一管理员”。
    """
    configured_approver = approver_telegram_id or settings.wechat_reply_approver_telegram_id
    configured_chat = approver_chat_id or settings.wechat_reply_approver_chat_id

    if not configured_approver or not configured_chat:
        logger.info(
            "[SecondaryReplyApproval] 未显式配置 wechat_reply_approver_telegram_id 或 wechat_reply_approver_chat_id，任务留在待审核状态。"
        )
        return False, "APPROVER_NOT_CONFIGURED"

    if not is_authorized_approver(configured_approver, admin_ids_override=admin_ids_override):
        logger.warning(
            "[SecondaryReplyApproval] 配置的审批人 %s 不在 telegram_admin_ids 白名单内，拒绝派发！",
            configured_approver,
        )
        return False, "APPROVER_NOT_IN_WHITELIST"

    task = db.get_secondary_reply_task(task_id)
    if not task:
        return False, "TASK_NOT_FOUND"

    comment_row = db.get_secondary_reply_task_by_comment(
        task["platform_post_id"], task["comment_id"]
    )
    # 获取观众评论原文
    audience_comment = None
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wechat_audience_comments WHERE platform_post_id = ? AND comment_id = ?",
            (task["platform_post_id"], task["comment_id"]),
        ).fetchone()
        if row:
            audience_comment = dict(row)

    nick = audience_comment.get("nickname", "观众") if audience_comment else "观众"
    content = audience_comment.get("content", "") if audience_comment else ""

    # 1. 生成不可预测随机 Token 与过期时间
    token = secrets.token_urlsafe(16)
    expires_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=expiry_hours)
    expires_iso = expires_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 2. 服务端绑定 Token
    bound = db.bind_reply_task_approval_request(
        task_id=task_id,
        approval_token=token,
        expires_at_iso=expires_iso,
        approver_id=configured_approver,
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
    active_transport = transport or FakeApprovalTransport()
    try:
        active_transport.send_approval_message(
            chat_id=configured_chat,
            text=msg_html,
            inline_keyboard=keyboard,
        )
        return True, "DISPATCHED"
    except Exception as exc:
        logger.error("[SecondaryReplyApproval] 审批消息推送异常: %s", exc)
        return False, f"TRANSPORT_ERROR: {exc}"


def handle_approval_callback(
    db: PipelineDB,
    callback_data: str,
    user_id: str,
    admin_ids_override: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """处理审批按钮回调并原子执行状态机消费。"""
    # 格式: rep:{task_id}:{token}:{action}
    parts = callback_data.split(":")
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

    # 审批人白名单校验
    if not is_authorized_approver(user_id, admin_ids_override=admin_ids_override):
        logger.warning("[SecondaryReplyApproval] 非法用户 %s 试图点击审批按钮，拒绝！", user_id)
        return False, "UNAUTHORIZED_USER"

    task = db.get_secondary_reply_task(task_id)
    if not task:
        return False, "TASK_NOT_FOUND"

    # 若调用方提供了 chat 身份，必须与配置的审批私聊一致（失败关闭）
    configured_chat = str(getattr(settings, "wechat_reply_approver_chat_id", "") or "")
    if chat_id is not None and configured_chat and str(chat_id) != configured_chat:
        return False, "CHAT_MISMATCH"

    return db.consume_reply_task_approval(
        task_id=task_id,
        token=callback_token,
        approver_id=str(user_id),
        action=action,
    )

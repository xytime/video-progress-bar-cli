"""二级回复人工审批版：单条真实操作入口的业务逻辑（预检/人工文案导入/审批请求派发/审批回调消费/提交/平台对账/停用）。

设计边界：
- 全部走既有统一编排（``SecondaryReplyOrchestrator``）；本模块不直接写任何发送成功状态，不批量，不常驻。
- 文案来源只有“人工撰写并导入”一条路径（provider=manual_import），覆盖人工审批版试运行；
  **不是自动生成能力**，规则 provider 仍仅限 fixture。
- 严格区分三件事：
  1. 草稿只读检查（``preflight``）：核对配置、开关、配额、防重账本与正文 SHA256；
  2. 正文哈希确认与发起审批请求（``request_approval``）：核对 ``confirm_reply_sha12`` 一致后，
     向白名单审批人绑定一次性随机 token、账号/作品/父评论/源评论哈希/草稿版本/最终正文哈希/有效期并派发外部审批卡片；
     未接通可信外部审批传输通道时保持 ``PENDING_REVIEW`` 且返回 ``APPROVAL_TRANSPORT_UNAVAILABLE``；
  3. 有效发送批准（``approve_callback``）：仅接受来自白名单审批人（``telegram_admin_ids``）与绑定 ``chat_id`` 的
     一次性回调 token 消费，消费成功后任务才进入 ``APPROVED``。
- 旧 ``approve_local`` 命令行自批入口已废止并硬拒绝（``SELF_APPROVAL_DISABLED_REQUIRES_VERIFIED_CALLBACK``），
  防止同一本地执行者通过填写配置字符串或回填哈希将草稿自批为 ``APPROVED``。
- 真实信任边界声明：应用层审批绑定与回调校验可阻止未获批任务在正常 CLI/编排链路中进入发送，但无法防御拥有本机任意代码修改或 SQLite 直接写权限的操作者。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-10-17 | Antigravity | 收紧 verify_platform 强类型证据契约；废止 approve_local 自批，拆分 request_approval 与 approve_callback |
| 1.2.0 | 2026-10-17 | Codex | 完善 verify_platform 回传原生作者身份与评论正文新鲜度校验字段 (M2) |
| 1.1.0 | 2026-10-17 | Codex | 新增 verify_platform 实现平台只读控件校准与三态验证 (R1) |
| 1.0.0 | 2026-10-13 | Antigravity | 新增：M3 单条操作入口逻辑（预检/导入/本地审批/提交/平台对账/停用/状态） |
"""

from __future__ import annotations

import datetime
import hashlib
import json
import secrets
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_approval import (
    DISALLOWED_LOCAL_APPROVER_IDS,
    DISALLOWED_LOCAL_CHAT_PREFIXES,
    dispatch_approval_request,
    handle_approval_callback,
    is_authorized_approver,
)
from video_processing.interaction.secondary_reply_contract import (
    PlatformVerificationReport,
    SecondaryReplyContractError,
    validate_reply_length_and_format,
)
from video_processing.interaction.secondary_reply_orchestrator import (
    SecondaryReplyOrchestrator,
    SecondaryReplyPlatformPort,
)
from video_processing.interaction.secondary_reply_service import SecondaryReplyCensor, SecondaryReplyService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STOP_FILE = PROJECT_ROOT / "output" / "secondary_reply.STOP"
DEFAULT_EVIDENCE_DIR = PROJECT_ROOT / "output" / "secondary_reply_evidence"
MANUAL_PROVIDER = "manual_import"


def _sha(text: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", text or "").encode("utf-8")).hexdigest()


def _service() -> SecondaryReplyService:
    return SecondaryReplyService(censor=SecondaryReplyCensor())


def configured_approver_target(
    admin_ids_override: Optional[str] = None,
) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """校验并返回显式配置的受信任审批人身份与私聊会话目标。

    规则：
    - 必须显式配置 ``wechat_reply_approver_telegram_id`` 与 ``wechat_reply_approver_chat_id``；
    - 严禁使用 ``local_operator`` 等本地占位身份或 ``local-cli:`` 伪会话前缀；
    - 审批人 ID 必须在 ``telegram_admin_ids`` 白名单内。
    """
    approver = (settings.wechat_reply_approver_telegram_id or "").strip()
    if not approver:
        return None, "APPROVER_NOT_CONFIGURED（未配置 wechat_reply_approver_telegram_id，不推断审批人）"
    if approver.lower() in DISALLOWED_LOCAL_APPROVER_IDS:
        return None, "LOCAL_OPERATOR_SELF_APPROVAL_FORBIDDEN（禁止使用 local_operator 作为人类审批身份）"
    if not is_authorized_approver(approver, admin_ids_override=admin_ids_override):
        return None, "APPROVER_NOT_IN_ADMIN_WHITELIST（wechat_reply_approver_telegram_id 不在 telegram_admin_ids 白名单内）"
    chat = (settings.wechat_reply_approver_chat_id or "").strip()
    if not chat:
        return None, "APPROVER_CHAT_ID_NOT_CONFIGURED（未配置 wechat_reply_approver_chat_id，禁止回退到 local-cli 伪会话）"
    if any(chat.lower().startswith(prefix) for prefix in DISALLOWED_LOCAL_CHAT_PREFIXES):
        return None, "LOCAL_CLI_CHAT_ID_FORBIDDEN（禁止使用 local-cli: 伪会话作为审批目标）"
    return {"approver_id": approver, "chat_id": chat}, None


def local_approver_identity() -> Optional[Dict[str, str]]:
    """兼容读取已通过白名单与真实会话校验的审批人配置；未配置或含本地伪身份时返回 None。"""
    ident, _ = configured_approver_target()
    return ident


# ---------------------------------------------------------------- 导入 ----

def import_manual_draft(
    db: PipelineDB, *, account_key: str, post_id: str, comment_id: str, comment_text: str,
    zh: str, en: str, style: str = "CASUAL_LIGHT",
) -> Dict[str, Any]:
    """导入一条人工撰写的双语回复为待审草稿；经确定性格式与政策终审检查，不合格直接拒绝。"""
    if not account_key:
        return {"ok": False, "reason": "ACCOUNT_KEY_REQUIRED"}
    try:
        zh_nfc, en_nfc, formatted = validate_reply_length_and_format(zh, en)
        _service().validate_for_submission(zh_nfc, en_nfc, formatted)
    except Exception as exc:
        return {"ok": False, "reason": f"CONTENT_REJECTED: {exc}"}
    db.save_discovered_audience_comments(
        post_id, [{"comment_id": comment_id, "content": comment_text}], account_key=account_key
    )
    task_id = db.create_or_update_secondary_reply_task(
        account_key=account_key, platform_post_id=post_id, comment_id=comment_id, intent="REPLY", style=style,
        chinese_reply=zh_nfc, english_reply=en_nfc, formatted_reply=formatted, reason_code="MANUAL_AUTHORED",
        evidence_refs=[], provider=MANUAL_PROVIDER, status="PENDING_REVIEW",
    )
    return {"ok": True, "task_id": task_id, "reply_sha256": _sha(formatted)}


# ---------------------------------------------------------------- 预检 ----

def preflight(db: PipelineDB, task_id: int, *, account_key: str, finder_id: str) -> Dict[str, Any]:
    """只读预检：展示将要发送的一切，并列出阻断项。不访问平台，不写库。"""
    task = db.get_secondary_reply_task(task_id)
    blockers: List[str] = []
    if not task:
        return {"ok": False, "blockers": ["TASK_NOT_FOUND"]}
    if (task.get("account_key") or "") != account_key:
        blockers.append("ACCOUNT_KEY_MISMATCH")
    if not finder_id:
        blockers.append("AUTHOR_FINDER_ID_NOT_CONFIGURED")
    if not settings.enable_wechat_secondary_reply:
        blockers.append("FLAG_enable_wechat_secondary_reply_OFF")
    if not settings.enable_wechat_secondary_reply_live_submission:
        blockers.append("FLAG_enable_wechat_secondary_reply_live_submission_OFF")
    if DEFAULT_STOP_FILE.exists():
        blockers.append("STOP_FILE_PRESENT")
    if task["provider"] == "rule_secondary_provider":
        blockers.append("FIXTURE_PROVIDER_DRAFT_NOT_SENDABLE")
    if task["status"] != "APPROVED":
        blockers.append(f"STATUS_{task['status']}_NOT_APPROVED")
    else:
        approver_id = str(task.get("approver_id") or "").strip()
        approver_chat_id = str(task.get("approver_chat_id") or "").strip()
        if (
            not approver_id
            or approver_id.lower() in DISALLOWED_LOCAL_APPROVER_IDS
            or not is_authorized_approver(approver_id)
            or not approver_chat_id
            or any(approver_chat_id.lower().startswith(p) for p in DISALLOWED_LOCAL_CHAT_PREFIXES)
        ):
            blockers.append("UNVERIFIED_OR_SELF_APPROVED_IDENTITY")
    ledger = db.check_secondary_reply_idempotency(task["platform_post_id"], task["comment_id"], account_key=account_key)
    if ledger:
        blockers.append(f"LEDGER_{ledger['status']}_BLOCKS_SEND")
    quota_ok, quota_reason = db.check_wechat_reply_quota(task["platform_post_id"])
    if not quota_ok:
        blockers.append(f"QUOTA_{quota_reason}")
    return {
        "ok": not blockers, "blockers": blockers, "mode": "PREFLIGHT_LOCAL_READ_ONLY",
        "account_key": account_key, "author_finder_id": finder_id,
        "platform_post_id": task["platform_post_id"], "root_comment_id": task["comment_id"],
        "task_id": task_id, "status": task["status"], "provider": task["provider"],
        "reply_zh": task["chinese_reply"], "reply_en": task["english_reply"],
        "reply_sha256": _sha(task["formatted_reply"] or ""),
        "approval": {
            "approver_id": task.get("approver_id"), "approver_chat_id": task.get("approver_chat_id"),
            "expires_at": task.get("approval_expires_at"), "approved_at": task.get("approved_at"),
            "bound_source_comment_hash": task.get("bound_source_comment_hash"),
            "bound_reply_text_hash": task.get("bound_reply_text_hash"),
        },
        "quota": {"allowed": quota_ok, "reason": quota_reason},
        "platform_checks_not_done_here": "作品/父评论是否存在、作者是否已回复将在提交时锁内由平台复核",
    }


# ---------------------------------------------------------------- 审批请求与回调验证 ----

def _validate_task_for_hash_confirmation(
    db: PipelineDB,
    task_id: int,
    *,
    account_key: str,
    confirm_reply_sha12: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """核对任务归属、可审批状态与正文 SHA256 前 12 位一致性（仅证明正文一致，不产生批准状态）。"""
    task = db.get_secondary_reply_task(task_id)
    if not task:
        return None, {"ok": False, "reason": "TASK_NOT_FOUND"}
    if not account_key or task["account_key"] != account_key:
        return None, {"ok": False, "reason": "ACCOUNT_MISMATCH"}
    if task["status"] not in ("PENDING_REVIEW", "DRAFTED"):
        return None, {"ok": False, "reason": f"INVALID_STATUS: {task['status']}"}
    if task["provider"] == "rule_secondary_provider":
        return None, {"ok": False, "reason": "FIXTURE_PROVIDER_DRAFT_NOT_APPROVABLE"}
    expected = _sha(task["formatted_reply"] or "")[:12]
    if not confirm_reply_sha12 or confirm_reply_sha12.strip().lower() != expected:
        return None, {"ok": False, "reason": "CONFIRM_HASH_MISMATCH（请以预检输出的 reply_sha256 前 12 位确认）"}
    return task, None


def request_approval(
    db: PipelineDB,
    task_id: int,
    *,
    account_key: str,
    confirm_reply_sha12: str,
    transport: Optional[Any] = None,
    ttl_minutes: int = 60,
    admin_ids_override: Optional[str] = None,
) -> Dict[str, Any]:
    """确认待审草稿正文哈希并向受信任人类审批通道派发一次性审批请求。

    注意：
    - 本函数只完成“正文哈希确认 + 绑定待审 token + 派发审批卡片”，任务状态保持 ``PENDING_REVIEW``；
    - 绝不在此处消费 token 或将任务设为 ``APPROVED``；
    - 当未接通外部可验证审批传输通道（``transport is None``）时保持失败关闭（``APPROVAL_TRANSPORT_UNAVAILABLE``）。
    """
    task, err = _validate_task_for_hash_confirmation(
        db, task_id, account_key=account_key, confirm_reply_sha12=confirm_reply_sha12
    )
    if err is not None:
        return err

    ident, ident_err = configured_approver_target(admin_ids_override=admin_ids_override)
    if not ident:
        return {
            "ok": False,
            "status": task["status"],
            "hash_confirmed": True,
            "reason": ident_err or "APPROVER_NOT_CONFIGURED",
        }

    if transport is None:
        return {
            "ok": False,
            "status": "PENDING_REVIEW",
            "hash_confirmed": True,
            "approval_requested": False,
            "reason": "APPROVAL_TRANSPORT_UNAVAILABLE",
            "remaining_conditions": (
                "正文哈希已确认一致，但当前未接通真实外部审批通知通道（如 Telegram Bot Transport）；"
                "任务保持 PENDING_REVIEW 且发送不可用。需接入可验证的 ApprovalNotificationTransport 派发审批卡片，"
                "并由白名单审批人触发 approve-callback 完成一次性令牌消费后，任务才可进入 APPROVED。"
            ),
        }

    ok, msg = dispatch_approval_request(
        db=db,
        task_id=task_id,
        transport=transport,
        approver_telegram_id=ident["approver_id"],
        approver_chat_id=ident["chat_id"],
        ttl_minutes=ttl_minutes,
        admin_ids_override=admin_ids_override,
        expected_account_key=account_key,
    )
    refreshed = db.get_secondary_reply_task(task_id) or task
    return {
        "ok": bool(ok),
        "status": refreshed.get("status", "PENDING_REVIEW"),
        "hash_confirmed": True,
        "approval_requested": bool(ok),
        "reason": msg,
        "approver_id": ident["approver_id"],
        "approver_chat_id": ident["chat_id"],
        "expires_at_utc": refreshed.get("approval_expires_at"),
    }


def approve_callback(
    db: PipelineDB,
    *,
    callback_data: str,
    user_id: str,
    chat_id: str,
    account_key: str,
    admin_ids_override: Optional[str] = None,
) -> Dict[str, Any]:
    """处理来自可验证人类审批通道（Telegram 回调）的批准/拒绝动作，执行一次性原子消费。"""
    if not account_key:
        return {"ok": False, "reason": "ACCOUNT_KEY_NOT_CONFIGURED"}
    ident, ident_err = configured_approver_target(admin_ids_override=admin_ids_override)
    if not ident:
        return {"ok": False, "reason": ident_err or "APPROVER_NOT_CONFIGURED"}
    clean_user = str(user_id or "").strip()
    clean_chat = str(chat_id or "").strip()
    if clean_user != ident["approver_id"] or clean_chat != ident["chat_id"]:
        return {"ok": False, "reason": "CALLBACK_SENDER_MISMATCH_WITH_CONFIGURED_APPROVER"}

    ok, msg = handle_approval_callback(
        db=db,
        callback_data=callback_data,
        user_id=clean_user,
        chat_id=clean_chat,
        admin_ids_override=admin_ids_override,
        expected_account_key=account_key,
    )
    return {
        "ok": bool(ok),
        "result": msg,
        "reason": msg,
        "approver_id": clean_user,
        "approver_chat_id": clean_chat,
    }


def approve_local(
    db: PipelineDB, task_id: int, *, account_key: str, confirm_reply_sha12: str, ttl_minutes: int = 60,
) -> Dict[str, Any]:
    """已废止的本地命令行自批入口（硬拒绝直接置为 APPROVED，保留参数校验与明确迁移说明）。"""
    _ = ttl_minutes
    task, err = _validate_task_for_hash_confirmation(
        db, task_id, account_key=account_key, confirm_reply_sha12=confirm_reply_sha12
    )
    if err is not None:
        return err
    return {
        "ok": False,
        "status": task["status"],
        "hash_confirmed": True,
        "reason": "SELF_APPROVAL_DISABLED_REQUIRES_VERIFIED_CALLBACK",
        "migration": (
            "本地直接自批（approve / approve_local）已禁用：哈希确认仅证明正文一致，不能替代人类审批。"
            "请迁移为两步闭环：(1) 使用 request-approval 确认正文哈希前 12 位并向白名单审批人派发一次性审批请求；"
            "(2) 由白名单审批人通过可验证回调入口 approve-callback 消费一次性 token 后，任务方可转为 APPROVED。"
        ),
    }


# ---------------------------------------------------------------- 提交 / 对账 ----

def _orchestrator(
    db: PipelineDB,
    platform: SecondaryReplyPlatformPort,
    account_key: str,
    evidence_dir: Optional[Path],
    approval_transport: Optional[Any] = None,
) -> SecondaryReplyOrchestrator:
    ident, _ = configured_approver_target()
    approver_id = ident["approver_id"] if ident else ""
    approver_chat_id = ident["chat_id"] if ident else ""

    return SecondaryReplyOrchestrator(
        db=db,
        service=_service(),
        platform=platform,
        approval_transport=approval_transport,
        account_key=account_key,
        approver_id=approver_id,
        approver_chat_id=approver_chat_id,
        admin_ids_override=None,
        allow_fixture_drafts=False,
        evidence_dir=evidence_dir or DEFAULT_EVIDENCE_DIR,
    )


def submit_single(
    db: PipelineDB, task_id: int, *, platform: SecondaryReplyPlatformPort, account_key: str,
    evidence_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """单条提交：开关/停止文件与已验证审批身份在访问平台之前检查；其后全部经统一编排。"""
    if not settings.enable_wechat_secondary_reply:
        return {"ok": False, "reason": "FLAG_enable_wechat_secondary_reply_OFF"}
    if not settings.enable_wechat_secondary_reply_live_submission:
        return {"ok": False, "reason": "FLAG_enable_wechat_secondary_reply_live_submission_OFF"}
    if DEFAULT_STOP_FILE.exists():
        return {"ok": False, "reason": "STOP_FILE_PRESENT"}
    ident, ident_err = configured_approver_target()
    if not ident:
        return {"ok": False, "reason": ident_err or "APPROVER_NOT_CONFIGURED"}
    out = _orchestrator(db, platform, account_key, evidence_dir).submit(task_id)
    return {"ok": out.status == "VERIFIED", "status": out.status, "detail": out.detail, "extra": out.extra}


def reconcile_on_platform(
    db: PipelineDB, task_id: int, *, platform: SecondaryReplyPlatformPort, account_key: str,
    evidence_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """平台对账：真正读取平台（只读，不发写请求）。不要求提交闸门开启，以便停用后仍可收尾。"""
    out = _orchestrator(db, platform, account_key, evidence_dir).reconcile(task_id)
    return {"ok": out.status == "VERIFIED", "status": out.status, "detail": out.detail, "extra": out.extra,
            "mode": "PLATFORM_READ_ONLY_RECONCILE"}


# ---------------------------------------------------------------- 状态 / 停用 ----

def status_summary(db: PipelineDB) -> Dict[str, Any]:
    pending = db.get_uncertain_secondary_reply_tasks(None)
    return {
        "flags": {
            "enable_wechat_secondary_reply": bool(settings.enable_wechat_secondary_reply),
            "enable_wechat_secondary_reply_live_submission": bool(settings.enable_wechat_secondary_reply_live_submission),
        },
        "stop_file_present": DEFAULT_STOP_FILE.exists(),
        "needs_platform_reconcile": [
            {"task_id": t["id"], "status": t["status"], "post": t["platform_post_id"], "comment": t["comment_id"]}
            for t in pending
        ],
    }


def stop(stop_file: Optional[Path] = None) -> Dict[str, Any]:
    path = stop_file or DEFAULT_STOP_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat(), encoding="utf-8")
    return {"stopped": True, "stop_file": str(path)}


def resume(stop_file: Optional[Path] = None) -> Dict[str, Any]:
    path = stop_file or DEFAULT_STOP_FILE
    if path.exists():
        path.unlink()
    return {"stopped": False, "stop_file": str(path)}


def verify_platform(
    db: Optional[PipelineDB],
    *,
    post_id: str,
    comment_id: str,
    platform: Any,
    account_key: str,
    finder_id: str,
    video_title: Optional[str] = None,
    comment_text: Optional[str] = None,
    evidence_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """真实平台只读校准与状态验证（零写操作、零出站请求，强类型契约校验）。"""
    _ = db
    if not account_key:
        return {"ok": False, "status": "UNKNOWN", "reason": "ACCOUNT_KEY_NOT_CONFIGURED"}
    if not finder_id:
        return {"ok": False, "status": "UNKNOWN", "reason": "AUTHOR_FINDER_ID_NOT_CONFIGURED"}
    clean_post = str(post_id or "").strip()
    clean_comment = str(comment_id or "").strip()
    if not clean_post:
        return {"ok": False, "status": "UNKNOWN", "reason": "POST_ID_REQUIRED"}
    if not clean_comment:
        return {"ok": False, "status": "UNKNOWN", "reason": "COMMENT_ID_REQUIRED"}

    calibrate_fn = getattr(platform, "calibrate_and_verify", None)
    if not callable(calibrate_fn):
        return {"ok": False, "status": "UNKNOWN", "reason": "PLATFORM_DOES_NOT_SUPPORT_CALIBRATION"}

    out_base = evidence_dir or DEFAULT_EVIDENCE_DIR
    attempt_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(4)
    attempt_dir = Path(out_base) / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=True)

    try:
        raw_res = calibrate_fn(
            post_id=clean_post,
            root_id=clean_comment,
            video_title=video_title,
            comment_text=comment_text,
            evidence_dir=attempt_dir,
        )
        report = PlatformVerificationReport.from_raw(
            raw_res,
            account_key=account_key,
            expected_finder_id=finder_id,
            expected_post_id=clean_post,
            expected_comment_id=clean_comment,
            expected_video_title=video_title,
            expected_comment_text=comment_text,
        )
    except SecondaryReplyContractError as exc:
        return {
            "ok": False,
            "status": "UNKNOWN",
            "reason": f"PLATFORM_VERIFICATION_CONTRACT_ERROR: {exc}",
            "channel_profile": {
                "account_key": account_key,
                "finder_id": finder_id,
                "expected_finder_id": finder_id,
                "native_username": "",
                "observed_native_username": "",
                "channel_nickname": "",
                "identity_verified": False,
            },
            "target": {
                "post_id": "",
                "comment_id": "",
                "expected_post_id": clean_post,
                "expected_comment_id": clean_comment,
                "expected_comment_text": str(comment_text or "").strip(),
                "video_title": str(video_title or "").strip(),
                "author_nickname": "",
                "comment_text": "",
                "observed_comment_text": "",
                "text_matched": False,
                "fresh": False,
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "UNKNOWN",
            "reason": f"PLATFORM_VERIFICATION_EXCEPTION: {exc}",
            "channel_profile": {
                "account_key": account_key,
                "finder_id": finder_id,
                "expected_finder_id": finder_id,
                "native_username": "",
                "observed_native_username": "",
                "channel_nickname": "",
                "identity_verified": False,
            },
            "target": {
                "post_id": "",
                "comment_id": "",
                "expected_post_id": clean_post,
                "expected_comment_id": clean_comment,
                "expected_comment_text": str(comment_text or "").strip(),
                "video_title": str(video_title or "").strip(),
                "author_nickname": "",
                "comment_text": "",
                "observed_comment_text": "",
                "text_matched": False,
                "fresh": False,
            },
        }

    evidence_json_path = attempt_dir / "platform_verification.json"
    result = report.to_dict()
    result["evidence_files"] = {
        "json": str(report.evidence_files.get("json") or evidence_json_path),
        "screenshot": str(report.evidence_files.get("screenshot") or (attempt_dir / "platform_verification.png")),
    }

    try:
        with open(evidence_json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass

    return result


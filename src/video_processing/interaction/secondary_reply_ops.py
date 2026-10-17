"""二级回复人工审批版：单条真实操作入口的业务逻辑（预检/人工文案导入/本地人工审批/提交/平台对账/停用）。

设计边界：
- 全部走既有统一编排（``SecondaryReplyOrchestrator``）；本模块不写任何成功状态，不批量，不常驻。
- 文案来源只有“人工撰写并导入”一条路径（provider=manual_import），覆盖人工审批版试运行；
  **不是自动生成能力**，规则 provider 仍仅限 fixture。
- 本地人工审批：以配置的审批人身份、一次性随机 token、目标/正文/源评论快照/有效期绑定，
  经与 Telegram 审批相同的 DAL 绑定与消费（原子、一次性）。操作者身份由本机运行者与配置共同声明（未验证项）。
- 作者身份：发送守卫要求请求载荷中的 ``_log_finder_id`` 与配置的作者原生标识一致（该字段来自真实登录会话），
  不一致则网络前中止；account_key 与 finder_id 的配置绑定仍需 M3 只读样本进一步验证。
- 停用开关：``stop`` 写入停止文件，``submit`` 在读取任何平台之前拒绝。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
from typing import Any, Callable, Dict, List, Optional

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_orchestrator import (
    SecondaryReplyOrchestrator,
    SecondaryReplyPlatformPort,
)
from video_processing.interaction.secondary_reply_service import SecondaryReplyCensor, SecondaryReplyService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STOP_FILE = PROJECT_ROOT / "output" / "secondary_reply.STOP"
DEFAULT_EVIDENCE_DIR = PROJECT_ROOT / "output" / "secondary_reply_evidence"
MANUAL_PROVIDER = "manual_import"
LOCAL_CHAT_PREFIX = "local-cli:"


def _sha(text: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", text or "").encode("utf-8")).hexdigest()


def _service() -> SecondaryReplyService:
    return SecondaryReplyService(censor=SecondaryReplyCensor())


def local_approver_identity() -> Optional[Dict[str, str]]:
    """本地审批身份必须显式配置，未配置不得推断。"""
    approver = (settings.wechat_reply_approver_telegram_id or "").strip()
    if not approver:
        return None
    chat = (settings.wechat_reply_approver_chat_id or "").strip() or f"{LOCAL_CHAT_PREFIX}{approver}"
    return {"approver_id": approver, "chat_id": chat}


# ---------------------------------------------------------------- 导入 ----

def import_manual_draft(
    db: PipelineDB, *, account_key: str, post_id: str, comment_id: str, comment_text: str,
    zh: str, en: str, style: str = "CASUAL_LIGHT",
) -> Dict[str, Any]:
    """导入一条人工撰写的双语回复为待审草稿；经确定性格式与政策终审检查，不合格直接拒绝。"""
    if not account_key:
        return {"ok": False, "reason": "ACCOUNT_KEY_REQUIRED"}
    formatted = f"{zh}\n{en}"
    try:
        _service().validate_for_submission(zh, en, formatted)
    except Exception as exc:
        return {"ok": False, "reason": f"CONTENT_REJECTED: {exc}"}
    db.save_discovered_audience_comments(
        post_id, [{"comment_id": comment_id, "content": comment_text}], account_key=account_key
    )
    task_id = db.create_or_update_secondary_reply_task(
        account_key=account_key, platform_post_id=post_id, comment_id=comment_id, intent="REPLY", style=style,
        chinese_reply=zh, english_reply=en, formatted_reply=formatted, reason_code="MANUAL_AUTHORED",
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


# ---------------------------------------------------------------- 本地人工审批 ----

def approve_local(
    db: PipelineDB, task_id: int, *, account_key: str, confirm_reply_sha12: str, ttl_minutes: int = 60,
) -> Dict[str, Any]:
    """本地人工审批：操作者必须回填正文哈希前 12 位以证明已核对将发送的正文。"""
    ident = local_approver_identity()
    if not ident:
        return {"ok": False, "reason": "APPROVER_NOT_CONFIGURED（不推断审批人）"}
    task = db.get_secondary_reply_task(task_id)
    if not task:
        return {"ok": False, "reason": "TASK_NOT_FOUND"}
    if not account_key or task["account_key"] != account_key:
        return {"ok": False, "reason": "ACCOUNT_MISMATCH"}
    if task["status"] not in ("PENDING_REVIEW", "DRAFTED"):
        return {"ok": False, "reason": f"INVALID_STATUS: {task['status']}"}
    if task["provider"] == "rule_secondary_provider":
        return {"ok": False, "reason": "FIXTURE_PROVIDER_DRAFT_NOT_APPROVABLE"}
    expected = _sha(task["formatted_reply"] or "")[:12]
    if not confirm_reply_sha12 or confirm_reply_sha12.strip().lower() != expected:
        return {"ok": False, "reason": "CONFIRM_HASH_MISMATCH（请以预检输出的 reply_sha256 前 12 位确认）"}
    token = secrets.token_urlsafe(16)
    expires = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ttl_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    if not db.bind_reply_task_approval_request(
        task_id, approval_token=token, expires_at_iso=expires, expected_account_key=account_key,
        approver_id=ident["approver_id"], approver_chat_id=ident["chat_id"],
    ):
        return {"ok": False, "reason": "BIND_FAILED"}
    ok, msg = db.consume_reply_task_approval(
        task_id=task_id, token=token, approver_id=ident["approver_id"], chat_id=ident["chat_id"], action="APPROVE",
        expected_account_key=account_key,
    )
    return {"ok": bool(ok), "result": msg, "expires_at_utc": expires, "approver_id": ident["approver_id"]}


# ---------------------------------------------------------------- 提交 / 对账 ----

def _orchestrator(db: PipelineDB, platform: SecondaryReplyPlatformPort, account_key: str,
                  evidence_dir: Optional[Path]) -> SecondaryReplyOrchestrator:
    ident = local_approver_identity() or {"approver_id": "unconfigured", "chat_id": "unconfigured"}
    from video_processing.interaction.secondary_reply_approval import FakeApprovalTransport

    return SecondaryReplyOrchestrator(
        db=db, service=_service(), platform=platform,
        approval_transport=FakeApprovalTransport(),  # 本入口不派发审批消息；审批走 approve_local
        account_key=account_key, approver_id=ident["approver_id"], approver_chat_id=ident["chat_id"],
        admin_ids_override=ident["approver_id"], allow_fixture_drafts=False,
        evidence_dir=evidence_dir or DEFAULT_EVIDENCE_DIR,
    )


def submit_single(
    db: PipelineDB, task_id: int, *, platform: SecondaryReplyPlatformPort, account_key: str,
    evidence_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """单条提交：开关/停止文件在访问平台之前检查；其后全部经统一编排。"""
    if not settings.enable_wechat_secondary_reply:
        return {"ok": False, "reason": "FLAG_enable_wechat_secondary_reply_OFF"}
    if not settings.enable_wechat_secondary_reply_live_submission:
        return {"ok": False, "reason": "FLAG_enable_wechat_secondary_reply_live_submission_OFF"}
    if DEFAULT_STOP_FILE.exists():
        return {"ok": False, "reason": "STOP_FILE_PRESENT"}
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
    """真实平台只读校准与状态验证（零写操作、零出站请求）。"""
    if not account_key:
        return {"ok": False, "reason": "ACCOUNT_KEY_NOT_CONFIGURED"}
    if not finder_id:
        return {"ok": False, "reason": "AUTHOR_FINDER_ID_NOT_CONFIGURED"}
    clean_post = str(post_id or "").strip()
    clean_comment = str(comment_id or "").strip()
    if not clean_post:
        return {"ok": False, "reason": "POST_ID_REQUIRED"}
    if not clean_comment:
        return {"ok": False, "reason": "COMMENT_ID_REQUIRED"}

    out_base = evidence_dir or DEFAULT_EVIDENCE_DIR
    attempt_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(4)
    attempt_dir = Path(out_base) / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=True)

    if not hasattr(platform, "calibrate_and_verify") and not hasattr(platform, "calibrate_controls"):
        return {"ok": False, "reason": "PLATFORM_DOES_NOT_SUPPORT_CALIBRATION"}

    try:
        if hasattr(platform, "calibrate_and_verify"):
            raw_res = platform.calibrate_and_verify(
                post_id=clean_post,
                root_id=clean_comment,
                video_title=video_title,
                comment_text=comment_text,
                evidence_dir=attempt_dir,
            )
        else:
            raw_res = platform.calibrate_controls(
                post_id=clean_post,
                root_id=clean_comment,
                evidence_dir=attempt_dir,
            )
    except Exception as exc:
        return {
            "ok": False,
            "status": "UNKNOWN",
            "reason": f"PLATFORM_VERIFICATION_EXCEPTION: {exc}",
            "channel_profile": {"account_key": account_key, "finder_id": finder_id},
            "target": {"post_id": clean_post, "comment_id": clean_comment, "fresh": False},
        }

    status = raw_res.get("status", "UNKNOWN")
    controls = raw_res.get("controls_calibration", {})
    evidence_files = raw_res.get("evidence_files", {})

    evidence_json_path = attempt_dir / "platform_verification.json"
    raw_profile = raw_res.get("channel_profile", {})
    raw_target = raw_res.get("target", {})
    result = {
        "ok": bool(raw_res.get("ok", False)),
        "status": status,
        "channel_profile": {
            "account_key": account_key,
            "finder_id": finder_id,
            "native_username": raw_profile.get("native_username") or finder_id,
            "channel_nickname": raw_profile.get("channel_nickname") or "",
            "identity_verified": bool(raw_profile.get("identity_verified", True)),
        },
        "target": {
            "post_id": clean_post,
            "comment_id": clean_comment,
            "video_title": video_title or raw_target.get("video_title", ""),
            "author_nickname": raw_target.get("author_nickname", ""),
            "comment_text": raw_target.get("comment_text") or comment_text or "",
            "text_matched": bool(raw_target.get("text_matched", True)),
            "fresh": bool(raw_target.get("fresh", status != "UNKNOWN")),
        },
        "controls_calibration": controls,
        "evidence_files": {
            "json": str(evidence_files.get("json") or evidence_json_path),
            "screenshot": str(evidence_files.get("screenshot") or (attempt_dir / "platform_verification.png")),
        },
        "mode": "PLATFORM_READ_ONLY_CALIBRATION_AND_VERIFICATION",
    }
    if not result["ok"] and "reason" in raw_res:
        result["reason"] = raw_res["reason"]

    try:
        with open(evidence_json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass

    return result

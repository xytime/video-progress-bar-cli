"""视频号二级回复有界单周期调度器 (Bounded Tick Runner, M3.5)。

按四阶段顺序在单次 Tick 中执行有界任务，不常驻后台死循环：
1. Phase 0 (对账优先): 取到期 (``next_reconcile_at <= now``) 且未超上限的 ``UNCERTAIN`` 任务执行只读平台对账（每 Tick 最多 2 条）；
2. Phase 1 (获批单发): 当实时发送开关开启时，取 ``APPROVED`` 任务先做非破坏性配额/时段预检（``check_wechat_reply_quota``）；
   若处于夜间窗口或滚动配额暂满则保持 ``APPROVED`` 等待下一周期，不误标 ``FAILED`` (SR-01)；通过后单次最多认领并发送 1 条；
3. Phase 2 (增量扫描): 按 ``wechat_comment_scan_state`` 水位选取最久未扫的已发布视频（每 Tick 最多 N 个），
   在只读会话锁与路由强拦截下捕获 ``comment_list`` 入库并更新扫描水位 (SR-04)；
4. Phase 3 (无锁生成与派发): 释放浏览器锁后，对尚无任何任务记录的新观众评论（``include_failed_tasks=False``，防重入刷屏 SR-03）
   调用沙箱 ``AgySecondaryReplyProvider`` 生成双语草稿、落库 ``PENDING_REVIEW`` 并通过 ``TelegramApprovalTransport`` 推送审批卡片。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-17 | Antigravity | 初始创建：实现 M3.5 四阶段有界 Tick 调度器与防重入/非破坏性配额预检 (SR-01~SR-04) |
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_agy_provider import (
    AgySecondaryReplyProvider,
    build_verified_video_context,
)
from video_processing.interaction.secondary_reply_approval import (
    build_default_approval_transport,
    dispatch_approval_request,
)
from video_processing.interaction.secondary_reply_contract import (
    AudienceCommentRecord,
    SecondaryReplyIntent,
    parse_wechat_comment_list_payload,
)
from video_processing.interaction.secondary_reply_ops import (
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_STOP_FILE,
    configured_approver_target,
)
from video_processing.interaction.secondary_reply_orchestrator import (
    SecondaryReplyOrchestrator,
)
from video_processing.interaction.secondary_reply_service import (
    SecondaryReplyCensor,
    SecondaryReplyService,
)

logger = logging.getLogger(__name__)


def _utc_now(clock: Optional[Callable[[], datetime.datetime]] = None) -> datetime.datetime:
    now = clock() if clock else datetime.datetime.now(datetime.timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=datetime.timezone.utc)


def run_secondary_reply_tick(
    db: PipelineDB,
    *,
    platform: Any,
    service: Optional[SecondaryReplyService] = None,
    approval_transport: Optional[Any] = None,
    account_key: Optional[str] = None,
    finder_id: Optional[str] = None,
    admin_ids_override: Optional[str] = None,
    evidence_dir: Optional[Path] = None,
    clock: Optional[Callable[[], datetime.datetime]] = None,
    allow_fixture_drafts: Optional[bool] = None,
    max_reconcile_per_tick: int = 2,
    max_submit_per_tick: int = 1,
    scan_posts_per_tick: Optional[int] = None,
    max_drafts_per_tick: Optional[int] = None,
    max_reconcile_attempts: Optional[int] = None,
) -> Dict[str, Any]:
    """执行一次有界二级回复 Tick 周期。"""
    if not settings.enable_wechat_secondary_reply:
        return {
            "ok": False,
            "status": "SKIPPED_FEATURE_DISABLED",
            "reason": "FLAG_enable_wechat_secondary_reply_OFF",
        }
    if DEFAULT_STOP_FILE.exists():
        return {
            "ok": False,
            "status": "SKIPPED_STOP_FILE_PRESENT",
            "reason": "STOP_FILE_PRESENT",
            "stop_file": str(DEFAULT_STOP_FILE),
        }

    acct = (account_key or settings.wechat_reply_account_key or "").strip()
    finder = (finder_id or settings.wechat_reply_author_finder_id or "").strip()
    if not acct:
        return {"ok": False, "status": "CONFIG_MISSING", "reason": "ACCOUNT_KEY_NOT_CONFIGURED"}
    if not finder:
        return {"ok": False, "status": "CONFIG_MISSING", "reason": "AUTHOR_FINDER_ID_NOT_CONFIGURED"}

    scan_limit = int(
        scan_posts_per_tick
        if scan_posts_per_tick is not None
        else getattr(settings, "wechat_reply_scan_posts_per_tick", 3)
    )
    draft_limit = int(
        max_drafts_per_tick
        if max_drafts_per_tick is not None
        else getattr(settings, "wechat_reply_max_drafts_per_tick", 5)
    )
    reconcile_cap = int(
        max_reconcile_attempts
        if max_reconcile_attempts is not None
        else getattr(settings, "wechat_reply_max_reconcile_attempts", 5)
    )

    transport = approval_transport if approval_transport is not None else build_default_approval_transport(db)
    svc = service or SecondaryReplyService(
        provider=AgySecondaryReplyProvider(),
        censor=SecondaryReplyCensor(),
    )
    ident, ident_err = configured_approver_target(admin_ids_override=admin_ids_override)
    approver_id = ident["approver_id"] if ident else ""
    approver_chat_id = ident["chat_id"] if ident else ""

    if allow_fixture_drafts is None:
        allow_fixture_drafts = bool(getattr(transport, "allow_fixture_drafts", False))

    orch = SecondaryReplyOrchestrator(
        db=db,
        service=svc,
        platform=platform,
        approval_transport=transport,
        account_key=acct,
        approver_id=approver_id,
        approver_chat_id=approver_chat_id,
        admin_ids_override=admin_ids_override,
        clock=clock,
        allow_fixture_drafts=allow_fixture_drafts,
        evidence_dir=evidence_dir or DEFAULT_EVIDENCE_DIR,
    )

    now_dt = _utc_now(clock)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    report: Dict[str, Any] = {
        "ok": True,
        "status": "COMPLETED",
        "account_key": acct,
        "now_utc": now_str,
        "reconciled": [],
        "submitted": [],
        "submit_deferred": [],
        "scanned_posts": [],
        "drafted": [],
        "approver_configured": bool(ident),
        "approver_warning": ident_err,
    }

    # =========================================================================
    # Phase 0: 到期 UNCERTAIN 任务只读对账（优先恢复确定性状态，带指数退避）
    # =========================================================================
    due_uncertain = db.get_due_uncertain_secondary_reply_tasks(
        account_key=acct,
        max_attempts=reconcile_cap,
        now_utc=now_dt,
        limit=max(0, int(max_reconcile_per_tick)),
    )
    for utask in due_uncertain:
        tid = int(utask["id"])
        out = orch.reconcile(tid)
        report["reconciled"].append(
            {"task_id": tid, "outcome": out.status, "detail": out.detail}
        )

    # =========================================================================
    # Phase 1: 已获人工批准 (APPROVED) 任务单条发送（非破坏性配额/时段预检 SR-01）
    # =========================================================================
    if settings.enable_wechat_secondary_reply_live_submission:
        approved_tasks = db.get_approved_secondary_reply_tasks(
            account_key=acct,
            now_utc=now_dt,
            limit=max(1, int(max_submit_per_tick)),
        )
        sent_count = 0
        for atask in approved_tasks:
            if sent_count >= max(0, int(max_submit_per_tick)):
                break
            tid = int(atask["id"])
            post_id = str(atask["platform_post_id"])
            check_now_dt = _utc_now(clock)
            quota_ok, quota_reason = db.check_wechat_reply_quota(
                post_id, now_utc=check_now_dt
            )
            if not quota_ok:
                if "Single video secondary reply limit reached" in quota_reason:
                    db.record_secondary_reply_skipped(
                        tid, reason="VIDEO_SECONDARY_REPLY_QUOTA_EXCEEDED"
                    )
                    report["submit_deferred"].append(
                        {"task_id": tid, "action": "SKIPPED", "reason": quota_reason}
                    )
                else:
                    # 夜间窗口、滚动 60m 配额或 15s 最小间隔未到：保持 APPROVED 等待下一 Tick
                    report["submit_deferred"].append(
                        {"task_id": tid, "action": "DEFERRED_KEEP_APPROVED", "reason": quota_reason}
                    )
                continue

            sub_out = orch.submit(tid)
            report["submitted"].append(
                {
                    "task_id": tid,
                    "outcome": sub_out.status,
                    "detail": sub_out.detail,
                    "extra": sub_out.extra,
                }
            )
            sent_count += 1
    else:
        report["submit_skipped_reason"] = "FLAG_enable_wechat_secondary_reply_live_submission_OFF"

    # =========================================================================
    # Phase 2: 按水位表增量扫描已发布作品评论区 (SR-04)
    # =========================================================================
    discover_fn = getattr(platform, "discover_comments", None)
    due_posts = (
        db.get_due_comment_scan_posts(account_key=acct, limit=max(1, scan_limit), now_utc=now_dt)
        if scan_limit > 0
        else []
    )
    posts_by_id: Dict[str, Dict[str, Any]] = {
        str(p["platform_post_id"]): p for p in due_posts if p.get("platform_post_id")
    }

    if callable(discover_fn) and scan_limit > 0:
        for post_row in due_posts:
            post_id = str(post_row["platform_post_id"])
            vtitle = str(post_row.get("video_title") or post_row.get("zh_title") or post_row.get("title") or "")
            vdesc = str(post_row.get("published_description") or post_row.get("description") or "")
            pub_at = str(post_row.get("publication_created_at") or post_row.get("published_at") or "")
            scan_now_dt = _utc_now(clock)
            disc = discover_fn(post_id=post_id, video_title=vtitle, published_description=vdesc)
            if not isinstance(disc, dict) or not disc.get("ok") or not isinstance(disc.get("payload"), dict):
                err_reason = str((disc or {}).get("reason") or "DISCOVER_FAILED")
                db.record_comment_scan_state(
                    account_key=acct,
                    platform_post_id=post_id,
                    top_level_status="INCOMPLETE",
                    observed_comment_count=0,
                    complete=False,
                    last_error=err_reason,
                    published_at_utc=pub_at,
                    now_utc=scan_now_dt,
                )
                report["scanned_posts"].append(
                    {"post_id": post_id, "ok": False, "reason": err_reason}
                )
                if err_reason == "LOGIN_REQUIRED":
                    report["ok"] = False
                    report["status"] = "LOGIN_REQUIRED"
                    return report
                continue

            try:
                parsed = parse_wechat_comment_list_payload(
                    disc["payload"],
                    platform_post_id=post_id,
                    author_username=finder,
                    strict_schema=False,
                )
            except Exception as exc:
                err_msg = f"PARSE_ERROR: {exc}"
                db.record_comment_scan_state(
                    account_key=acct,
                    platform_post_id=post_id,
                    top_level_status="INVALID",
                    observed_comment_count=0,
                    complete=False,
                    last_error=err_msg,
                    published_at_utc=pub_at,
                    now_utc=scan_now_dt,
                )
                report["scanned_posts"].append(
                    {"post_id": post_id, "ok": False, "reason": err_msg}
                )
                continue

            db.save_discovered_audience_comments(
                post_id,
                [
                    {
                        "comment_id": c.comment_id,
                        "nickname": c.nickname,
                        "content": c.content,
                        "createtime": c.createtime,
                        "like_count": c.like_count,
                        "is_author": c.is_author,
                        "has_author_reply": c.has_author_reply,
                    }
                    for c in parsed.comments
                ],
                account_key=acct,
            )
            is_complete = parsed.top_level_status.value == "COMPLETE"
            db.record_comment_scan_state(
                account_key=acct,
                platform_post_id=post_id,
                top_level_status=parsed.top_level_status.value,
                observed_comment_count=len(parsed.comments),
                complete=is_complete,
                last_error=None,
                published_at_utc=pub_at,
                now_utc=scan_now_dt,
            )
            report["scanned_posts"].append(
                {
                    "post_id": post_id,
                    "ok": True,
                    "top_level_status": parsed.top_level_status.value,
                    "discovered_count": len(parsed.comments),
                }
            )

    # =========================================================================
    # Phase 3: 无浏览器锁状态下生成新草稿并推送 Telegram 审批卡片 (SR-03)
    # =========================================================================
    if draft_limit > 0:
        unprocessed = db.get_unprocessed_audience_comments(
            platform_post_id=None,
            account_key=acct,
            exclude_existing_tasks=True,
            include_failed_tasks=False,
        )
        for row in unprocessed[:draft_limit]:
            post_id = str(row["platform_post_id"])
            cid = str(row["comment_id"])
            content_norm = unicodedata.normalize("NFC", str(row.get("content") or ""))
            content_hash = str(row.get("content_hash") or hashlib.sha256(content_norm.encode("utf-8")).hexdigest())
            record = AudienceCommentRecord(
                platform_post_id=post_id,
                comment_id=cid,
                nickname=str(row.get("nickname") or ""),
                content=content_norm,
                content_hash=content_hash,
                createtime=str(row.get("createtime") or ""),
                like_count=int(row.get("like_count") or 0),
                is_author=bool(row.get("is_author")),
                has_author_reply=bool(row.get("has_author_reply")),
            )

            post_meta = posts_by_id.get(post_id) or db.get_commentable_wechat_post_by_platform_id(post_id)
            video_ctx = build_verified_video_context(post_meta)

            try:
                draft = svc.generate_draft(record, video_context=video_ctx)
            except Exception as exc:
                logger.warning("[SecondaryReplyRunner] 评论 %s 草稿生成或安全门禁未通过，落库 FAILED: %s", cid, exc)
                fail_tid = db.create_or_update_secondary_reply_task(
                    platform_post_id=post_id,
                    comment_id=cid,
                    intent=SecondaryReplyIntent.MANUAL.value,
                    style="PRAGMATIC",
                    reason_code=f"GENERATION_FAILED: {type(exc).__name__}",
                    provider=getattr(svc.provider, "model", "agy"),
                    status="FAILED",
                    account_key=acct,
                )
                db.record_secondary_reply_failed(fail_tid, error_message=str(exc)[:300])
                report["drafted"].append(
                    {"task_id": fail_tid, "comment_id": cid, "status": "FAILED", "reason": str(exc)}
                )
                continue

            if draft.intent != SecondaryReplyIntent.REPLY:
                non_reply_status = "MANUAL" if draft.intent == SecondaryReplyIntent.MANUAL else "SKIPPED"
                tid = db.create_or_update_secondary_reply_task(
                    platform_post_id=post_id,
                    comment_id=cid,
                    intent=draft.intent.value,
                    style=draft.style.value,
                    reason_code=draft.reason_code,
                    provider=draft.provider,
                    status=non_reply_status,
                    account_key=acct,
                )
                report["drafted"].append(
                    {"task_id": tid, "comment_id": cid, "status": non_reply_status, "reason": draft.reason_code}
                )
                continue

            tid = db.create_or_update_secondary_reply_task(
                platform_post_id=post_id,
                comment_id=cid,
                intent=draft.intent.value,
                style=draft.style.value,
                chinese_reply=draft.chinese_reply,
                english_reply=draft.english_reply,
                formatted_reply=draft.formatted_reply,
                reason_code=draft.reason_code,
                evidence_refs=draft.evidence_refs,
                provider=draft.provider,
                status="PENDING_REVIEW",
                account_key=acct,
            )
            dispatched = False
            dispatch_msg = "APPROVER_OR_TRANSPORT_NOT_READY"
            if ident and transport is not None:
                dispatched, dispatch_msg = dispatch_approval_request(
                    db=db,
                    task_id=tid,
                    transport=transport,
                    expiry_hours=24,
                    approver_telegram_id=approver_id,
                    approver_chat_id=approver_chat_id,
                    admin_ids_override=admin_ids_override,
                    now_utc=_utc_now(clock),
                )
            report["drafted"].append(
                {
                    "task_id": tid,
                    "comment_id": cid,
                    "status": "PENDING_REVIEW",
                    "approval_dispatched": dispatched,
                    "dispatch_detail": dispatch_msg,
                }
            )

    return report

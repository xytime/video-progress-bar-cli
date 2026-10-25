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
| scan-deadline-v1 | 2026-10-25 | Codex | 正常扫描暂缓记录结构化释放时间，成功/失败读取仍沿用原水位和单轮计费。 |
| reply-coverage-v2 | 2026-10-25 | Codex | 原生活动唯一绑定后供下一批优先选择，保存顶层续扫水位与候选来源。 |
| reply-recovery-v1 | 2026-10-25 | Codex | 维护暂停返回有界等待并保留已完成回执，不误标草稿失败。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| operations-v1 | 2026-10-24 | Codex | 分用途滚动预算与安全有界重试接入，保留既有提交事实与内容保护。 |
| interaction-recovery-v1 | 2026-10-23 | Codex | 所有阶段限定显式作品，零上限不执行，未知作者状态保留批准。 |
| 1.3.0 | 2026-10-18 | Antigravity | 支持携带双语参考草稿的 MANUAL 意图落库 PENDING_REVIEW 并推送 Telegram 人工审批卡片 |
| 1.2.0 | 2026-10-18 | Antigravity | 接入 secondary_reply_policy 热加载、hybrid_auto 自动批准入队与发送成功后 Telegram 事后通告 |
| 1.1.0 | 2026-10-17 | Antigravity | 新增 resolve_published_copy_text 解析落盘文案文件用于评论页场景 ID 绑定与草稿背景摘要 |
| 1.0.0 | 2026-10-17 | Antigravity | 初始创建：实现 M3.5 四阶段有界 Tick 调度器与防重入/非破坏性配额预检 (SR-01~SR-04) |
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import unicodedata
from pathlib import Path
from contextlib import nullcontext
from typing import Any, Callable, Dict, List, Optional

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_agy_provider import (
    AgySecondaryReplyProvider,
    build_verified_video_context,
)
from video_processing.interaction.secondary_reply_approval import (
    auto_approve_and_bind_task,
    build_default_approval_transport,
    dispatch_approval_request,
    dispatch_post_reply_notification,
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
from video_processing.utils.secondary_reply_policy import sync_secondary_reply_settings

logger = logging.getLogger(__name__)


def _utc_now(clock: Optional[Callable[[], datetime.datetime]] = None) -> datetime.datetime:
    now = clock() if clock else datetime.datetime.now(datetime.timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=datetime.timezone.utc)


def resolve_published_copy_text(post_row: Optional[Dict[str, Any]]) -> str:
    """从作品记录或落盘文案文件读取完整已发布文案，用于评论页场景 ID 绑定与背景摘要。"""
    if not isinstance(post_row, dict):
        return ""
    direct = str(post_row.get("published_description") or post_row.get("description") or "").strip()
    if direct:
        return " ".join(direct.split())
    copy_path = str(post_row.get("copy_path") or "").strip()
    target_path: Optional[Path] = None
    if copy_path and Path(copy_path).is_file():
        target_path = Path(copy_path)
    else:
        yid = str(post_row.get("youtube_id") or "").strip()
        if yid:
            slice_idx = int(post_row.get("slice_index") or 0)
            prefix = f"{yid}_s{slice_idx}" if slice_idx else yid
            cand = Path(__file__).resolve().parents[3] / "output" / f"{prefix}_copy.txt"
            if cand.is_file():
                target_path = cand
    if target_path is not None:
        try:
            return " ".join(target_path.read_text(encoding="utf-8").split())
        except Exception:
            return ""
    return ""


def run_secondary_reply_tick(db: PipelineDB, **kwargs) -> Dict[str, Any]:
    """维护暂停是可恢复等待；保留暂停前已经完成的提交与扫描回执。"""
    from ..core.maintenance import gate, MaintenanceDenied
    progress: Dict[str, Any] = {}
    try:
        gate().require_running()
        return _run_secondary_reply_tick(db, _progress=progress, **kwargs)
    except MaintenanceDenied as exc:
        progress.update(ok=True, status='DEFERRED_MAINTENANCE', reason=exc.code)
        return progress


def _run_secondary_reply_tick(
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
    platform_post_id: Optional[str] = None,
    video_title_hint: str = "",
    _progress: Optional[dict] = None,
) -> Dict[str, Any]:
    """执行一次有界二级回复 Tick 周期。"""
    sync_secondary_reply_settings()
    from ..utils.wechat_operations_policy import load_policy
    operations_policy = load_policy()
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
    if operations_policy is not None:
        configured_scan_limit = operations_policy["operations"]["comment_scan"]["max_videos_per_run"]
        scan_limit = min(max(0, scan_limit), configured_scan_limit) if scan_posts_per_tick is not None else configured_scan_limit
        max_reconcile_per_tick = 0  # 旧 UNCERTAIN 不因新配额恢复自动回查。
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
    approval_mode = str(getattr(settings, "wechat_reply_approval_mode", "manual") or "manual")

    report: Dict[str, Any] = _progress if _progress is not None else {}
    report.update({
        "ok": True,
        "status": "COMPLETED",
        "account_key": acct,
        "now_utc": now_str,
        "approval_mode": approval_mode,
        "reconciled": [],
        "submitted": [],
        "submit_deferred": [],
        "scanned_posts": [],
        "drafted": [],
        "approver_configured": bool(ident),
        "approver_warning": ident_err,
    })

    # =========================================================================
    # Phase 0: 到期 UNCERTAIN 任务只读对账（优先恢复确定性状态，带指数退避）
    # =========================================================================
    due_uncertain = db.get_due_uncertain_secondary_reply_tasks(
        account_key=acct,
        platform_post_id=platform_post_id,
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
    # Phase 1: 已获批准 (APPROVED) 任务单条发送（非破坏性配额/时段预检 SR-01）
    # =========================================================================
    if settings.enable_wechat_secondary_reply_live_submission:
        approved_tasks = db.get_approved_secondary_reply_tasks(
            account_key=acct,
            platform_post_id=platform_post_id,
            now_utc=now_dt,
            limit=max(0, int(max_submit_per_tick)),
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
                    # 提交窗口外、滚动 60m 配额或最小间隔未到：保持 APPROVED 等待下一 Tick
                    report["submit_deferred"].append(
                        {"task_id": tid, "action": "DEFERRED_KEEP_APPROVED", "reason": quota_reason}
                    )
                continue

            sub_out = orch.submit(tid)
            if sub_out.status in ("DEFERRED_SESSION_BUSY", "DEFERRED_AUTHOR_STATE_UNKNOWN"):
                report["submit_deferred"].append(
                    {"task_id": tid, "action": "DEFERRED_KEEP_APPROVED", "reason": sub_out.detail}
                )
                break
            notified = False
            if sub_out.status == "VERIFIED" and approval_mode == "hybrid_auto" and ident and transport is not None:
                notified, _ = dispatch_post_reply_notification(
                    db=db,
                    task_id=tid,
                    transport=transport,
                    chat_id=approver_chat_id,
                    reply_id=sub_out.detail,
                )
            report["submitted"].append(
                {
                    "task_id": tid,
                    "outcome": sub_out.status,
                    "detail": sub_out.detail,
                    "extra": sub_out.extra,
                    "post_reply_notified": notified,
                }
            )
            sent_count += 1
    else:
        report["submit_skipped_reason"] = "FLAG_enable_wechat_secondary_reply_live_submission_OFF"

    # =========================================================================
    # Phase 2: 按水位表增量扫描已发布作品评论区 (SR-04)
    # =========================================================================
    discover_fn = getattr(platform, "discover_comments", None)
    if platform_post_id:
        explicit_row = db.get_commentable_wechat_post_by_platform_id(platform_post_id) or {
            "platform_post_id": platform_post_id,
            "title": video_title_hint,
            "zh_title": video_title_hint,
        }
        if video_title_hint and not explicit_row.get("video_title"):
            explicit_row["video_title"] = video_title_hint
        due_posts = [explicit_row] if scan_limit > 0 else []
    else:
        due_posts = (
            db.get_due_comment_scan_posts(account_key=acct, limit=max(1, scan_limit), now_utc=now_dt)
            if scan_limit > 0
            else []
        )
    posts_by_id: Dict[str, Dict[str, Any]] = {
        str(p["platform_post_id"]): p for p in due_posts if p.get("platform_post_id")
    }

    if callable(discover_fn) and scan_limit > 0 and due_posts:
        wake_store, pending_wake, wake_scope = None, None, None
        if not platform_post_id and getattr(getattr(platform, "adapter", None), "state_path", None):
            from .secondary_reply_scan_wake import store, scope_key
            wake_store, wake_scope = store(), scope_key(acct, finder)
            pending_wake = wake_store.read()
        try:
            with getattr(platform, "scan_scope", lambda _ids: nullcontext())([str(p["platform_post_id"]) for p in due_posts]):
                for post_row in due_posts:
                    post_id = str(post_row["platform_post_id"])
                    vtitle = str(
                        video_title_hint
                        or post_row.get("video_title")
                        or post_row.get("zh_title")
                        or post_row.get("title")
                        or ""
                    )
                    vdesc = resolve_published_copy_text(post_row)
                    if vdesc and not post_row.get("published_description"):
                        post_row["published_description"] = vdesc
                        if not post_row.get("description"):
                            post_row["description"] = vdesc
                    pub_at = str(post_row.get("publication_created_at") or post_row.get("published_at") or "")
                    scan_now_dt = _utc_now(clock)
                    paged_discover = getattr(platform, "discover_comment_pages", None)
                    if callable(paged_discover):
                        prior = db.get_comment_scan_state(acct, post_id) or {}
                        disc = paged_discover(post_id=post_id, video_title=vtitle,
                            published_description=vdesc, resume_cursor=prior.get("comment_cursor") or "")
                    else:
                        disc = discover_fn(post_id=post_id, video_title=vtitle, published_description=vdesc)
                    if not isinstance(disc, dict) or not disc.get("ok") or not isinstance(disc.get("payload"), dict):
                        err_reason = str((disc or {}).get("reason") or "DISCOVER_FAILED")
                        db.record_comment_scan_state(
                            account_key=acct,
                            platform_post_id=post_id,
                            top_level_status="INCOMPLETE",
                            observed_comment_count=0,
                            complete=False,
                            comment_cursor=(db.get_comment_scan_state(acct, post_id) or {}).get("comment_cursor") or "",
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
                            comment_cursor=(db.get_comment_scan_state(acct, post_id) or {}).get("comment_cursor") or "",
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
                                "source_page_cursor": (disc.get("comment_page_cursors") or {}).get(c.comment_id, ""),
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
                        comment_cursor=str(disc.get("comment_cursor") or ""),
                        last_error=str(disc.get("reason") or "") or None,
                        published_at_utc=pub_at,
                        now_utc=scan_now_dt,
                    )
                    report["scanned_posts"].append(
                        {
                            "post_id": post_id,
                            "ok": True,
                            "top_level_status": parsed.top_level_status.value,
                            "discovered_count": len(parsed.comments),
                            "candidate_origin": post_row.get("scan_candidate_origin", "explicit_target"),
                            "pages_observed": disc.get("pages_observed", 1),
                            "continuation_pending": not is_complete,
                            "scan_note": disc.get("reason"),
                        }
                    )

        except Exception as exc:
            from ..core.wechat_session_lock import WeChatSessionLockBusy
            if not isinstance(exc, WeChatSessionLockBusy):
                raise
            report["scan_deferred"] = str(exc)
            if wake_store is not None:
                from .secondary_reply_scan_wake import remember_scan_wait
                report["scan_wait"] = remember_scan_wait(exc, account=acct, finder=finder,
                                                        scan_limit=scan_limit, platform=platform)
        else:
            if wake_store is not None and pending_wake and pending_wake["scope"] == wake_scope:
                wake_store.complete(wake_scope, pending_wake["token"])

    observations_fn = getattr(platform, "comment_activity_observations", None)
    if callable(observations_fn) and report["scanned_posts"]:
        observations = observations_fn()
        if observations:
            known = db.get_due_comment_scan_posts(account_key=acct, limit=100000,
                                                  include_cooling=True, now_utc=now_dt)
            descriptions = {}
            for row in known:
                description = " ".join(resolve_published_copy_text(row).split())
                if len(description) >= 30:
                    descriptions.setdefault(description, []).append(str(row["platform_post_id"]))
            activity_audit = []
            for observed in observations:
                matches = descriptions.get(" ".join(str(observed.get("description") or "").split()), [])
                if len(matches) != 1:
                    activity_audit.append({"native_id": observed.get("native_id"),
                                           "binding": "UNKNOWN_OR_AMBIGUOUS"})
                    continue
                db.record_comment_activity(account_key=acct, platform_post_id=matches[0],
                    comment_count=observed["comment_count"], unread_count=observed["unread_count"],
                    scanned_complete=any(r.get("post_id") == matches[0] and r.get("top_level_status") == "COMPLETE"
                                         for r in report["scanned_posts"]))
                activity_audit.append({"post_id": matches[0], "native_id": observed["native_id"],
                    "binding": "UNIQUE_FULL_DESCRIPTION", "comment_count": observed["comment_count"],
                    "unread_count": observed["unread_count"]})
            report["activity_observations"] = activity_audit

    # =========================================================================
    # Phase 3: 无浏览器锁状态下生成新草稿并推送 Telegram 审批卡片 (SR-03)
    # =========================================================================
    if draft_limit > 0:
        unprocessed = db.get_unprocessed_audience_comments(
            platform_post_id=platform_post_id,
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
            if post_meta:
                post_meta = dict(post_meta)
                copy_desc = resolve_published_copy_text(post_meta)
                if copy_desc and not post_meta.get("description"):
                    post_meta["description"] = copy_desc
            if video_title_hint and (not post_meta or not post_meta.get("title")):
                post_meta = dict(post_meta or {}, title=video_title_hint, zh_title=video_title_hint)
            video_ctx = build_verified_video_context(post_meta)

            try:
                draft = svc.generate_draft(record, video_context=video_ctx)
            except Exception as exc:
                from ..core.maintenance import MaintenanceDenied
                if isinstance(exc, MaintenanceDenied):
                    raise
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

            has_suggested_draft = bool(draft.chinese_reply.strip() and draft.english_reply.strip())
            if draft.intent == SecondaryReplyIntent.SKIP or (
                draft.intent == SecondaryReplyIntent.MANUAL and not has_suggested_draft
            ):
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
            final_draft_status = "PENDING_REVIEW"
            if approval_mode == "hybrid_auto" and draft.intent == SecondaryReplyIntent.REPLY and ident:
                auto_ok, auto_msg = auto_approve_and_bind_task(
                    db=db,
                    task_id=tid,
                    approver_telegram_id=approver_id,
                    approver_chat_id=approver_chat_id,
                    admin_ids_override=admin_ids_override,
                    expected_account_key=acct,
                    allow_fixture_drafts=bool(allow_fixture_drafts),
                    expiry_hours=168,
                    now_utc=_utc_now(clock),
                )
                dispatched = auto_ok
                dispatch_msg = f"HYBRID_AUTO:{auto_msg}"
                if auto_ok:
                    final_draft_status = "APPROVED"
            elif ident and transport is not None:
                dispatched, dispatch_msg = dispatch_approval_request(
                    db=db,
                    task_id=tid,
                    transport=transport,
                    expiry_hours=168,
                    approver_telegram_id=approver_id,
                    approver_chat_id=approver_chat_id,
                    admin_ids_override=admin_ids_override,
                    now_utc=_utc_now(clock),
                )
            report["drafted"].append(
                {
                    "task_id": tid,
                    "comment_id": cid,
                    "status": final_draft_status,
                    "approval_dispatched": dispatched,
                    "dispatch_detail": dispatch_msg,
                }
            )

    return report

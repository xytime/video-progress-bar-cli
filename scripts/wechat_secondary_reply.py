#!/usr/bin/env python3
"""视频号二级回复 CLI 与自动化调度入口。

特性开关与提交闸门默认严格关闭；
dry-run 模式下数据库完全只读，不启动浏览器、不调用外部 API、零副作用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.7.0 | 2026-10-17 | Antigravity | 接入 M3.5 tick 定时周期子命令、默认 TelegramApprovalTransport、持久化证据目录与 DB 作品标题回填 (CR-01/CR-02/CR-04) |
| 1.6.0 | 2026-10-17 | Antigravity | 收回裸 SQL 为 PipelineDB.delete_secondary_reply_task；拆分 request-approval 与 approve-callback 审批入口 |
| 1.5.0 | 2026-10-17 | Codex | 完善 main() 返回码保护与 verify-platform / calibrate-dom 统一集成测试支持 (M3) |
| 1.4.0 | 2026-10-17 | Codex | 支持 verify-platform 传递 comment-text 原文校验与原生作者身份回传 (M2) |
| 1.3.0 | 2026-10-17 | Codex | 新增 verify-platform / calibrate-dom 只读平台校准与状态验证子命令 (R1) |
| 1.2.0 | 2026-10-12 | Antigravity | 接入严格 API 载荷解析器 (T01/T02/T03/T12) 与只读对账 (--reconcile) 审计支持 |
| 1.1.0 | 2026-10-12 | Codex | 新增 --demo 离线 4 路径重现验证套件（成功防重/守卫拦截/异常对账/墓碑持久） |
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现二级回复 CLI、dry-run、审批流与状态机调度 |
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_approval import (
    FakeApprovalTransport,
    build_default_approval_transport,
    dispatch_approval_request,
    handle_approval_callback,
)
from video_processing.interaction.secondary_reply_browser_adapter import (
    SecondaryReplyBrowserAdapter,
)
from video_processing.interaction.secondary_reply_contract import (
    AudienceCommentRecord,
    SecondaryReplyIntent,
    SecondaryReplyStyle,
    SecondaryReplySubmissionGuard,
    TopLevelPaginationStatus,
    SecondaryPaginationStatus,
    parse_wechat_comment_list_payload,
    validate_input_comment,
)
from video_processing.interaction.secondary_reply_service import (
    SecondaryReplyCensor,
    SecondaryReplyService,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("wechat_secondary_reply")


def run_dry_run_inspection(db: PipelineDB, platform_post_id: str) -> Dict[str, Any]:
    """只读检查待处理评论、草稿与配额状态，零写操作。"""
    comments = db.get_unprocessed_audience_comments(platform_post_id)
    quota_allowed, quota_reason = db.check_wechat_reply_quota(platform_post_id)
    return {
        "platform_post_id": platform_post_id,
        "unprocessed_count": len(comments),
        "comments": comments[:5],
        "quota_allowed": quota_allowed,
        "quota_reason": quota_reason,
        "mode": "DRY_RUN_READ_ONLY",
    }


def run_reconcile_inspection(db: PipelineDB, platform_post_id: Optional[str] = None) -> Dict[str, Any]:
    """对 UNCERTAIN 状态的二级回复任务进行只读对账审计，零写操作零副作用。"""
    tasks = db.get_uncertain_secondary_reply_tasks(platform_post_id)
    return {
        "platform_post_id": platform_post_id,
        "uncertain_count": len(tasks),
        "tasks": tasks,
        "mode": "RECONCILE_READ_ONLY",
        "recommendation": "对账模式仅执行只读回查与审计，绝不自动盲目重发出站请求",
    }


def run_offline_4path_demo() -> Dict[str, Any]:
    """离线 4 路径演示：四条路径全部经过同一编排服务与离线平台替身，不手工写状态。

    1. 成功与防重：fixture 采集 -> 草稿 -> fake 审批 -> 认领/终审/意图/守卫/回执/刷新回读 -> VERIFIED；二次运行零出站。
    2. 错目标：守卫在网络前拦截，零出站，意图保留墓碑。
    3. 重启对账：意图后崩溃，只读对账发现平台已有回复 -> VERIFIED；未发现 -> 保持 UNCERTAIN，不重发。
    4. 删除后墓碑：任务被物理删除，账本仍阻断再次发送。
    平台替身仅为离线模拟，真实平台字段/分页仍属未验证项。
    """
    import copy
    from datetime import datetime as _dt

    from video_processing.interaction.secondary_reply_fake_platform import FakeSecondaryReplyPlatform
    from video_processing.interaction.secondary_reply_orchestrator import SecondaryReplyOrchestrator

    logger.info("开始执行离线 4 路径演示（统一编排 + 平台替身）...")
    results: Dict[str, Any] = {}
    post_id = "export/synth_video_888"
    approver = "888999"
    def material_for(text: str) -> Dict[str, Any]:
        # 夹具材料：与评论有字面关联的合成片段（真实材料需上游审核提供）
        return {"title": "合成演示视频", "evidence": {"fixture_segment_1": f"【合成夹具材料，仅用于离线演示】{text}"}}

    with tempfile.TemporaryDirectory() as tmp_dir:
        db = PipelineDB(db_path=str(Path(tmp_dir) / "demo.db"))
        platform = FakeSecondaryReplyPlatform()
        transport = FakeApprovalTransport()
        # 固定时钟：上海 12:00，每次提交推进 60 秒，避开最小间隔与时段限制
        state = {"now": _dt(2026, 10, 12, 4, 0, 0, tzinfo=timezone.utc)}

        def clock():
            state["now"] += timedelta(seconds=60)
            return state["now"]

        orch = SecondaryReplyOrchestrator(
            db=db, service=SecondaryReplyService(censor=SecondaryReplyCensor()), platform=platform,
            approval_transport=transport, account_key="acct_demo", approver_id=approver,
            approver_chat_id=approver, admin_ids_override=approver, clock=clock,
            allow_fixture_drafts=True,  # 仅离线演示
        )

        with open(PROJECT_ROOT / "tests" / "fixtures" / "secondary_reply" / "sanitized_api_responses.json", "r", encoding="utf-8") as f:
            fixture_data = json.load(f)
        parse_res = parse_wechat_comment_list_payload(
            fixture_data["comment_list"], platform_post_id=post_id,
            author_username=platform.account_finder_id, strict_schema=True,
        )
        assert parse_res.top_level_status == TopLevelPaginationStatus.COMPLETE and parse_res.comments

        def approve(task_id: int) -> None:
            callback = transport.sent_messages[-1]["inline_keyboard"][0][0]["callback_data"]
            ok, msg = orch.approve_via_callback(callback, user_id=approver, chat_id=approver)
            assert ok, msg

        # ---- 路径一：成功与防重 ----
        base = parse_res.comments[0]
        (task_1,) = orch.ingest_and_draft(post_id=post_id, comments=[base], video_context=material_for(base.content))
        approve(task_1)
        out1 = orch.submit(task_1)
        assert out1.status == "VERIFIED", out1
        sent_after_first = len(platform.outbound_requests)
        out1b = orch.submit(task_1)  # 二次运行
        dup_id = db.create_or_update_secondary_reply_task(
            platform_post_id=post_id, comment_id=base.comment_id, intent="REPLY", style="MACRO",
            chinese_reply="尝试再次回复", provider="rule_engine", status="PENDING_REVIEW", account_key="acct_demo",
        )
        task_1_final = db.get_secondary_reply_task(task_1)
        results["path_1_success_and_idempotency"] = {
            "status": "PASSED" if (
                task_1_final["status"] == "VERIFIED" and out1b.status == "NOT_CLAIMABLE"
                and dup_id == task_1 and len(platform.outbound_requests) == sent_after_first == 1
            ) else "FAILED",
            "first_run": out1.status, "second_run": out1b.status,
            "outbound_requests_total": len(platform.outbound_requests),
            "platform_reply_comment_id": task_1_final["platform_reply_comment_id"],
        }

        def extra_comment(cid: str, text: str) -> AudienceCommentRecord:
            return AudienceCommentRecord(
                platform_post_id=post_id, comment_id=cid, nickname="合成观众", content=text,
                content_hash="demo", createtime="1791779000",
            )

        # ---- 路径二：错目标在网络前拦截 ----
        platform.mode = "wrong-root"
        (task_2,) = orch.ingest_and_draft(post_id=post_id, comments=[extra_comment("demo_cmt_2", "为什么会出现这种情况？")], video_context=material_for("为什么会出现这种情况？"))
        approve(task_2)
        before = len(platform.outbound_requests)
        out2 = orch.submit(task_2)
        results["path_2_wrong_target_blocked_before_network"] = {
            "status": "PASSED" if out2.status == "BLOCKED_BY_GUARD" and len(platform.outbound_requests) == before else "FAILED",
            "outcome": out2.status, "detail": out2.detail,
            "new_outbound_requests": len(platform.outbound_requests) - before,
        }

        # ---- 路径三：意图后崩溃，重启只读对账 ----
        platform.mode = "crash-after-intent"
        (task_3,) = orch.ingest_and_draft(post_id=post_id, comments=[extra_comment("demo_cmt_3", "为什么会出现这种情况？")], video_context=material_for("为什么会出现这种情况？"))
        approve(task_3)
        crashed = orch.submit(task_3)
        # “重启”：新的编排实例/新的 DB 连接仅做只读对账
        db_after_restart = PipelineDB(db_path=str(Path(tmp_dir) / "demo.db"))
        queue = [t["id"] for t in db_after_restart.get_uncertain_secondary_reply_tasks(post_id)]
        platform.mode = "success"
        before = len(platform.outbound_requests)
        rec_not_seen = orch.reconcile(task_3)  # 平台上没有该回复
        platform._store(post_id, "demo_cmt_3", db.get_secondary_reply_task(task_3)["formatted_reply"], platform.account_finder_id, "late_reply_1")
        rec_found = orch.reconcile(task_3)  # 延迟出现
        results["path_3_restart_reconcile_only"] = {
            "status": "PASSED" if (
                crashed.status == "UNCERTAIN" and task_3 in queue
                and rec_not_seen.status == "UNCERTAIN" and rec_found.status == "VERIFIED"
                and len(platform.outbound_requests) == before
            ) else "FAILED",
            "crash_outcome": crashed.status, "in_reconcile_queue": task_3 in queue,
            "reconcile_not_observed": rec_not_seen.status, "reconcile_found": rec_found.status,
            "outbound_during_reconcile": len(platform.outbound_requests) - before,
        }

        # ---- 路径四：任务删除后墓碑仍阻断 ----
        db.delete_secondary_reply_task(task_1)
        tombstone = db.check_secondary_reply_idempotency(post_id, base.comment_id, account_key="acct_demo")
        # 绕过采集（评论已 PROCESSED）直接重建同目标任务，并走真实审批回调，最后仍应被账本拦截
        task_4 = db.create_or_update_secondary_reply_task(
            platform_post_id=post_id, comment_id=base.comment_id, intent="REPLY", style="MACRO",
            chinese_reply="重新创建的任务。", english_reply="Recreated task.",
            formatted_reply="重新创建的任务。\nRecreated task.", evidence_refs=["fixture_segment_1"],
            provider="rule_engine", status="PENDING_REVIEW", account_key="acct_demo",
        )
        dispatch_approval_request(
            db=db, task_id=task_4, transport=transport, approver_telegram_id=approver,
            approver_chat_id=approver, admin_ids_override=approver,
        )
        approve(task_4)
        # 模拟页面读不到已发回复（折叠/延迟），此时只能靠独立账本拦截
        platform.server_replies.pop((post_id, base.comment_id), None)
        before = len(platform.outbound_requests)
        out4 = orch.submit(task_4)
        blocked = (
            out4.status == "REJECTED_BEFORE_INTENT" and "IDEMPOTENCY_CONFLICT" in out4.detail
            and len(platform.outbound_requests) == before
        )
        results["path_4_tombstone_survives_deletion"] = {
            "status": "PASSED" if (tombstone and tombstone["status"] == "VERIFIED" and blocked) else "FAILED",
            "tombstone_status": tombstone["status"] if tombstone else None, "resend_blocked": blocked,
            "outcome": out4.status, "detail": out4.detail,
        }

    results["all_passed"] = all(v["status"] == "PASSED" for v in results.values() if isinstance(v, dict))
    logger.info("离线 4 路径演示结束: all_passed=%s", results["all_passed"])
    return results


# 与 PipelineDB 默认路径一致；测试可替换
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "output" / "pipeline.db"


def _read_only_refusal(db_path):
    """只读检视的前置检查：库不存在或有未检查点的 WAL 时拒绝（immutable 读取活动 WAL 库不安全）。"""
    if db_path is None or not db_path.exists():
        return "DB_NOT_FOUND: 只读模式不会创建数据库"
    wal = Path(str(db_path) + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        return "ACTIVE_WAL: 数据库存在未检查点的 WAL，拒绝以 immutable 方式读取"
    return None


SUBCOMMANDS = {
    "import-draft",
    "preflight",
    "request-approval",
    "approve-callback",
    "approve",
    "submit",
    "reconcile-platform",
    "status",
    "stop",
    "resume",
    "verify-platform",
    "calibrate-dom",
    "tick",
}

_UNSET_TRANSPORT = object()


def _build_real_platform(args, db: Optional[PipelineDB] = None):
    """真实浏览器端口：账号标识来自配置；缺失时拒绝。"""
    from video_processing.interaction import secondary_reply_ops as ops
    from video_processing.interaction.secondary_reply_browser_platform import BrowserSecondaryReplyPlatform

    finder = (settings.wechat_reply_author_finder_id or "").strip()
    if not finder:
        raise SystemExit("AUTHOR_FINDER_ID_NOT_CONFIGURED: 请配置 wechat_reply_author_finder_id")
    adapter = SecondaryReplyBrowserAdapter(headless=not getattr(args, "headed", False))
    cli_title = getattr(args, "video_title", "") or ""
    evidence_dir = getattr(args, "evidence_dir", None) or ops.DEFAULT_EVIDENCE_DIR

    def _resolve_hints(post_id: str):
        if cli_title:
            return cli_title, ""
        if db is not None and post_id:
            try:
                post_row = db.get_commentable_wechat_post_by_platform_id(post_id)
                if isinstance(post_row, dict):
                    return (
                        str(post_row.get("video_title") or post_row.get("zh_title") or post_row.get("title") or ""),
                        str(post_row.get("published_description") or post_row.get("description") or ""),
                    )
            except Exception:
                pass
        return "", ""

    return BrowserSecondaryReplyPlatform(
        adapter,
        account_finder_id=finder,
        post_hints=_resolve_hints,
        evidence_dir=evidence_dir,
        lookup_max_attempts=2,
        lookup_retry_delay_seconds=2.0,
    )


def ops_main(argv: List[str], platform_factory=None, approval_transport=_UNSET_TRANSPORT) -> int:
    """M3/M3.5 操作入口：预检/导入/发起审批/审批回调/提交/平台对账/状态/停用/平台验证/定时Tick。所有发送经统一编排。"""
    from video_processing.interaction import secondary_reply_ops as ops
    from video_processing.interaction.secondary_reply_runner import run_secondary_reply_tick

    parser = argparse.ArgumentParser(prog="wechat_secondary_reply")
    parser.add_argument("command", choices=sorted(SUBCOMMANDS))
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="数据库路径（测试可指向临时库）")
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--post-id")
    parser.add_argument("--comment-id")
    parser.add_argument("--comment-text", help="导入时：该一级评论的原文（作为审批绑定的源评论快照）")
    parser.add_argument("--zh")
    parser.add_argument("--en")
    parser.add_argument("--style", default="CASUAL_LIGHT", choices=[s.value for s in SecondaryReplyStyle])
    parser.add_argument("--confirm-reply-sha12", help="request-approval：回填预检输出 reply_sha256 前 12 位")
    parser.add_argument("--callback-data", help="approve-callback：Telegram 回调载荷 rep:<action>:<task_id>:<token>")
    parser.add_argument("--approver-user-id", help="approve-callback：触发回调的审批人 Telegram ID")
    parser.add_argument("--approver-chat-id", help="approve-callback：触发回调的私聊会话 ID")
    parser.add_argument("--ttl-minutes", type=int, default=60)
    parser.add_argument("--video-title", default="", help="仅用于页面卡片导航提示；不作为作品绑定依据")
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--confirm-readonly-platform-access", action="store_true",
                        help="reconcile-platform：明确确认本次将只读访问真实平台")
    parser.add_argument("--max-reconcile", type=int, default=2, help="tick：单次最多对账 UNCERTAIN 条数")
    parser.add_argument("--max-submit", type=int, default=1, help="tick：单次最多发送 APPROVED 条数")
    parser.add_argument("--scan-posts", type=int, default=None, help="tick：单次最多扫描作品数")
    parser.add_argument("--max-drafts", type=int, default=None, help="tick：单次最多生成草稿数")
    args = parser.parse_args(argv)

    if args.command == "stop":
        print(json.dumps(ops.stop(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "resume":
        print(json.dumps(ops.resume(), ensure_ascii=False, indent=2))
        return 0

    account_key = (settings.wechat_reply_account_key or "").strip()
    finder = (settings.wechat_reply_author_finder_id or "").strip()
    if not account_key:
        print(json.dumps({"ok": False, "reason": "ACCOUNT_KEY_NOT_CONFIGURED"}, ensure_ascii=False))
        return 2

    db = None
    if not args.db_path.exists():
        if args.command in ("verify-platform", "calibrate-dom"):
            db = None
        elif args.command == "import-draft":
            db = PipelineDB(db_path=str(args.db_path), read_only=False)
        else:
            print(json.dumps({"ok": False, "reason": "DB_NOT_FOUND"}, ensure_ascii=False))
            return 2
    else:
        read_only = args.command in {"preflight", "status", "verify-platform", "calibrate-dom"}
        if read_only:
            refusal = _read_only_refusal(args.db_path)
            if refusal:
                print(json.dumps({"ok": False, "reason": refusal}, ensure_ascii=False))
                return 2
        db = PipelineDB(db_path=str(args.db_path), read_only=read_only)

    def need(*names):
        missing = [n for n in names if getattr(args, n.replace("-", "_")) in (None, "")]
        if missing:
            print(json.dumps({"ok": False, "reason": "MISSING_ARGS", "args": missing}, ensure_ascii=False))
            raise SystemExit(2)

    def show(res) -> int:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0 if res.get("ok", True) else 1

    factory = platform_factory or (lambda a: _build_real_platform(a, db=db))
    resolved_transport = (
        build_default_approval_transport(db)
        if approval_transport is _UNSET_TRANSPORT
        else approval_transport
    )

    if args.command == "status":
        return show(ops.status_summary(db))
    if args.command == "tick":
        if not settings.enable_wechat_secondary_reply:
            return show({
                "ok": False,
                "status": "SKIPPED_FEATURE_DISABLED",
                "reason": "FLAG_enable_wechat_secondary_reply_OFF",
            })
        if not finder:
            return show({"ok": False, "reason": "AUTHOR_FINDER_ID_NOT_CONFIGURED"})
        return show(run_secondary_reply_tick(
            db,
            platform=factory(args),
            approval_transport=resolved_transport,
            account_key=account_key,
            finder_id=finder,
            evidence_dir=args.evidence_dir or ops.DEFAULT_EVIDENCE_DIR,
            max_reconcile_per_tick=args.max_reconcile,
            max_submit_per_tick=args.max_submit,
            scan_posts_per_tick=args.scan_posts,
            max_drafts_per_tick=args.max_drafts,
            platform_post_id=args.post_id,
            video_title_hint=args.video_title or "",
        ))
    if args.command == "import-draft":
        need("post-id", "comment-id", "comment-text", "zh", "en")
        return show(ops.import_manual_draft(
            db, account_key=account_key, post_id=args.post_id, comment_id=args.comment_id,
            comment_text=args.comment_text, zh=args.zh, en=args.en, style=args.style,
        ))
    if args.command == "approve-callback":
        need("callback-data", "approver-user-id", "approver-chat-id")
        return show(ops.approve_callback(
            db,
            callback_data=args.callback_data,
            user_id=args.approver_user_id,
            chat_id=args.approver_chat_id,
            account_key=account_key,
        ))
    if args.command in ("verify-platform", "calibrate-dom"):
        if not finder:
            return show({"ok": False, "reason": "AUTHOR_FINDER_ID_NOT_CONFIGURED"})
        if not account_key:
            return show({"ok": False, "reason": "ACCOUNT_KEY_NOT_CONFIGURED"})

        target_post = args.post_id
        target_comment = args.comment_id
        target_title = args.video_title or ""
        target_text = args.comment_text or ""
        if (not target_post or not target_comment) and args.task_id and db is not None:
            task = db.get_secondary_reply_task(args.task_id)
            if task:
                target_post = target_post or task.get("platform_post_id")
                target_comment = target_comment or task.get("comment_id")
        if not target_post or not target_comment:
            need("post-id", "comment-id")

        return show(ops.verify_platform(
            db,
            post_id=target_post,
            comment_id=target_comment,
            platform=factory(args),
            account_key=account_key,
            finder_id=finder,
            video_title=target_title,
            comment_text=target_text,
            evidence_dir=args.evidence_dir,
        ))

    need("task-id")
    if args.command == "preflight":
        return show(ops.preflight(db, args.task_id, account_key=account_key, finder_id=finder))
    if args.command == "request-approval":
        need("confirm-reply-sha12")
        return show(ops.request_approval(
            db,
            args.task_id,
            account_key=account_key,
            confirm_reply_sha12=args.confirm_reply_sha12,
            transport=resolved_transport,
            ttl_minutes=args.ttl_minutes,
        ))
    if args.command == "approve":
        need("confirm-reply-sha12")
        return show(ops.approve_local(
            db, args.task_id, account_key=account_key,
            confirm_reply_sha12=args.confirm_reply_sha12, ttl_minutes=args.ttl_minutes,
        ))

    if args.command == "submit":
        if not settings.enable_wechat_secondary_reply or not settings.enable_wechat_secondary_reply_live_submission:
            return show({"ok": False, "reason": "FLAGS_OFF（默认关闭，M3 窗口内临时开启）"})
        if not finder:
            return show({"ok": False, "reason": "AUTHOR_FINDER_ID_NOT_CONFIGURED"})
        return show(ops.submit_single(
            db, args.task_id, platform=factory(args), account_key=account_key, evidence_dir=args.evidence_dir,
        ))
    if args.command == "reconcile-platform":
        if not args.confirm_readonly_platform_access:
            return show({"ok": False, "reason": "需要 --confirm-readonly-platform-access 明确确认只读访问平台"})
        if not finder:
            return show({"ok": False, "reason": "AUTHOR_FINDER_ID_NOT_CONFIGURED"})
        return show(ops.reconcile_on_platform(
            db, args.task_id, platform=factory(args), account_key=account_key, evidence_dir=args.evidence_dir,
        ))
    return 2


def main(argv: Optional[List[str]] = None, platform_factory=None, approval_transport=_UNSET_TRANSPORT):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] in SUBCOMMANDS:
            return ops_main(argv, platform_factory, approval_transport=approval_transport)

        parser = argparse.ArgumentParser(
            description="视频号二级回复（旧式只读/演示开关；真实操作请使用子命令: " + ", ".join(sorted(SUBCOMMANDS)) + "）"
        )
        parser.add_argument("--post-id", type=str, help="视频号平台作品 exportId")
        parser.add_argument("--task-id", type=int, help="指定的二级回复任务 ID")
        parser.add_argument("--dry-run", action="store_true", help="本地只读模式，零写操作零副作用")
        parser.add_argument("--reconcile", action="store_true", help="仅本地检视待对账任务（不访问平台；平台对账请用 reconcile-platform）")
        parser.add_argument("--demo", action="store_true", help="运行离线 4 路径重现验证 Demo")

        args = parser.parse_args(argv)

        if args.demo:
            results = run_offline_4path_demo()
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0

        # 先决定模式，再打开数据库：只读模式绝不构造可写 PipelineDB（会触发建表/迁移/幽灵任务整理）
        if args.reconcile or args.dry_run:
            db_path = DEFAULT_DB_PATH
            refuse = _read_only_refusal(db_path)
            if refuse:
                print(json.dumps({"mode": "inspection", "refused": refuse}, ensure_ascii=False, indent=2))
                return 2
            db = PipelineDB(db_path=str(db_path), read_only=True)
            if args.reconcile:
                logger.info("[Local inspection] 本地待对账任务只读检视（不访问平台，不等于平台对账）...")
                res = run_reconcile_inspection(db, args.post_id)
            else:
                logger.info("[DryRun] 本地只读模式，不执行任何外部操作或写事务。")
                res = run_dry_run_inspection(db, args.post_id or "export/default_dry_run")
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0

        parser.print_help()
        return 2
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2


if __name__ == "__main__":
    sys.exit(main())


#!/usr/bin/env python3
"""视频号二级回复 CLI 与自动化调度入口。

特性开关与提交闸门默认严格关闭；
dry-run 模式下数据库完全只读，不启动浏览器、不调用外部 API、零副作用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
    dispatch_approval_request,
    handle_approval_callback,
)
from video_processing.interaction.secondary_reply_browser_adapter import (
    SecondaryReplyBrowserAdapter,
    SecondaryReplySubmissionGuard,
)
from video_processing.interaction.secondary_reply_contract import (
    AudienceCommentRecord,
    SecondaryReplyIntent,
    SecondaryReplyStyle,
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
    material = {"title": "合成演示视频", "evidence": {"fixture_segment_1": "【合成夹具材料，仅用于离线演示】"}}

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
        (task_1,) = orch.ingest_and_draft(post_id=post_id, comments=[base], video_context=material)
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
        (task_2,) = orch.ingest_and_draft(post_id=post_id, comments=[extra_comment("demo_cmt_2", "为什么会出现这种情况？")], video_context=material)
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
        (task_3,) = orch.ingest_and_draft(post_id=post_id, comments=[extra_comment("demo_cmt_3", "为什么会出现这种情况？")], video_context=material)
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
        with db.get_connection() as conn:
            conn.execute("DELETE FROM wechat_secondary_reply_tasks WHERE id = ?", (task_1,))
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


def main():
    parser = argparse.ArgumentParser(description="视频号二级回复自动化处理")
    parser.add_argument("--post-id", type=str, help="视频号平台作品 exportId")
    parser.add_argument("--task-id", type=int, help="指定的二级回复任务 ID")
    parser.add_argument("--dry-run", action="store_true", help="本地只读模式，零写操作零副作用")
    parser.add_argument("--reconcile", action="store_true", help="对 UNCERTAIN 任务进行只读对账")
    parser.add_argument("--demo", action="store_true", help="运行离线 4 路径重现验证 Demo")

    args = parser.parse_args()

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
            logger.info("[Reconcile] 本地 UNCERTAIN 任务只读检视（不访问平台）...")
            res = run_reconcile_inspection(db, args.post_id)
        else:
            logger.info("[DryRun] 本地只读模式，不执行任何外部操作或写事务。")
            res = run_dry_run_inspection(db, args.post_id or "export/default_dry_run")
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if not settings.enable_wechat_secondary_reply:
        logger.info("enable_wechat_secondary_reply 特性开关未开启，安全停止。")
        return 0

    if not settings.enable_wechat_secondary_reply_live_submission:
        logger.info("enable_wechat_secondary_reply_live_submission 提交闸门未开启，安全停止真实发送。")
        return 0

    # 真实发送链路尚未接线（M3 之前不实现）：明确拒绝，不得静默返回成功
    logger.error("真实二级回复执行链路尚未接线，拒绝运行（退出码 3）。")
    return 3


if __name__ == "__main__":
    sys.exit(main())


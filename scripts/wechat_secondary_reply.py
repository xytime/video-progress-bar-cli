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
    """离线 4 路径重现验证 Demo。

    1. 路径一（成功与防重）：解析真实载荷 -> 发现入库 -> 起草 -> 虚拟审批 -> 提交意图落盘 -> 回执与回读 -> VERIFIED。二次运行被防重账本拦截。
    2. 路径二（前置路由守卫）：错作品 exportId 或错 rootCommentId 在网络发送前硬拦截，零出站流量。
    3. 路径三（异常只读对账）：提交后网络丢包/假死，安全转入 UNCERTAIN，执行只读对账。
    4. 路径四（墓碑持久保护）：任务被物理删除后，独立防重账本墓碑依然阻断重发。
    """
    logger.info("开始执行离线 4 路径重现验证 Demo...")
    results: Dict[str, Any] = {}

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "demo.db"
        db = PipelineDB(db_path=str(db_path))

        # ==========================================
        # 路径一：全链路成功与二次防重拦截
        # ==========================================
        logger.info("[Demo] 路径一：开始全链路成功与二次防重验证...")
        post_id = "export/synth_video_888"
        fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "secondary_reply" / "sanitized_api_responses.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            fixture_data = json.load(f)

        # 1. 严格 API 载荷解析（T01/T02/T03/T12）
        parse_res = parse_wechat_comment_list_payload(
            fixture_data["comment_list"],
            platform_post_id=post_id,
            author_username="v2_synthetic_author_finder_id@finder",
            strict_schema=True,
        )
        assert parse_res.top_level_status == TopLevelPaginationStatus.COMPLETE
        assert parse_res.author_first_comment is not None
        assert parse_res.author_first_comment.is_author is True
        assert len(parse_res.comments) >= 1

        db.save_discovered_audience_comments(
            post_id,
            [
                {
                    "comment_id": c.comment_id,
                    "nickname": c.nickname,
                    "content": c.content,
                    "createtime": c.createtime,
                }
                for c in parse_res.comments
            ],
        )

        target_comment = parse_res.comments[0]
        root_id = target_comment.comment_id

        # 2. 生成起草（规则引擎保证符合 Scheme A 契约）
        service = SecondaryReplyService(censor=SecondaryReplyCensor())
        draft = service.generate_draft(
            comment=target_comment,
            video_context={"title": "全球货币与资产配置解析"},
        )
        assert draft.intent == SecondaryReplyIntent.REPLY
        assert draft.evidence_refs

        # 3. 创建任务并派发 Telegram 审批请求
        task_id_1 = db.create_or_update_secondary_reply_task(
            platform_post_id=post_id,
            comment_id=root_id,
            intent=draft.intent.value,
            style=draft.style.value,
            chinese_reply=draft.chinese_reply,
            english_reply=draft.english_reply,
            formatted_reply=draft.formatted_reply,
            evidence_refs=draft.evidence_refs,
            provider="rule_engine",
            status="PENDING_REVIEW",
        )
        transport = FakeApprovalTransport()
        dispatch_ok, dispatch_msg = dispatch_approval_request(
            db=db,
            task_id=task_id_1,
            transport=transport,
            approver_telegram_id="888999",
            approver_chat_id="888999",
            admin_ids_override="888999",
        )
        assert dispatch_ok and len(transport.sent_messages) == 1
        msg = transport.sent_messages[0]
        app_callback_data = msg["inline_keyboard"][0][0]["callback_data"]

        # 4. 模拟人工通过审批
        cb_ok, cb_msg = handle_approval_callback(
            db=db,
            callback_data=app_callback_data,
            user_id="888999",
            admin_ids_override="888999",
        )
        assert cb_ok
        task_1 = db.get_secondary_reply_task(task_id_1)
        assert task_1["status"] == "APPROVED"

        # 5. 调度器领取任务并持久化提交意图
        claimed_1 = db.claim_approved_reply_task(task_id=task_id_1)
        assert claimed_1 is not None
        intent_ok, intent_msg = db.record_secondary_reply_submit_intent(
            task_id_1, claimed_1["lease_token"]
        )
        assert intent_ok

        # 6. 提交成功并回读确认
        db.record_secondary_reply_success(
            task_id=task_id_1,
            platform_reply_comment_id="synth_platform_reply_999",
            evidence_path=str(Path(tmp_dir) / "evidence_verified.png"),
        )
        task_1_final = db.get_secondary_reply_task(task_id_1)
        ledger_1 = db.check_secondary_reply_idempotency(post_id, root_id)
        assert task_1_final["status"] == "VERIFIED"
        assert ledger_1["status"] == "VERIFIED"

        # 7. 二次运行尝试：同一作品同一评论再次尝试创建与提交
        task_id_dup = db.create_or_update_secondary_reply_task(
            platform_post_id=post_id,
            comment_id=root_id,
            intent="REPLY",
            style="MACRO",
            chinese_reply="尝试再次回复",
            evidence_refs=["secondary_retry_evidence"],
            provider="rule_engine",
            status="APPROVED",
        )
        claimed_dup = db.claim_approved_reply_task(task_id=task_id_dup)
        now_30s_later = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
        intent_dup_ok, intent_dup_err = db.record_secondary_reply_submit_intent(
            task_id_dup, claimed_dup["lease_token"], now_utc=now_30s_later
        )
        assert not intent_dup_ok
        assert "IDEMPOTENCY_CONFLICT" in intent_dup_err

        results["path_1_success_and_idempotency"] = {
            "status": "PASSED",
            "task_id": task_id_1,
            "final_status": task_1_final["status"],
            "platform_reply_comment_id": task_1_final["platform_reply_comment_id"],
            "second_run_intercepted": not intent_dup_ok,
            "second_run_reason": intent_dup_err,
        }

        # ==========================================
        # 路径二：前置路由守卫拦截错作品/错评论/错账号/缺字段
        # ==========================================
        logger.info("[Demo] 路径二：开始前置路由守卫拦截错作品验证...")
        guard = SecondaryReplySubmissionGuard(
            expected_export_id=post_id,
            expected_root_comment_id=root_id,
            expected_content=draft.formatted_reply,
            expected_finder_id="v2_synthetic_author_finder_id@finder",
        )

        class FakeInterceptedRequest:
            method = "POST"
            url = "https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/comment/create_comment"
            post_data_json = {
                "exportId": "export/WRONG_VIDEO_999",
                "rootCommentId": root_id,
                "replyCommentId": root_id,
                "content": draft.formatted_reply,
                "_log_finder_id": "v2_synthetic_author_finder_id@finder",
            }

        guard_pass = guard.capture_request(FakeInterceptedRequest())
        assert not guard_pass
        assert len(guard.requests) == 0
        assert len(guard.mismatched_requests) == 1
        mism = guard.mismatched_requests[0]

        results["path_2_route_guard_mismatch"] = {
            "status": "PASSED",
            "guard_blocked": not guard_pass,
            "blocked_reason": mism.get("reason"),
            "details": mism.get("details"),
        }

        # ==========================================
        # 路径三：提交后异常转入 UNCERTAIN 对账
        # ==========================================
        logger.info("[Demo] 路径三：开始提交后丢包转入 UNCERTAIN 只读对账验证...")
        root_id_3 = "demo_root_cmt_103"
        task_id_3 = db.create_or_update_secondary_reply_task(
            platform_post_id=post_id,
            comment_id=root_id_3,
            intent="REPLY",
            style="PRAGMATIC",
            chinese_reply="测试异常场景",
            evidence_refs=["evidence_path3"],
            provider="rule_engine",
            status="APPROVED",
        )
        claimed_3 = db.claim_approved_reply_task(task_id=task_id_3)
        assert claimed_3 is not None
        now_path3 = (datetime.now(timezone.utc) + timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
        intent_3_ok, intent_3_err = db.record_secondary_reply_submit_intent(
            task_id_3, claimed_3["lease_token"], now_utc=now_path3
        )
        assert intent_3_ok, f"Path 3 intent failed: {intent_3_err}"

        # 模拟提交发出但网络丢包/假死未获得明确 201 回执
        db.record_secondary_reply_uncertain(
            task_id=task_id_3,
            error_message="提交网络丢包或超时，转入只读对账",
            evidence_path=str(Path(tmp_dir) / "evidence_drop.png"),
        )
        task_3 = db.get_secondary_reply_task(task_id_3)
        ledger_3 = db.check_secondary_reply_idempotency(post_id, root_id_3)
        assert task_3["status"] == "UNCERTAIN"
        assert ledger_3["status"] == "UNCERTAIN"

        # 验证只读对账查询
        uncertain_tasks = db.get_uncertain_secondary_reply_tasks(post_id)
        assert any(t["id"] == task_id_3 for t in uncertain_tasks)

        # 模拟只读对账安全终结
        db.reconcile_secondary_reply_uncertain(
            task_id=task_id_3,
            verified=False,
            reason="对账确认：平台未找到该回复",
        )
        task_3_reconciled = db.get_secondary_reply_task(task_id_3)
        assert task_3_reconciled["status"] == "FAILED"

        results["path_3_drop_uncertain_reconcile"] = {
            "status": "PASSED",
            "task_id": task_id_3,
            "task_status": task_3["status"],
            "ledger_status": ledger_3["status"],
            "error_message": task_3["error_message"],
            "reconciled_status": task_3_reconciled["status"],
        }

        # ==========================================
        # 路径四：任务被物理删除后墓碑仍然阻断重发
        # ==========================================
        logger.info("[Demo] 路径四：开始任务删除后墓碑持久防护验证...")
        with db.get_connection() as conn:
            conn.execute("DELETE FROM wechat_secondary_reply_tasks WHERE id = ?", (task_id_1,))

        deleted_task = db.get_secondary_reply_task(task_id_1)
        assert deleted_task is None

        tombstone = db.check_secondary_reply_idempotency(post_id, root_id)
        assert tombstone is not None
        assert tombstone["status"] == "VERIFIED"

        task_id_4 = db.create_or_update_secondary_reply_task(
            platform_post_id=post_id,
            comment_id=root_id,
            intent="REPLY",
            style="MACRO",
            chinese_reply="重新创建的任务尝试提交",
            evidence_refs=["evidence_tombstone"],
            provider="rule_engine",
            status="APPROVED",
        )
        claimed_4 = db.claim_approved_reply_task(task_id=task_id_4)
        now_120s_later = (datetime.now(timezone.utc) + timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
        intent_4_ok, intent_4_err = db.record_secondary_reply_submit_intent(
            task_id_4, claimed_4["lease_token"], now_utc=now_120s_later
        )
        assert not intent_4_ok
        assert "IDEMPOTENCY_CONFLICT" in intent_4_err

        results["path_4_tombstone_survives_deletion"] = {
            "status": "PASSED",
            "task_deleted": deleted_task is None,
            "tombstone_survived": tombstone["status"] == "VERIFIED",
            "recreation_blocked": not intent_4_ok,
            "recreation_blocked_reason": intent_4_err,
        }

    logger.info("离线 4 路径重现验证 Demo 全部顺利完成并通过！")
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


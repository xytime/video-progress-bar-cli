"""视频号二级回复业务编排（可注入平台端口，离线与真实适配器共用）。

流程：采集入库 -> 草稿（含生成后审查）-> 审批派发 -> 批准回调 -> 认领 -> 发送前终审（当前政策）
-> 作者是否已回复复核 -> 持久提交意图（同事务原子预占配额）-> 路由守卫放行唯一出站请求
-> 关联回执校验 -> 刷新后独立回读 -> VERIFIED / UNCERTAIN，崩溃后只读对账。

边界：
- 本模块不依赖浏览器；平台通过 ``SecondaryReplyPlatformPort`` 注入。真实浏览器适配器默认不接入本编排。
- 任何已持久化提交意图之后的不明确结果一律进入 UNCERTAIN/只读对账，绝不重发。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Antigravity | 新增：统一编排服务，演示 CLI 与测试共用；终审、意图、守卫、回读、对账同一路径 |
"""

from __future__ import annotations

import datetime
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_approval import (
    dispatch_approval_request,
    handle_approval_callback,
)
from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplySubmissionGuard
from video_processing.interaction.secondary_reply_contract import (
    AudienceCommentRecord,
    SecondaryReplyIntent,
)
from video_processing.interaction.secondary_reply_service import (
    CensorshipViolationError,
    SecondaryReplyService,
)

logger = logging.getLogger(__name__)


@dataclass
class PlatformSendResult:
    """平台端口一次发送尝试的结果（由端口如实填写，编排据此判定）。"""

    intent_persisted: bool = False  # before_submit 是否成功落盘意图
    guard: Optional[SecondaryReplySubmissionGuard] = None
    exception: Optional[str] = None


@dataclass
class LookupResult:
    """刷新后服务器数据中的回读结果。"""

    found: bool
    reply_id: str = ""
    complete: bool = False  # 是否完整遍历（仅供报告；未见回复不等于未出站）


class SecondaryReplyPlatformPort(Protocol):
    account_finder_id: str

    def author_reply_state(self, *, post_id: str, root_id: str) -> str:
        """返回 REPLIED / NOT_REPLIED / UNKNOWN（以原生作者 ID 判断）。"""

    def send_reply(
        self, *, post_id: str, root_id: str, text: str,
        before_submit: Callable[[], bool], guard: SecondaryReplySubmissionGuard,
    ) -> PlatformSendResult:
        """先 before_submit 落意图，再经 guard 放行唯一出站请求。"""

    def lookup_reply(self, *, post_id: str, root_id: str, text: str) -> LookupResult:
        """刷新后从服务器数据查找同作者同文回复。"""


@dataclass
class SubmitOutcome:
    status: str  # VERIFIED / UNCERTAIN / BLOCKED_BY_GUARD / SKIPPED_ALREADY_REPLIED / REJECTED_BEFORE_INTENT / NOT_CLAIMABLE
    detail: str = ""
    task_id: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


class SecondaryReplyOrchestrator:
    def __init__(
        self,
        *,
        db: PipelineDB,
        service: SecondaryReplyService,
        platform: SecondaryReplyPlatformPort,
        approval_transport: Any,
        account_key: str,
        approver_id: str,
        approver_chat_id: str,
        admin_ids_override: Optional[str] = None,
        clock: Optional[Callable[[], datetime.datetime]] = None,
        allow_fixture_drafts: bool = False,
    ) -> None:
        if not account_key:
            raise ValueError("account_key 不能为空")
        self.db = db
        self.service = service
        self.platform = platform
        self.transport = approval_transport
        self.account_key = account_key
        self.approver_id = approver_id
        self.approver_chat_id = approver_chat_id
        self.admin_ids_override = admin_ids_override
        self.allow_fixture_drafts = allow_fixture_drafts  # 仅离线演示/测试为 True；真实 provider 未验证前默认拒绝发送固定套话草稿
        self.clock = clock  # 仅用于离线演示/测试固定时钟；生产为 None 使用真实 UTC

    # ---------------- 采集 / 草稿 / 审批 ----------------
    def ingest_and_draft(
        self, *, post_id: str, comments: List[AudienceCommentRecord], video_context: Optional[Dict[str, Any]],
    ) -> List[int]:
        """采集入库并为每条新评论生成草稿、派发审批。返回产生的任务 ID。"""
        self.db.save_discovered_audience_comments(
            post_id,
            [
                {"comment_id": c.comment_id, "nickname": c.nickname, "content": c.content, "createtime": c.createtime}
                for c in comments
            ],
            account_key=self.account_key,
        )
        task_ids: List[int] = []
        for row in self.db.get_unprocessed_audience_comments(post_id, account_key=self.account_key):
            record = next((c for c in comments if c.comment_id == row["comment_id"]), None)
            if record is None:
                continue
            try:
                draft = self.service.generate_draft(record, video_context=video_context)
            except Exception as exc:  # 生成/审查失败进入待处理，不用无关模板回复
                logger.warning("草稿生成失败，转人工: %s", exc)
                continue
            if draft.intent != SecondaryReplyIntent.REPLY:
                self.db.create_or_update_secondary_reply_task(
                    platform_post_id=post_id, comment_id=record.comment_id,
                    intent=draft.intent.value, style=draft.style.value,
                    reason_code=draft.reason_code, provider=draft.provider,
                    status="MANUAL" if draft.intent == SecondaryReplyIntent.MANUAL else "SKIPPED",
                    account_key=self.account_key,
                )
                continue
            task_id = self.db.create_or_update_secondary_reply_task(
                platform_post_id=post_id, comment_id=record.comment_id,
                intent=draft.intent.value, style=draft.style.value,
                chinese_reply=draft.chinese_reply, english_reply=draft.english_reply,
                formatted_reply=draft.formatted_reply, reason_code=draft.reason_code,
                evidence_refs=draft.evidence_refs, provider=draft.provider,
                status="PENDING_REVIEW", account_key=self.account_key,
            )
            ok, msg = dispatch_approval_request(
                db=self.db, task_id=task_id, transport=self.transport,
                approver_telegram_id=self.approver_id, approver_chat_id=self.approver_chat_id,
                admin_ids_override=self.admin_ids_override,
            )
            if not ok:
                logger.info("审批派发未成功(%s)，任务停留待审核", msg)
            task_ids.append(task_id)
        return task_ids

    def approve_via_callback(self, callback_data: str, *, user_id: str, chat_id: str):
        return handle_approval_callback(
            self.db, callback_data, user_id, chat_id, admin_ids_override=self.admin_ids_override
        )

    # ---------------- 发送 ----------------
    def submit(self, task_id: int) -> SubmitOutcome:
        claimed = self.db.claim_approved_reply_task(task_id=task_id)
        if not claimed:
            return SubmitOutcome("NOT_CLAIMABLE", "任务不是已批准状态或租约仍有效", task_id)
        lease = claimed["lease_token"]
        post_id, root_id = claimed["platform_post_id"], claimed["comment_id"]
        if (claimed.get("account_key") or "") != self.account_key:
            self.db.record_secondary_reply_failed(task_id, error_message="ACCOUNT_KEY_MISMATCH")
            return SubmitOutcome("REJECTED_BEFORE_INTENT", "ACCOUNT_KEY_MISMATCH", task_id)

        if claimed.get("provider") == "rule_secondary_provider" and not self.allow_fixture_drafts:
            self.db.record_secondary_reply_failed(task_id, error_message="REAL_PROVIDER_UNAVAILABLE_FIXTURE_DRAFT")
            return SubmitOutcome("REJECTED_BEFORE_INTENT", "REAL_PROVIDER_UNAVAILABLE: fixture 草稿不得发送", task_id)

        # 发送前终审：以当前政策检查实际获批正文（中英分别、合并与跨字段）
        try:
            final_text = self.service.validate_for_submission(
                claimed["chinese_reply"], claimed["english_reply"], claimed["formatted_reply"]
            )
        except Exception as exc:
            self.db.record_secondary_reply_failed(task_id, error_message=f"FINAL_REVIEW_BLOCK: {exc}")
            return SubmitOutcome("REJECTED_BEFORE_INTENT", f"FINAL_REVIEW_BLOCK: {exc}", task_id)
        if unicodedata.normalize("NFC", final_text) != unicodedata.normalize("NFC", claimed["formatted_reply"] or ""):
            self.db.record_secondary_reply_failed(task_id, error_message="FINAL_TEXT_DIFFERS_FROM_APPROVED")
            return SubmitOutcome("REJECTED_BEFORE_INTENT", "FINAL_TEXT_DIFFERS_FROM_APPROVED", task_id)

        # 锁内复核：作者是否已回复（手机并发仍无法被本地锁排除）
        state = self.platform.author_reply_state(post_id=post_id, root_id=root_id)
        if state == "REPLIED":
            self.db.record_secondary_reply_skipped(task_id, reason="AUTHOR_ALREADY_REPLIED")
            return SubmitOutcome("SKIPPED_ALREADY_REPLIED", "作者已回复", task_id)
        if state != "NOT_REPLIED":
            self.db.record_secondary_reply_failed(task_id, error_message="AUTHOR_REPLY_STATE_UNKNOWN")
            return SubmitOutcome("REJECTED_BEFORE_INTENT", "无法完整判断是否已回复，禁止发送", task_id)

        guard = SecondaryReplySubmissionGuard(
            post_id, root_id, final_text, expected_finder_id=self.platform.account_finder_id
        )
        intent_msgs: List[str] = []

        def before_submit() -> bool:
            now_utc = self.clock().strftime("%Y-%m-%d %H:%M:%S") if self.clock else None
            ok, msg = self.db.record_secondary_reply_submit_intent(task_id, lease, now_utc=now_utc)
            intent_msgs.append(msg)
            return ok

        try:
            result = self.platform.send_reply(
                post_id=post_id, root_id=root_id, text=final_text, before_submit=before_submit, guard=guard
            )
        except Exception as exc:
            after = self.db.get_secondary_reply_task(task_id)
            if after and after["status"] == "SUBMIT_INTENT":
                self.db.record_secondary_reply_uncertain(task_id, error_message=f"发送过程异常: {exc}")
                return SubmitOutcome("UNCERTAIN", f"发送过程异常: {exc}", task_id)
            self.db.record_secondary_reply_failed(task_id, error_message=f"PRE_INTENT_EXCEPTION: {exc}")
            return SubmitOutcome("REJECTED_BEFORE_INTENT", str(exc), task_id)

        if not result.intent_persisted:
            self.db.record_secondary_reply_failed(task_id, error_message=f"INTENT_REJECTED: {intent_msgs[-1:]}")
            return SubmitOutcome("REJECTED_BEFORE_INTENT", "; ".join(intent_msgs), task_id)

        if not guard.requests:
            # 意图已落盘，但守卫在网络前拦截了所有写请求：有明确“未出站”证据
            evidence = "guard_aborted_before_network: " + ",".join(
                str(m.get("reason")) for m in guard.mismatched_requests
            )
            if guard.mismatched_requests:
                self.db.reconcile_secondary_reply_uncertain(
                    task_id, verified=False, outcome="CONFIRMED_NOT_SENT",
                    not_sent_evidence=evidence, reason=evidence,
                )
                return SubmitOutcome("BLOCKED_BY_GUARD", evidence, task_id)
            self.db.record_secondary_reply_uncertain(task_id, error_message="意图已落盘但无出站/拦截记录，转对账")
            return SubmitOutcome("UNCERTAIN", "no outbound evidence", task_id)

        ok, reply_id, reason = guard.validate_success_response()
        if not ok:
            self.db.record_secondary_reply_uncertain(task_id, error_message=f"无关联的业务成功回执: {reason}")
            return SubmitOutcome("UNCERTAIN", reason, task_id)

        # 刷新后独立回读
        look = self.platform.lookup_reply(post_id=post_id, root_id=root_id, text=final_text)
        if not (look.found and look.reply_id == reply_id):
            self.db.record_secondary_reply_uncertain(task_id, error_message="平台回执成功但刷新后回读未确认")
            return SubmitOutcome("UNCERTAIN", "readback_not_confirmed", task_id)
        if not self.db.record_secondary_reply_success(
            task_id, platform_reply_comment_id=reply_id, evidence_path="fixture://readback"
        ):
            self.db.record_secondary_reply_uncertain(task_id, error_message="成功落库被拒绝")
            return SubmitOutcome("UNCERTAIN", "success_persist_rejected", task_id)
        return SubmitOutcome("VERIFIED", reply_id, task_id, {"reply_id": reply_id})

    # ---------------- 只读对账 ----------------
    def reconcile(self, task_id: int) -> SubmitOutcome:
        """只读对账：不发送任何写请求。"""
        task = self.db.get_secondary_reply_task(task_id)
        if not task or task["status"] not in ("UNCERTAIN", "SUBMIT_INTENT"):
            return SubmitOutcome("NOT_RECONCILABLE", "", task_id)
        look = self.platform.lookup_reply(
            post_id=task["platform_post_id"], root_id=task["comment_id"], text=task["formatted_reply"]
        )
        if look.found and look.reply_id:
            self.db.reconcile_secondary_reply_uncertain(
                task_id, verified=True, platform_reply_comment_id=look.reply_id, outcome="FOUND"
            )
            return SubmitOutcome("VERIFIED", look.reply_id, task_id)
        self.db.reconcile_secondary_reply_uncertain(
            task_id, verified=False, outcome="NOT_OBSERVED_INCOMPLETE",
            reason="未观察到回复，无法证明未发出，保持 UNCERTAIN",
        )
        return SubmitOutcome("UNCERTAIN", "NOT_OBSERVED_INCOMPLETE", task_id)

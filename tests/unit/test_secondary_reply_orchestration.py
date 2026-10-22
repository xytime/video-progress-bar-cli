"""二级回复续作验收：账号隔离、受保护终态、审批绑定、共享配额、统一编排的成功/失败/对账路径。

每条拒绝类测试都有相邻的合法路径，避免“全部拒绝也通过”。
"""

from __future__ import annotations

import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from config.settings import settings
from tests.unit.secondary_reply_support import TEST_ACCOUNT, TEST_APPROVER, TEST_CHAT, approved_task
from video_processing.db.database import PipelineDB
from video_processing.interaction.runner import run_interaction_tick
from video_processing.interaction.secondary_reply_approval import FakeApprovalTransport
from video_processing.interaction.secondary_reply_contract import (
    AudienceCommentRecord,
    SecondaryReplyIntent,
)
from video_processing.interaction.secondary_reply_fake_platform import FakeSecondaryReplyPlatform
from video_processing.interaction.secondary_reply_orchestrator import SecondaryReplyOrchestrator
from video_processing.interaction.secondary_reply_service import (
    SecondaryReplyCensor,
    SecondaryReplyService,
)

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 12, 4, 0, 0, tzinfo=UTC)  # 上海 12:00
QUESTION = "为什么会出现这种情况？"


def _ledger_rows(db: PipelineDB, count: int, *, minutes_ago: int = 6, account_key: str = TEST_ACCOUNT) -> None:
    created = (NOW - datetime.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with db.get_connection() as conn:
        for i in range(count):
            conn.execute(
                "INSERT INTO wechat_secondary_reply_idempotency_ledger "
                "(account_key, platform_post_id, root_comment_id, reply_comment_id, content_hash, status, created_at) "
                "VALUES (?, ?, ?, ?, 'h', 'VERIFIED', ?)",
                (account_key, f"export/older_{i}", f"old_{i}", f"r_{i}", created),
            )


@pytest.fixture(autouse=True)
def _no_min_interval(monkeypatch):
    monkeypatch.setattr(settings, "wechat_reply_min_interval_seconds", 0, raising=False)


# ---------------------------------------------------------------------------
# 共享配额：恰有一次成功、另一次因额度不足被拒绝
# ---------------------------------------------------------------------------

def _race(funcs):
    barrier = threading.Barrier(len(funcs))

    def run(fn):
        barrier.wait(timeout=5)
        return fn()

    with ThreadPoolExecutor(max_workers=len(funcs)) as pool:
        return list(pool.map(run, funcs))


def test_two_secondary_workers_exactly_one_gets_last_slot(tmp_path):
    db = PipelineDB(str(tmp_path / "q.db"))
    _ledger_rows(db, 9)
    claims = []
    for i in range(2):
        tid = approved_task(db, platform_post_id=f"export/new_{i}", comment_id=f"new_{i}", chinese_reply="谢谢分享。", english_reply="Thanks.")
        claims.append(db.claim_approved_reply_task(task_id=tid))
    results = _race([
        (lambda c=c: db.record_secondary_reply_submit_intent(c["id"], c["lease_token"], now_utc=NOW.strftime("%Y-%m-%d %H:%M:%S")))
        for c in claims
    ])
    assert sorted(bool(r[0]) for r in results) == [False, True]
    rejected = [r for r in results if not r[0]][0]
    assert rejected[1].startswith("QUOTA_REJECTED"), rejected


def _published(db: PipelineDB, tmp_path, suffix: str):
    yid = f"yt_{suffix}"
    db.add_video(yid, f"T {suffix}", "ch", score=80)
    ev = tmp_path / f"{suffix}.png"
    ev.write_bytes(b"x")
    return db.record_wechat_publication_confirmation(
        yid, evidence_path=str(ev), state="PUBLISHED", platform_post_id=f"export/fc_{suffix}"
    )


def test_first_comment_and_secondary_race_for_last_slot(tmp_path):
    db = PipelineDB(str(tmp_path / "mix.db"))
    _ledger_rows(db, 8)
    # 再放 1 条首评占用名额：此时合计 9，剩 1 个
    pub0 = _published(db, tmp_path, "used")
    q0 = db.queue_wechat_interaction(publication_id=pub0["id"], platform_post_id="export/fc_used", interaction_type="POLL_STAND", provider="t", comment_text="已用首评", now=NOW - datetime.timedelta(minutes=5))
    c0 = db.claim_due_wechat_interaction(now=NOW - datetime.timedelta(minutes=5), platform_post_id="export/fc_used")
    assert db.mark_wechat_interaction_submit_intent(q0["id"], c0["lease_token"], now=NOW - datetime.timedelta(minutes=5), enforce_shared_quota=True)

    pub = _published(db, tmp_path, "race")
    q = db.queue_wechat_interaction(publication_id=pub["id"], platform_post_id="export/fc_race", interaction_type="POLL_STAND", provider="t", comment_text="首评竞争", now=NOW)
    first = db.claim_due_wechat_interaction(now=NOW, platform_post_id="export/fc_race")
    tid = approved_task(db, platform_post_id="export/sec_race", comment_id="sec_race", chinese_reply="谢谢分享。", english_reply="Thanks.")
    sec = db.claim_approved_reply_task(task_id=tid)

    results = _race([
        lambda: ("first", db.mark_wechat_interaction_submit_intent(q["id"], first["lease_token"], now=NOW, enforce_shared_quota=True)),
        lambda: ("second", db.record_secondary_reply_submit_intent(sec["id"], sec["lease_token"], now_utc=NOW.strftime("%Y-%m-%d %H:%M:%S"))[0]),
    ])
    assert sum(1 for _, ok in results if ok) == 1, results


class _RecordingServices:
    def __init__(self):
        self.intent_results = []

    def generate_comment(self, target, *, force_rule):
        from video_processing.interaction.contract import InteractionType
        return SimpleNamespace(formatted_comment="这是一条用于共享配额测试的首评文本，不会被真正发送。", interaction_type=InteractionType.POLL_STAND, provider="t")

    def post_comment(self, **kw):
        ok = kw["before_submit"]() if kw["before_submit"] else None
        self.intent_results.append(ok)
        return ("UNCERTAIN", None, "test") if ok else ("FAILED", None, "intent rejected")

    def notify_result(self, *a):
        return None


@pytest.mark.parametrize("flag,expected_first_intent", [(True, False), (False, True)])
def test_runner_first_comment_uses_shared_quota_only_when_secondary_feature_on(tmp_path, monkeypatch, flag, expected_first_intent):
    """首评实际调用路径：二级回复功能开启时共享配额生效；关闭时保持既有首评行为（相邻合法路径）。"""
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply", flag)
    db = PipelineDB(str(tmp_path / "runner.db"))
    _ledger_rows(db, 10)
    _published(db, tmp_path, "run")
    services = _RecordingServices()
    run_interaction_tick(db, services, clock=lambda: NOW, evidence_root=tmp_path)
    assert services.intent_results == [expected_first_intent]


# ---------------------------------------------------------------------------
# 审批：chat 绑定、批准后到出站前的复核
# ---------------------------------------------------------------------------

def _pending_with_callback(tmp_path):
    db = PipelineDB(str(tmp_path / "ap.db"))
    from video_processing.interaction.secondary_reply_approval import dispatch_approval_request
    db.save_discovered_audience_comments("export/ap", [{"comment_id": "c1", "nickname": "n", "content": "评论"}], account_key=TEST_ACCOUNT)
    tid = db.create_or_update_secondary_reply_task(
        account_key=TEST_ACCOUNT, platform_post_id="export/ap", comment_id="c1", intent="REPLY", style="MACRO",
        chinese_reply="谢谢。", english_reply="Thanks.", formatted_reply="谢谢。\nThanks.", provider="rule_mock", status="PENDING_REVIEW",
    )
    transport = FakeApprovalTransport()
    ok, msg = dispatch_approval_request(db, tid, transport, approver_telegram_id=TEST_APPROVER, approver_chat_id=TEST_CHAT, admin_ids_override=TEST_APPROVER)
    assert ok, msg
    return db, tid, transport.sent_messages[0]["inline_keyboard"][0][0]["callback_data"]


@pytest.mark.parametrize("chat,expected_ok", [(TEST_CHAT, True), ("other_chat", False), ("", False), (None, False)])
def test_callback_chat_must_match_bound_chat(tmp_path, chat, expected_ok):
    from video_processing.interaction.secondary_reply_approval import handle_approval_callback
    db, tid, cb = _pending_with_callback(tmp_path)
    ok, reason = handle_approval_callback(db, cb, TEST_APPROVER, chat, admin_ids_override=TEST_APPROVER)
    assert ok is expected_ok, reason
    assert db.get_secondary_reply_task(tid)["status"] == ("APPROVED" if expected_ok else "PENDING_REVIEW")


def _claimed(db, **kw):
    tid = approved_task(db, **kw)
    return tid, db.claim_approved_reply_task(task_id=tid)


def _intent(db, tid, claim, now=NOW):
    return db.record_secondary_reply_submit_intent(tid, claim["lease_token"], now_utc=now.strftime("%Y-%m-%d %H:%M:%S"))


def test_intent_rechecks_approval_after_queueing(tmp_path):
    db = PipelineDB(str(tmp_path / "re.db"))
    base = dict(chinese_reply="谢谢。", english_reply="Thanks.")
    # 合法
    tid, cl = _claimed(db, platform_post_id="export/ok", comment_id="ok", **base)
    assert _intent(db, tid, cl)[0] is True
    # 批准过期后才出站
    tid, cl = _claimed(db, platform_post_id="export/exp", comment_id="exp", **base)
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_secondary_reply_tasks SET approval_expires_at='2026-10-12 03:00:00' WHERE id=?", (tid,))
    assert _intent(db, tid, cl) == (False, "APPROVAL_EXPIRED")
    # 批准后正文被改
    tid, cl = _claimed(db, platform_post_id="export/txt", comment_id="txt", **base)
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_secondary_reply_tasks SET formatted_reply='被改的正文\nChanged' WHERE id=?", (tid,))
    assert _intent(db, tid, cl) == (False, "DRAFT_TEXT_CHANGED")
    # 批准后版本变化
    tid, cl = _claimed(db, platform_post_id="export/rev", comment_id="rev", **base)
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_secondary_reply_tasks SET revision=revision+1 WHERE id=?", (tid,))
    assert _intent(db, tid, cl) == (False, "DRAFT_REVISION_CHANGED")
    # 批准后源评论变化
    tid, cl = _claimed(db, platform_post_id="export/src", comment_id="src", **base)
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_audience_comments SET content_hash='changed' WHERE comment_id='src'")
    assert _intent(db, tid, cl) == (False, "SOURCE_COMMENT_CHANGED")


def test_intent_rejects_unapproved_task_and_missing_account(tmp_path):
    db = PipelineDB(str(tmp_path / "un.db"))
    tid = db.create_or_update_secondary_reply_task(
        platform_post_id="export/u", comment_id="u", intent="REPLY", style="MACRO", chinese_reply="x", provider="p", status="APPROVED",
    )  # 绕过审批直接写 APPROVED，且没有 account_key
    cl = db.claim_approved_reply_task(task_id=tid)
    assert _intent(db, tid, cl) == (False, "ACCOUNT_KEY_MISSING")
    tid2 = db.create_or_update_secondary_reply_task(
        account_key="a", platform_post_id="export/u", comment_id="u", intent="REPLY", style="MACRO", chinese_reply="x", provider="p", status="APPROVED",
    )
    cl2 = db.claim_approved_reply_task(task_id=tid2)
    assert _intent(db, tid2, cl2) == (False, "NOT_APPROVED")


# ---------------------------------------------------------------------------
# 账号隔离与受保护终态、过期租约
# ---------------------------------------------------------------------------

def test_same_post_and_comment_on_different_accounts_do_not_collide(tmp_path):
    db = PipelineDB(str(tmp_path / "acct.db"))
    a = approved_task(db, account_key="acct_A", platform_post_id="export/p", comment_id="same", chinese_reply="甲。", english_reply="A.")
    b = approved_task(db, account_key="acct_B", platform_post_id="export/p", comment_id="same", chinese_reply="乙。", english_reply="B.")
    assert a != b
    ca, cb = db.claim_approved_reply_task(task_id=a), db.claim_approved_reply_task(task_id=b)
    assert _intent(db, a, ca)[0] is True
    assert _intent(db, b, cb, NOW + datetime.timedelta(minutes=1))[0] is True  # A 的账本不拦截 B
    assert db.check_secondary_reply_idempotency("export/p", "same", account_key="acct_A")["status"] == "INTENT"
    assert db.check_secondary_reply_idempotency("export/p", "same", account_key="acct_B")["status"] == "INTENT"
    # 同账号同目标第二次仍被拦截
    again = db.create_or_update_secondary_reply_task(
        account_key="acct_A", platform_post_id="export/p", comment_id="same", intent="REPLY", style="MACRO",
        chinese_reply="再。", english_reply="Again.", formatted_reply="再。\nAgain.", provider="p", status="PENDING_REVIEW",
    )
    assert again == a and db.get_secondary_reply_task(a)["status"] == "SUBMIT_INTENT"


@pytest.mark.parametrize("protected", ["CLAIMED", "SUBMIT_INTENT", "UNCERTAIN", "VERIFIED"])
def test_upsert_cannot_reset_protected_states(tmp_path, protected):
    db = PipelineDB(str(tmp_path / f"p_{protected}.db"))
    tid, cl = _claimed(db, platform_post_id="export/pp", comment_id="pp", chinese_reply="原文。", english_reply="Orig.")
    if protected != "CLAIMED":
        assert _intent(db, tid, cl)[0]
        if protected == "UNCERTAIN":
            db.record_secondary_reply_uncertain(tid, error_message="x")
        if protected == "VERIFIED":
            assert db.record_secondary_reply_success(tid, platform_reply_comment_id="rid", evidence_path="e")
    again = db.create_or_update_secondary_reply_task(
        account_key=TEST_ACCOUNT, platform_post_id="export/pp", comment_id="pp", intent="REPLY", style="MACRO",
        chinese_reply="改写。", english_reply="Rewritten.", formatted_reply="改写。\nRewritten.", provider="p", status="APPROVED",
    )
    assert again == tid
    row = db.get_secondary_reply_task(tid)
    assert row["status"] == protected and row["chinese_reply"] == "原文。"
    # 相邻合法路径：未保护状态(PENDING_REVIEW)可以改稿并使批准失效
    ok_id = approved_task(db, platform_post_id="export/free", comment_id="free", chinese_reply="一。", english_reply="One.")
    db.create_or_update_secondary_reply_task(
        account_key=TEST_ACCOUNT, platform_post_id="export/free", comment_id="free", intent="REPLY", style="MACRO",
        chinese_reply="二。", english_reply="Two.", formatted_reply="二。\nTwo.", provider="p", status="PENDING_REVIEW",
    )
    r = db.get_secondary_reply_task(ok_id)
    assert r["revision"] == 2 and r["approved_at"] is None and r["bound_reply_text_hash"] is None


def test_expired_lease_old_worker_cannot_send_but_new_worker_can(tmp_path):
    db = PipelineDB(str(tmp_path / "lease.db"))
    tid = approved_task(db, platform_post_id="export/l", comment_id="l", chinese_reply="谢。", english_reply="Thx.")
    old = db.claim_approved_reply_task(task_id=tid, lease_seconds=1)
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_secondary_reply_tasks SET lease_expires_at='2000-01-01 00:00:00' WHERE id=?", (tid,))
    new = db.claim_approved_reply_task(task_id=tid, lease_seconds=300)
    assert new and new["lease_token"] != old["lease_token"]
    assert _intent(db, tid, old) == (False, "LEASE_TOKEN_MISMATCH")  # 旧 worker 不得发送
    assert _intent(db, tid, new)[0] is True


# ---------------------------------------------------------------------------
# 统一编排：平台替身
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path):
    db = PipelineDB(str(tmp_path / "orch.db"))
    platform = FakeSecondaryReplyPlatform()
    transport = FakeApprovalTransport()
    state = {"now": NOW}

    def clock():
        state["now"] += datetime.timedelta(seconds=60)
        return state["now"]

    orch = SecondaryReplyOrchestrator(
        db=db, service=SecondaryReplyService(censor=SecondaryReplyCensor()), platform=platform,
        approval_transport=transport, account_key=TEST_ACCOUNT, approver_id=TEST_APPROVER,
        approver_chat_id=TEST_CHAT, admin_ids_override=TEST_APPROVER, clock=clock, allow_fixture_drafts=True,
    )
    return SimpleNamespace(db=db, platform=platform, transport=transport, orch=orch, state=state)


def _record(cid: str, text: str = QUESTION) -> AudienceCommentRecord:
    return AudienceCommentRecord(platform_post_id="export/orch", comment_id=cid, nickname="观众", content=text, content_hash="h", createtime="1")


def _material(text: str = QUESTION):
    return {"evidence": {"fx1": f"合成夹具材料：{text}"}}


def _approved(env, cid: str) -> int:
    (tid,) = env.orch.ingest_and_draft(post_id="export/orch", comments=[_record(cid)], video_context=_material())
    cb = env.transport.sent_messages[-1]["inline_keyboard"][0][0]["callback_data"]
    ok, msg = env.orch.approve_via_callback(cb, user_id=TEST_APPROVER, chat_id=TEST_CHAT)
    assert ok, msg
    return tid


def test_success_then_second_submit_sends_nothing(env):
    tid = _approved(env, "c1")
    out = env.orch.submit(tid)
    assert out.status == "VERIFIED" and len(env.platform.outbound_requests) == 1
    assert env.db.get_secondary_reply_task(tid)["platform_reply_comment_id"] == out.detail
    assert env.orch.submit(tid).status == "NOT_CLAIMABLE"
    assert len(env.platform.outbound_requests) == 1


@pytest.mark.parametrize("mode", ["wrong-root", "wrong-post", "wrong-account", "missing-account", "altered-text"])
def test_wrong_target_blocked_before_network(env, mode):
    env.platform.mode = mode
    tid = _approved(env, "c_bad")
    out = env.orch.submit(tid)
    assert out.status == "BLOCKED_BY_GUARD" and out.detail.startswith("guard_aborted_before_network")
    assert env.platform.outbound_requests == []
    assert env.db.check_secondary_reply_idempotency("export/orch", "c_bad", account_key=TEST_ACCOUNT)["status"] == "INTENT"
    # 相邻合法路径：同一环境、正确模式，另一条评论成功
    env.platform.mode = "success"
    assert env.orch.submit(_approved(env, "c_good")).status == "VERIFIED"


@pytest.mark.parametrize("mode", ["drop-response", "drop-not-persisted", "optimistic-only", "unrelated-response"])
def test_ambiguous_outcomes_are_uncertain_and_never_resent(env, mode):
    env.platform.mode = mode
    tid = _approved(env, "c_amb")
    out = env.orch.submit(tid)
    assert out.status == "UNCERTAIN"
    task = env.db.get_secondary_reply_task(tid)
    assert task["status"] == "UNCERTAIN"
    sent = len(env.platform.outbound_requests)
    assert env.orch.submit(tid).status == "NOT_CLAIMABLE"  # 不会重发
    assert len(env.platform.outbound_requests) == sent
    # 只读对账：drop-response 服务器已受理 -> FOUND；其余未观察到 -> 保持 UNCERTAIN，且对账不出站
    rec = env.orch.reconcile(tid)
    assert len(env.platform.outbound_requests) == sent
    if mode in ("drop-response", "unrelated-response"):
        assert rec.status == "VERIFIED"
    else:
        assert rec.status == "UNCERTAIN"
        assert env.db.get_secondary_reply_task(tid)["status"] == "UNCERTAIN"


def test_crash_after_intent_is_reconcile_only_after_restart(env, tmp_path):
    env.platform.mode = "crash-after-intent"
    tid = _approved(env, "c_crash")
    out = env.orch.submit(tid)
    assert out.status == "UNCERTAIN"
    reopened = PipelineDB(str(tmp_path / "orch.db"))
    assert tid in [t["id"] for t in reopened.get_uncertain_secondary_reply_tasks("export/orch")]
    assert env.orch.submit(tid).status == "NOT_CLAIMABLE"
    assert env.platform.outbound_requests == []


def test_persisted_intent_without_status_update_is_in_reconcile_queue(env):
    """进程在写 UNCERTAIN 之前死亡：任务停留 SUBMIT_INTENT，仍进入只读对账队列。"""
    tid = _approved(env, "c_intent_only")
    claim = env.db.claim_approved_reply_task(task_id=tid)
    assert env.db.record_secondary_reply_submit_intent(tid, claim["lease_token"], now_utc=NOW.strftime("%Y-%m-%d %H:%M:%S"))[0]
    assert env.db.get_secondary_reply_task(tid)["status"] == "SUBMIT_INTENT"
    assert tid in [t["id"] for t in env.db.get_uncertain_secondary_reply_tasks("export/orch")]
    assert env.orch.reconcile(tid).status == "UNCERTAIN"  # 未观察到 -> 升级为 UNCERTAIN，不重发
    assert env.db.get_secondary_reply_task(tid)["status"] == "UNCERTAIN"


def test_reconcile_never_confirms_not_sent_without_evidence(env):
    tid = _approved(env, "c_ev")
    claim = env.db.claim_approved_reply_task(task_id=tid)
    env.db.record_secondary_reply_submit_intent(tid, claim["lease_token"], now_utc=NOW.strftime("%Y-%m-%d %H:%M:%S"))
    assert env.db.reconcile_secondary_reply_uncertain(tid, verified=False, outcome="CONFIRMED_NOT_SENT") is False
    assert env.db.get_secondary_reply_task(tid)["status"] == "SUBMIT_INTENT"
    assert env.db.reconcile_secondary_reply_uncertain(
        tid, verified=False, outcome="CONFIRMED_NOT_SENT", not_sent_evidence="guard_aborted_before_network"
    ) is True


def test_approval_expired_while_queued_blocks_send(env):
    tid = _approved(env, "c_exp")
    with env.db.get_connection() as conn:
        conn.execute("UPDATE wechat_secondary_reply_tasks SET approval_expires_at='2026-10-12 03:00:00' WHERE id=?", (tid,))
    out = env.orch.submit(tid)
    assert out.status == "REJECTED_BEFORE_INTENT" and "APPROVAL_EXPIRED" in out.detail
    assert env.platform.outbound_requests == []


def test_final_policy_review_runs_on_actual_text_before_send(env):
    class _BlockingCensor(SecondaryReplyCensor):
        def check_reply_safety(self, chinese_reply, english_reply, formatted_reply=None):
            return False, "policy changed after approval"

    tid = _approved(env, "c_pol")
    env.orch.service = SecondaryReplyService(censor=_BlockingCensor())
    out = env.orch.submit(tid)
    assert out.status == "REJECTED_BEFORE_INTENT" and "FINAL_REVIEW_BLOCK" in out.detail
    assert env.platform.outbound_requests == []
    assert env.db.check_secondary_reply_idempotency("export/orch", "c_pol", account_key=TEST_ACCOUNT) is None  # 未建意图


def test_author_already_replied_and_unknown_state_block_send(env):
    env.platform.seed_author_reply("export/orch", "c_phone")
    out = env.orch.submit(_approved(env, "c_phone"))
    assert out.status == "SKIPPED_ALREADY_REPLIED" and env.platform.outbound_requests == []
    env.platform.mode = "state-unknown"
    tid = _approved(env, "c_unknown")
    out2 = env.orch.submit(tid)
    assert out2.status == "DEFERRED_AUTHOR_STATE_UNKNOWN" and env.platform.outbound_requests == []
    assert env.db.get_secondary_reply_task(tid)["status"] == "APPROVED"
    assert not env.db.check_secondary_reply_idempotency("export/orch", "c_unknown", account_key=TEST_ACCOUNT)
    env.platform.mode = "success"
    assert env.orch.submit(tid).status == "VERIFIED"
    assert len(env.platform.outbound_requests) == 1


def test_fixture_drafts_are_refused_unless_explicitly_allowed(env):
    tid = _approved(env, "c_fx")
    env.orch.allow_fixture_drafts = False
    out = env.orch.submit(tid)
    assert out.status == "REJECTED_BEFORE_INTENT" and "REAL_PROVIDER_UNAVAILABLE" in out.detail
    assert env.platform.outbound_requests == []


# ---------------------------------------------------------------------------
# R6：材料与评论无关/未知来源
# ---------------------------------------------------------------------------

def test_unrelated_or_missing_material_routes_to_manual():
    service = SecondaryReplyService()
    rec = _record("m1")
    related = service.generate_draft(rec, video_context=_material())
    assert related.intent == SecondaryReplyIntent.REPLY and related.evidence_refs == ["fx1"]
    unrelated = service.generate_draft(rec, video_context={"evidence": {"fx1": "完全无关的火星殖民航天器材料"}})
    assert unrelated.intent == SecondaryReplyIntent.MANUAL and unrelated.reason_code == "EVIDENCE_NOT_RELEVANT"
    assert service.generate_draft(rec, video_context={}).intent == SecondaryReplyIntent.MANUAL


def test_unknown_evidence_refs_from_a_provider_are_rejected():
    from video_processing.interaction.secondary_reply_contract import SecondaryReplyContractError

    class _Liar:
        def generate(self, comment, video_context=None, preferred_style=None):
            draft = SecondaryReplyService().provider.generate(comment, _material(), preferred_style)
            import dataclasses
            return dataclasses.replace(draft, evidence_refs=["not_provided_source"])

    with pytest.raises(SecondaryReplyContractError):
        SecondaryReplyService(provider=_Liar()).generate_draft(_record("m2"), video_context=_material())


def test_guard_only_accepts_response_of_the_allowed_request():
    from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplySubmissionGuard
    from video_processing.interaction.secondary_reply_fake_platform import _FakeRequest, _FakeResponse, _SUBMIT_URL

    author = "v2_a@finder"
    payload = {"exportId": "export/g", "rootCommentId": "r1", "replyCommentId": "r1", "content": "正文", "_log_finder_id": author}
    body = {"errCode": 0, "data": {"commentId": "n1", "comment": {
        "commentId": "n1", "commentContent": "正文", "replyCommentId": "r1", "username": author}}}

    def run(response_for_allowed: bool, tweak=None):
        guard = SecondaryReplySubmissionGuard("export/g", "r1", "正文", expected_finder_id=author)
        req = _FakeRequest("POST", _SUBMIT_URL, dict(payload))
        assert guard.capture_request(req)
        b = {"errCode": 0, "data": {"commentId": "n1", "comment": dict(body["data"]["comment"])}}
        if tweak:
            tweak(b)
        guard.capture_response(_FakeResponse(req if response_for_allowed else _FakeRequest("POST", _SUBMIT_URL, dict(payload)), _SUBMIT_URL, 201, b))
        return guard.validate_success_response()

    assert run(True)[:2] == (True, "n1")                      # 合法
    assert run(False)[0] is False                              # 无关回执
    assert run(True, lambda b: b["data"]["comment"].update(username="x@finder"))[2] == "AUTHOR_MISMATCH"
    assert run(True, lambda b: b["data"]["comment"].update(commentContent="正文!"))[2] == "CONTENT_MISMATCH"
    assert run(True, lambda b: b["data"]["comment"].update(replyCommentId="other"))[2] == "PARENT_MISMATCH"
    assert run(True, lambda b: b["data"].update(commentId=""))[0] is False

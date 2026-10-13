"""Codex 独立验收反例的正式回归：账号隔离（认领/对账）与来源评论变化使旧审批失效。

每个拒绝类断言都带相邻合法对照。
"""

from __future__ import annotations

from tests.unit.test_secondary_reply_orchestration import (  # noqa: F401  (fixtures)
    QUESTION,
    _approved,
    _material,
    _no_min_interval,
    _record,
    env,
)
from tests.unit.secondary_reply_support import TEST_ACCOUNT
from video_processing.interaction.secondary_reply_fake_platform import FakeSecondaryReplyPlatform

POST = "export/orch"


# ---------------------------------------------------------------- 账号隔离 ----

def test_other_account_cannot_reconcile_a_task(env):
    tid = _approved(env, "cross_reconcile")
    env.platform.mode = "drop-not-persisted"
    assert env.orch.submit(tid).status == "UNCERTAIN"
    original = env.db.get_secondary_reply_task(tid)
    ledger_before = env.db.check_secondary_reply_idempotency(POST, "cross_reconcile", account_key=TEST_ACCOUNT)

    other = FakeSecondaryReplyPlatform(account_finder_id="other_native_author")
    other.seed_author_reply(original["platform_post_id"], original["comment_id"], original["formatted_reply"])
    good_platform, good_key = env.orch.platform, env.orch.account_key
    env.orch.account_key, env.orch.platform = "other_account", other
    out = env.orch.reconcile(tid)
    assert out.status == "REJECTED_ACCOUNT_MISMATCH"
    after = env.db.get_secondary_reply_task(tid)
    assert after["status"] == "UNCERTAIN" and not after["platform_reply_comment_id"]
    assert env.db.check_secondary_reply_idempotency(POST, "cross_reconcile", account_key=TEST_ACCOUNT) == ledger_before

    # 合法对照：同账号、平台中确有同作者同文回复 -> 对账 VERIFIED
    env.orch.account_key, env.orch.platform = good_key, good_platform
    good_platform.seed_author_reply(original["platform_post_id"], original["comment_id"], original["formatted_reply"])
    assert env.orch.reconcile(tid).status == "VERIFIED"


def test_other_account_cannot_claim_and_fail_a_task(env):
    tid = _approved(env, "cross_claim")
    before = env.db.get_secondary_reply_task(tid)
    good_key = env.orch.account_key
    env.orch.account_key = "other_account"
    out = env.orch.submit(tid)
    assert out.status == "REJECTED_ACCOUNT_MISMATCH"
    after = env.db.get_secondary_reply_task(tid)
    assert after["status"] == "APPROVED"
    assert after["lease_token"] == before["lease_token"] and after["approved_at"] == before["approved_at"]
    assert env.db.check_secondary_reply_idempotency(POST, "cross_claim", account_key=TEST_ACCOUNT) is None
    assert env.platform.outbound_requests == []
    # 合法对照：本账号仍可正常发送同一任务
    env.orch.account_key = good_key
    assert env.orch.submit(tid).status == "VERIFIED"


def test_reconcile_persist_rejection_is_never_reported_verified(env, monkeypatch):
    tid = _approved(env, "persist_reject")
    env.platform.mode = "drop-not-persisted"
    assert env.orch.submit(tid).status == "UNCERTAIN"
    original = env.db.get_secondary_reply_task(tid)
    env.platform.seed_author_reply(original["platform_post_id"], original["comment_id"], original["formatted_reply"])
    monkeypatch.setattr(env.db, "reconcile_secondary_reply_uncertain", lambda *a, **k: False)
    out = env.orch.reconcile(tid)
    assert out.status == "UNCERTAIN" and out.detail == "RECONCILE_PERSIST_REJECTED"
    assert env.db.get_secondary_reply_task(tid)["status"] == "UNCERTAIN"


# -------------------------------------------------------- 来源评论变化 ----

def _collect(env, cid: str, text: str):
    """走正常采集接口（不手改 hash）。"""
    return env.db.save_discovered_audience_comments(
        POST, [{"comment_id": cid, "content": text}], account_key=env.orch.account_key
    )


def test_unchanged_source_passes(env):
    tid = _approved(env, "src_same")
    _collect(env, "src_same", QUESTION)  # 重新采集同一正文：无变化
    assert env.orch.submit(tid).status == "VERIFIED"
    assert len(env.platform.outbound_requests) == 1


def test_changed_source_invalidates_old_approval_with_zero_outbound_then_rereview_passes(env):
    tid = _approved(env, "src_changed")
    _collect(env, "src_changed", "新观察到的评论内容已发生变化")
    out = env.orch.submit(tid)
    assert out.status == "REJECTED_BEFORE_INTENT" and "SOURCE_COMMENT_CHANGED" in out.detail
    assert env.platform.outbound_requests == []
    assert env.db.check_secondary_reply_idempotency(POST, "src_changed", account_key=TEST_ACCOUNT) is None

    # 重审：按新正文重新生成草稿 -> 新审批 -> 合法发送
    new_text = "这种情况出现的原因是什么？"
    (tid2,) = env.orch.ingest_and_draft(
        post_id=POST, comments=[_record("src_changed", new_text)], video_context=_material(new_text)
    )
    cb = env.transport.sent_messages[-1]["inline_keyboard"][0][0]["callback_data"]
    from tests.unit.secondary_reply_support import TEST_APPROVER, TEST_CHAT
    ok, msg = env.orch.approve_via_callback(cb, user_id=TEST_APPROVER, chat_id=TEST_CHAT)
    assert ok, msg
    assert env.orch.submit(tid2).status == "VERIFIED"
    assert len(env.platform.outbound_requests) == 1


def test_recollection_does_not_revive_submitted_or_verified_tasks(env):
    tid = _approved(env, "src_done")
    assert env.orch.submit(tid).status == "VERIFIED"
    ledger = env.db.check_secondary_reply_idempotency(POST, "src_done", account_key=TEST_ACCOUNT)
    _collect(env, "src_done", "采集到被修改后的评论")
    row = env.db.get_secondary_reply_task(tid)
    assert row["status"] == "VERIFIED"
    assert env.db.check_secondary_reply_idempotency(POST, "src_done", account_key=TEST_ACCOUNT) == ledger
    assert env.orch.submit(tid).status == "NOT_CLAIMABLE"
    assert len(env.platform.outbound_requests) == 1

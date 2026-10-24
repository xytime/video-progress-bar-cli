"""按需保活的时钟、代际和准入边界测试。"""
from types import SimpleNamespace

import pytest

from video_processing.core.wechat_keepalive_schedule import demand_plan, failure_delay
from video_processing.core.wechat_auth_state import (
    record_wechat_authorization, read_wechat_auth_state,
    record_wechat_verified_evidence, record_wechat_keepalive_attempt,
    record_wechat_keepalive_result, evaluate_wechat_session_status,
)
from video_processing.core import wechat_session_lock as locks

NOW = 1792880000.0


def credential(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("{}")
    return state, record_wechat_authorization(state, method="scan_qr", timestamp=NOW)


def test_idle_24h_is_twelve_attempts_and_business_activity_defers():
    auth = {"last_verified_at": NOW}
    attempts = []
    for minute in range(1, 1441):
        now = NOW + minute * 60
        plan = demand_plan(auth, now)
        if plan["due"]:
            attempts.append(now)
            auth["last_verified_at"] = now
    assert len(attempts) == 12
    # 业务每 90 分钟已有真实认证，不需要额外保活。
    auth = {"last_verified_at": NOW}
    for minute in range(1, 1441):
        now = NOW + minute * 60
        if minute % 90 == 0:
            auth["last_verified_at"] = now
        assert not demand_plan(auth, now)["due"]


def test_restart_preserves_failure_backoff_and_success_clears_it(tmp_path):
    state, auth = credential(tmp_path)
    for index in range(1, 7):
        attempted = NOW + index * 10000
        record_wechat_keepalive_attempt(state, timestamp=attempted)
        restored = read_wechat_auth_state(state)
        assert restored["keepalive_retry_at"] == attempted + failure_delay(index)
        assert not demand_plan(restored, attempted + 60)["due"]
    record_wechat_keepalive_result(state, status="SUCCESS", timestamp=attempted + 120,
                                   expected_generation=auth["credential_generation"])
    restored = read_wechat_auth_state(state)
    assert restored["keepalive_failure_count"] == 0
    assert restored["keepalive_retry_at"] is None
    assert demand_plan(restored, attempted + 121)["at"] == attempted + 120 + 7200


def test_business_success_preserves_authorization_and_keepalive_history(tmp_path):
    state, auth = credential(tmp_path)
    record_wechat_keepalive_result(state, status="NETWORK_TIMEOUT", timestamp=NOW + 60)
    assert record_wechat_verified_evidence(state, source="publish_controls",
        expected_generation=auth["credential_generation"], timestamp=NOW + 120)
    restored = read_wechat_auth_state(state)
    assert restored["authorized_at"] == NOW
    assert restored["last_keepalive_status"] == "NETWORK_TIMEOUT"
    assert restored["last_keepalive_at"] == NOW + 60
    assert restored["last_verified_at"] == NOW + 120
    assert not demand_plan(restored, NOW + 7200)["due"]


def test_old_generation_cannot_mark_success_or_failure(tmp_path):
    state, old = credential(tmp_path)
    current = record_wechat_authorization(state, method="scan_qr", timestamp=NOW + 120)
    assert not record_wechat_verified_evidence(state, source="comment_controls",
        expected_generation=old["credential_generation"], timestamp=NOW + 180)
    for status in ("SUCCESS", "LOGIN_REQUIRED"):
        record_wechat_keepalive_result(state, status=status, timestamp=NOW + 180,
                                       expected_generation=old["credential_generation"])
    assert read_wechat_auth_state(state)["last_verified_at"] == current["last_verified_at"]


@pytest.mark.parametrize("allowed,until,code,reason", [
    (False, NOW + 86400, "OPERATION_ROLLING_24H_LIMIT", "BUDGET_WAIT"),
    (False, NOW + 1800, "PLATFORM_BACKOFF", "ACCOUNT_WAIT"),
    (False, None, "AUTH_REQUIRED", "ACCOUNT_WAIT"),
])
def test_admission_wait_is_never_browser_lock(allowed, until, code, reason):
    plan = demand_plan({}, NOW, admission={"allowed": allowed, "until": until,
                                          "blockers": [{"code": code}]})
    assert not plan["due"]
    assert plan["reason"] == reason
    assert plan["at"] == (until or NOW + 300)


def test_uncontrolled_or_limited_sessions_cannot_refresh_auth(tmp_path):
    state, auth = credential(tmp_path)
    assert not locks.record_current_wechat_verified("comment_controls")
    session = SimpleNamespace(purpose="评论", state_path=state, _request_started=True,
                              _request_limited=True, _credential_generation=auth["credential_generation"])
    token = locks._SESSION.set(session)
    try:
        assert not locks.record_current_wechat_verified("comment_controls")
        session._request_limited = False
        assert not locks.record_current_wechat_verified("http_200")
    finally:
        locks._SESSION.reset(token)
    assert read_wechat_auth_state(state)["last_verified_at"] == NOW


def test_stale_warning_survives_budget_wait():
    status = evaluate_wechat_session_status({"last_verified_at": NOW, "defer_reason": "BUDGET_WAIT"},
                                           state_file_exists=True, now_ts=NOW + 18000)
    assert "验证已陈旧" in status["status_label"]
    assert status["keepalive_wait_label"] == "保活额度等待"

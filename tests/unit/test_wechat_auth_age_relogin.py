"""视频号按授权时长自动快捷重登与授权告警回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Grok Bot | 覆盖与闲置保活解耦的授权时长重登、失败退避/上限、账户调度下单次登录许可及去重告警。 |
"""

import time
from unittest.mock import MagicMock, patch

import pytest

import web.app as web_app
from video_processing.core.wechat_auto_relogin import (
    login_required, pending_alerts, relogin_failure_alert, relogin_plan,
)

HOUR = 3600.0
NOW = 1_800_000_000.0


def _auth(age_hours, **extra):
    row = {"authorized_at": NOW - age_hours * HOUR, "credential_generation": "gen-a",
           "last_verified_at": NOW - age_hours * HOUR, "relogin_failure_count": 0,
           "next_relogin_allowed_at": None}
    row.update(extra)
    return row


def _plan(auth):
    return relogin_plan(auth, NOW, after_hours=20.0, max_failures=3)


def test_fresh_authorization_is_not_due():
    assert _plan(_auth(19.9)) == {"age_hours": pytest.approx(19.9), "expired": False,
                                  "due": False, "reason": "FRESH"}


def test_business_verification_refresh_does_not_postpone_relogin():
    """回归：评论/发布会话每分钟刷新 last_verified_at，旧闲置保活永不到期；授权时长仍须触发。"""
    plan = _plan(_auth(20.5, last_verified_at=NOW - 30))
    assert plan["due"] is True and plan["reason"] == "PRE_EXPIRY"


def test_expired_session_is_due_and_flagged():
    auth = _auth(24.1, last_verified_at=NOW - 2 * HOUR,
                 last_keepalive_status="LOGIN_REQUIRED", last_keepalive_at=NOW - HOUR)
    assert login_required(auth) is True
    plan = _plan(auth)
    assert plan["due"] is True and plan["expired"] is True and plan["reason"] == "EXPIRED"


def test_new_authorization_clears_login_required():
    auth = _auth(0.1, last_keepalive_status="LOGIN_REQUIRED", last_keepalive_at=NOW - HOUR)
    assert login_required(auth) is False
    assert _plan(auth)["due"] is False


def test_failure_backoff_and_cap_stop_repeated_logins():
    backoff = _plan(_auth(21, relogin_failure_count=1, next_relogin_allowed_at=NOW + 600))
    assert backoff["due"] is False and backoff["reason"] == "FAILURE_BACKOFF"
    assert _plan(_auth(21, relogin_failure_count=1, next_relogin_allowed_at=NOW - 1))["due"] is True
    capped = _plan(_auth(23, relogin_failure_count=3, next_relogin_allowed_at=NOW - 1))
    assert capped["due"] is False and capped["reason"] == "FAILURE_CAP"


def test_never_authorized_never_auto_logs_in():
    assert relogin_plan({}, NOW, after_hours=20, max_failures=3)["due"] is False
    assert pending_alerts({}, NOW, alert_hours=21, auto_enabled=True, max_failures=3) == []


def test_alerts_follow_authorization_age_and_generation():
    assert pending_alerts(_auth(10), NOW, alert_hours=21, auto_enabled=True, max_failures=3) == []
    [(kind, key, text)] = pending_alerts(_auth(21.5, last_verified_at=NOW - 5), NOW,
                                         alert_hours=21, auto_enabled=True, max_failures=3)
    assert kind == "WECHAT_SESSION_EXPIRING" and key == "expiring:gen-a"
    assert "21.5h" in text
    expired = _auth(24.2, last_keepalive_status="LOGIN_REQUIRED", last_keepalive_at=NOW - 60)
    [(kind, key, text)] = pending_alerts(expired, NOW, alert_hours=21, auto_enabled=False, max_failures=3)
    assert kind == "WECHAT_LOGIN_REQUIRED" and key == "login-required:gen-a"
    assert "/wechat_login" in text


def test_failure_alert_reports_retry_or_cap():
    kind, key, text = relogin_failure_alert(
        {"relogin_failure_count": 1, "next_relogin_allowed_at": NOW + 1800,
         "last_auth_attempt_reason": "PAGE_UNREADY"}, started_at=NOW, returncode=1, max_failures=3)
    assert kind == "WECHAT_AUTO_RELOGIN_FAILED" and key == f"auto-relogin-failed:{NOW:.0f}"
    assert "第 2/3 次" in text and "PAGE_UNREADY" in text
    _, _, capped = relogin_failure_alert({"relogin_failure_count": 3}, started_at=NOW, returncode=1, max_failures=3)
    assert "上限" in capped


def _prepare_project(tmp_path, monkeypatch, *, auto=True):
    fake_app = tmp_path / "src" / "web" / "app.py"
    fake_app.parent.mkdir(parents=True)
    output = tmp_path / "output"
    output.mkdir()
    (output / "wechat_state.json").write_text("{}")
    monkeypatch.setattr(web_app, "__file__", str(fake_app))
    # 账户许可/退避文件按 settings.default_output_dir 定位；隔离到本用例临时目录。
    monkeypatch.setattr(type(web_app.settings), "default_output_dir", property(lambda _: output))
    monkeypatch.setattr(web_app.settings, "wechat_scheduler_priority_video", "")
    monkeypatch.setattr(web_app.settings, "wechat_account_scheduler_enabled", True)
    monkeypatch.setattr(web_app.settings, "wechat_auto_relogin_enabled", auto)
    monkeypatch.setattr(web_app.settings, "wechat_keepalive_enabled", True)
    monkeypatch.setattr(web_app, "_restore_login_required_after_wechat_login", MagicMock())
    monkeypatch.setattr(web_app, "_resume_eligible_english_world_after_wechat_login", MagicMock())
    monkeypatch.setattr(web_app, "_is_wechat_login_running", lambda: False)
    monkeypatch.setattr(web_app, "_WECHAT_AUTH_ALERT_MEMO", {})
    return output


def _join_login_thread():
    if web_app._wechat_login_thread:
        web_app._wechat_login_thread.join(timeout=5.0)


def test_automatic_login_runs_under_account_scheduler_with_single_use_permit(tmp_path, monkeypatch):
    output = _prepare_project(tmp_path, monkeypatch)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return MagicMock(returncode=11)

    with patch("subprocess.run", side_effect=fake_run):
        res = web_app._start_wechat_login_flow(headless=True, preserve_marker=True,
                                               reason="automatic expired-session relogin")
        _join_login_thread()
    assert res["success"] is True and not res.get("deferred")
    assert calls and "--login-only" in calls[0] and "--manual-login-token" in calls[0]
    # 单次许可十五分钟内不重复签发，自动重登不会每分钟反复打开后台。
    again = web_app._start_wechat_login_flow(headless=True, preserve_marker=True,
                                             reason="automatic expired-session relogin")
    assert again.get("deferred") is True
    assert not (output / "wechat_auto_relogin_started.flag").exists()


def test_automatic_login_refused_when_switch_off(tmp_path, monkeypatch):
    _prepare_project(tmp_path, monkeypatch, auto=False)
    with patch("subprocess.run") as run:
        res = web_app._start_wechat_login_flow(preserve_marker=True, reason="automatic pre-expiry relogin")
    assert res.get("deferred") is True and not run.called


@pytest.mark.parametrize("code, alerted", [(1, True), (2, True), (17, False), (11, False)])
def test_automatic_login_failure_alerts_once_per_real_attempt(tmp_path, monkeypatch, code, alerted):
    output = _prepare_project(tmp_path, monkeypatch)
    from video_processing.core.wechat_auth_state import record_wechat_authorization
    record_wechat_authorization(output / "wechat_state.json", method="desktop_quick", timestamp=time.time() - 21 * HOUR)
    sent = []
    monkeypatch.setattr(web_app, "_send_wechat_auth_alert", lambda *a: sent.append(a) or "ACCEPTED")
    with patch("subprocess.run", return_value=MagicMock(returncode=code)):
        web_app._start_wechat_login_flow(preserve_marker=True, reason="automatic pre-expiry relogin")
        _join_login_thread()
    assert [s[0] for s in sent] == (["WECHAT_AUTO_RELOGIN_FAILED"] if alerted else [])


def _tick_state(output, monkeypatch, *, expired=True):
    from video_processing.core.wechat_auth_state import record_wechat_authorization, record_wechat_keepalive_result
    state = output / "wechat_state.json"
    record_wechat_authorization(state, method="desktop_quick", timestamp=time.time() - 25 * HOUR)
    if expired:
        record_wechat_keepalive_result(state, status="LOGIN_REQUIRED")
    return state


def test_tick_starts_one_automatic_login_for_expired_session(tmp_path, monkeypatch):
    output = _prepare_project(tmp_path, monkeypatch)
    state = _tick_state(output, monkeypatch)
    sent, started = [], []
    monkeypatch.setattr(web_app, "_send_wechat_auth_alert", lambda *a: sent.append(a[0]) or "ACCEPTED")
    monkeypatch.setattr(web_app, "_start_wechat_login_flow",
                        lambda **kw: started.append(kw) or {"success": True})
    monkeypatch.setattr("video_processing.core.wechat_request_guard.WeChatRequestGuard.evaluate",
                        lambda self, *a, **k: {"allowed": True, "blockers": []})
    assert web_app._wechat_auth_lifecycle_tick(str(state), MagicMock()) is True
    assert sent == ["WECHAT_LOGIN_REQUIRED"]
    assert len(started) == 1 and started[0]["reason"] == "automatic expired-session relogin"
    assert started[0]["preserve_marker"] is True


def test_tick_only_alerts_when_auto_relogin_disabled(tmp_path, monkeypatch):
    output = _prepare_project(tmp_path, monkeypatch, auto=False)
    state = _tick_state(output, monkeypatch)
    sent = []
    monkeypatch.setattr(web_app, "_send_wechat_auth_alert", lambda *a: sent.append(a[0]) or "ACCEPTED")
    monkeypatch.setattr(web_app, "_start_wechat_login_flow", MagicMock(side_effect=AssertionError))
    assert web_app._wechat_auth_lifecycle_tick(str(state), MagicMock()) is False
    assert sent == ["WECHAT_LOGIN_REQUIRED"]


def test_tick_waits_while_browser_session_busy(tmp_path, monkeypatch):
    output = _prepare_project(tmp_path, monkeypatch)
    state = _tick_state(output, monkeypatch)
    monkeypatch.setattr(web_app, "_send_wechat_auth_alert", lambda *a: "ACCEPTED")
    monkeypatch.setattr(web_app, "_start_wechat_login_flow", MagicMock(side_effect=AssertionError))
    from types import SimpleNamespace
    monkeypatch.setattr("video_processing.core.wechat_session_lock.inspect_wechat_session_lock",
                        lambda path: SimpleNamespace(locked=True))
    assert web_app._wechat_auth_lifecycle_tick(str(state), MagicMock()) is True


def test_alert_sender_dedupes_within_process(monkeypatch):
    monkeypatch.setattr(web_app, "_WECHAT_AUTH_ALERT_MEMO", {})
    calls = []
    from types import SimpleNamespace

    def fake_send(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(state="ACCEPTED")

    monkeypatch.setattr("video_processing.telegram_delivery.send_text", fake_send)
    assert web_app._send_wechat_auth_alert("WECHAT_LOGIN_REQUIRED", "login-required:g", "x") == "ACCEPTED"
    assert web_app._send_wechat_auth_alert("WECHAT_LOGIN_REQUIRED", "login-required:g", "x") == "MEMO_SUPPRESSED"
    assert len(calls) == 1 and calls[0]["dedupe_key"] == "login-required:g" and calls[0]["cooldown_seconds"] >= 86400

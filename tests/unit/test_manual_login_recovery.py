"""人工登录许可的账户边界；全部离线执行。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Codex | 验证单次、用途绑定、过期与遇限流即停。 |
"""
import pytest
from video_processing.core import wechat_request_guard as module
from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
from video_processing.core.wechat_session_lock import WeChatSessionLock, WeChatOverrideInvalid

@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(type(module.settings), "default_output_dir", property(lambda _: tmp_path))
    monkeypatch.setattr(module.settings, "wechat_account_scheduler_enabled", True)
    state = tmp_path / "state.json"
    guard = WeChatRequestGuard(state)
    guard.record_limited(endpoint="/test")
    return state, guard


def test_manual_login_one_use_keeps_cooldown_and_stops_on_new_limit(account):
    state, guard = account
    old_until = guard.snapshot()["blocked_until"]
    token = guard.issue_manual_login()
    with pytest.raises(WeChatRequestDeferred):
        guard.issue_manual_login()
    with WeChatSessionLock(state, purpose="登录", manual_login_token=token) as session:
        g = session.request_guard
        g.start_session("登录")
        g.check()
        assert g.snapshot()["blocked_until"] == old_until
        with pytest.raises(WeChatRequestDeferred):
            WeChatRequestGuard(state).check()
        g.record_limited(endpoint="/test")
        with pytest.raises(WeChatRequestDeferred):
            g.check()
    with pytest.raises(WeChatOverrideInvalid):
        with WeChatSessionLock(state, purpose="登录", manual_login_token=token):
            pass


def test_login_grant_cannot_publish(account):
    state, guard = account
    token = guard.issue_manual_login()
    with pytest.raises(WeChatOverrideInvalid):
        with WeChatSessionLock(state, purpose="发布", manual_login_token=token):
            pass


def test_expired_login_grant_denied(account, monkeypatch):
    state, guard = account
    now = module.time.time()
    token = guard.issue_manual_login()
    monkeypatch.setattr(module.time, "time", lambda: now + 901)
    with pytest.raises(WeChatOverrideInvalid):
        with WeChatSessionLock(state, purpose="登录", manual_login_token=token):
            pass

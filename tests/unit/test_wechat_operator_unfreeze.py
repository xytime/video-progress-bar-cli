"""人工确认解冻只解除旧冻结，保留互斥之外的调度与原生限流保护。"""
import pytest
from video_processing.core import wechat_request_guard as module
from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred


def test_operator_unfreeze_retains_history_spacing_and_new_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(type(module.settings), "default_output_dir", property(lambda _: tmp_path))
    monkeypatch.setattr(module.settings, "wechat_account_scheduler_enabled", True)
    guard = WeChatRequestGuard(tmp_path / "wechat_state.json")
    guard.record_limited(endpoint="/test")
    old = guard.cooldown()
    with guard._locked():
        row = guard._read()
        row["schedule"] = {"sessions": [{"at": module.time.time()-3600, "task": "manual-login", "purpose": "登录"}], "queue": [], "publications": {}, "submit_intents": {"already-sent": 1}}
        guard._save(row, {"event": "FIXTURE"})
    guard.acknowledge_unfrozen(old["version"])
    guard.check()
    assert guard.snapshot()["last_limited_at"] > 0
    with pytest.raises(WeChatRequestDeferred):
        guard.admission("发布", "already-sent")
    guard.admission("发布", "ready")
    guard.start_session("发布")
    with pytest.raises(WeChatRequestDeferred):
        WeChatRequestGuard(tmp_path / "wechat_state.json").check()
    with pytest.raises(WeChatRequestDeferred):
        guard.acknowledge_unfrozen(old["version"])
    guard.record_limited(endpoint="/test")
    assert "recovery_started" not in guard.snapshot()["schedule"]
    with pytest.raises(WeChatRequestDeferred):
        guard.check()


def test_unfreeze_keeps_recent_login_interval_and_rejects_stale_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(type(module.settings), "default_output_dir", property(lambda _: tmp_path))
    monkeypatch.setattr(module.settings, "wechat_account_scheduler_enabled", True)
    guard = WeChatRequestGuard(tmp_path / "wechat_state.json")
    guard.record_limited(endpoint="/test")
    with guard._locked():
        row = guard._read()
        row["last_session_at"] = module.time.time()
        guard._save(row, {"event": "FIXTURE"})
    old = guard.cooldown()["version"]
    guard.acknowledge_unfrozen(old)
    with pytest.raises(WeChatRequestDeferred):
        guard.check()
    guard.record_limited(endpoint="/test-new-limit")
    state = guard.snapshot()
    with pytest.raises(WeChatRequestDeferred):
        guard.acknowledge_unfrozen(old)
    assert guard.snapshot() == state

"""验证跨作品请求退避、首次页面响应捕获与半开探测，禁止联网。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 真文件、跨进程锁及响应事件验证共享退避不被无效调用延长。 |
"""
import json
import multiprocessing
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_processing.core import wechat_request_guard as requests
from video_processing.core.wechat_browser_context import create_wechat_context
from video_processing.core.wechat_session_lock import WeChatSessionLock, WeChatSessionLockBusy

API = "https://channels.weixin.qq.com/micro/interaction/cgi-bin/mmfinderassistant-bin/post/post_list"


def response(payload, *, url=API, status=201):
    return SimpleNamespace(url=url, status=status, json=lambda: payload)


class Context:
    def __init__(self):
        self.listeners = {}

    def on(self, event, callback):
        self.listeners[event] = callback

    def add_init_script(self, _script):
        pass


def _child_acquire(state, result):
    try:
        with WeChatSessionLock(state, purpose="保活"):
            result.put("OPEN")
    except WeChatSessionLockBusy:
        result.put("DEFERRED")


def test_first_context_response_blocks_other_process_and_does_not_extend(tmp_path):
    state = tmp_path / "state.json"
    browser = SimpleNamespace(new_context=lambda **_: Context())
    with WeChatSessionLock(state, purpose="发布"):
        context = create_wechat_context(browser, storage_state=state)
        context.listeners["response"](response({"errCode": 0, "data": {"baseResp": {"errcode": -360}, "list": []}}))
        assert context._wechat_rate_limit_seen is True
        with pytest.raises(WeChatSessionLockBusy):
            create_wechat_context(browser)
    guard = requests.WeChatRequestGuard(state)
    original = guard.path.read_text()
    spawn = multiprocessing.get_context("spawn")
    result = spawn.Queue()
    child = spawn.Process(target=_child_acquire, args=(str(state), result))
    child.start()
    assert result.get(timeout=10) == "DEFERRED"
    child.join(10)
    assert child.exitcode == 0
    for _ in range(10):
        with pytest.raises(WeChatSessionLockBusy):
            WeChatSessionLock(state, purpose="发布").acquire()
    assert guard.path.read_text() == original


def test_session_interval_applies_across_jobs_but_not_same_operation_contexts(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(requests.time, "time", lambda: clock[0])
    state = tmp_path / "state.json"
    browser = SimpleNamespace(new_context=lambda **_: Context())
    # 单纯判锁不消耗请求间隔，正式投稿前的锁预检不会饿死子进程。
    with WeChatSessionLock(state):
        pass
    with WeChatSessionLock(state):
        create_wechat_context(browser, storage_state=state)
        create_wechat_context(browser, storage_state=None)
    with pytest.raises(WeChatSessionLockBusy):
        WeChatSessionLock(state).acquire()
    clock[0] += requests.settings.wechat_request_min_interval_seconds + 1
    with WeChatSessionLock(state):
        create_wechat_context(browser, storage_state=state)


def test_reusing_lock_object_still_reserves_a_new_session(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(requests.time, "time", lambda: clock[0])
    state = tmp_path / "state.json"
    browser = SimpleNamespace(new_context=lambda **_: Context())
    lock = WeChatSessionLock(state)
    with lock:
        create_wechat_context(browser)
    clock[0] += requests.settings.wechat_request_min_interval_seconds + 1
    with lock:
        create_wechat_context(browser)
    with pytest.raises(WeChatSessionLockBusy):
        WeChatSessionLock(state).acquire()


def test_repeated_rate_limit_increases_backoff_until_valid_native_recovery(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(requests.time, "time", lambda: clock[0])
    guard = requests.WeChatRequestGuard(tmp_path / "state.json")
    limited = response({"data": {"baseResp": {"errcode": -360}}})
    assert guard.observe_response(limited)
    first = guard.snapshot()
    clock[0] += 10
    guard.observe_response(limited)
    assert guard.snapshot() == first
    clock[0] = first["blocked_until"] + 1
    guard.observe_response(limited)
    second = guard.snapshot()
    assert second["blocked_until"] - clock[0] == 2 * requests.settings.wechat_rate_limit_cooldown_seconds
    clock[0] = second["blocked_until"] + 1
    guard.observe_response(response({"errCode": 0, "data": {"list": []}}))
    assert guard.snapshot()["failure_streak"] == 2
    guard.observe_response(response({"errCode": 0, "data": {"baseResp": {"errcode": 0}, "list": []}}))
    assert guard.snapshot()["failure_streak"] == 0


def test_foreign_response_cannot_block_or_write_secrets(tmp_path):
    guard = requests.WeChatRequestGuard(tmp_path / "state.json")
    limited = {"errCode": 0, "data": {"baseResp": {"errcode": -360}, "private": "BODY_SECRET"}}
    assert not guard.observe_response(response(limited, url=API.replace("channels.weixin.qq.com", "channels.weixin.qq.com.evil.test")))
    assert not guard.path.exists()
    assert guard.observe_response(response(limited, url=API + "?token=QUERY_SECRET"))
    persisted = guard.path.read_text() + guard.audit_path.read_text()
    assert "QUERY_SECRET" not in persisted and "BODY_SECRET" not in persisted


def test_corrupt_state_is_fail_closed_and_http_429_is_shared(tmp_path):
    guard = requests.WeChatRequestGuard(tmp_path / "state.json")
    assert guard.observe_response(response({}, status=429))
    assert guard.snapshot()["business_code"] == 429
    guard.path.write_text(json.dumps({"blocked_until": "invalid"}))
    with pytest.raises(requests.WeChatRequestDeferred):
        guard.check()


@pytest.mark.parametrize("payload", [{}, {"errCode": False}, {"data": {"baseResp": {"errcode": "-360"}}}])
def test_only_real_numeric_business_error_is_a_limit(payload):
    assert not requests.business_rate_limited(payload)


def test_real_cli_session_deferral_creates_no_false_browser_evidence(tmp_path):
    state = tmp_path / "state.json"
    evidence = tmp_path / "evidence"
    script = Path(__file__).resolve().parents[2] / "scripts/wechat_uploader.py"
    with WeChatSessionLock(state):
        result = subprocess.run([sys.executable, str(script), "--state", str(state),
            "--video", str(tmp_path / "not-opened.mp4"), "--copy", str(tmp_path / "not-opened.txt"),
            "--evidence-dir", str(evidence)], text=True, capture_output=True, timeout=15)
    assert result.returncode == 11, result.stderr
    assert not evidence.exists()


@pytest.fixture(autouse=True)
def legacy_guard_mode(monkeypatch):
    """旧退避/人工凭据契约单独验证；新默认调度由 account_schedule 测试覆盖。"""
    from config.settings import settings
    monkeypatch.setattr(settings, "wechat_account_scheduler_enabled", False)
    monkeypatch.setenv("WECHAT_ACCOUNT_SCHEDULER_ENABLED", "false")

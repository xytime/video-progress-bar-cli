"""账户解冻前的离线回归：不访问真实平台。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from config.settings import settings
from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
from video_processing.core.wechat_session_lock import WeChatSessionLock, canonical_wechat_session_lock_path, guard_wechat_context


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'wechat_account_scheduler_enabled', True)
    monkeypatch.setattr(settings, 'wechat_scheduler_priority_video', '')
    monkeypatch.setattr(settings, 'wechat_scheduler_recovery_limit', 1)
    monkeypatch.setattr(type(settings), 'default_output_dir', property(lambda _: tmp_path))
    return tmp_path / 'wechat_state.json'


def test_copied_login_state_cannot_escape_account_cooldown_or_lock(account):
    guard = WeChatRequestGuard(account)
    guard.record_limited(endpoint='/post/post_list')
    alternate = account.parent / 'copied-state.json'
    assert canonical_wechat_session_lock_path(alternate) == canonical_wechat_session_lock_path(account)
    before = guard.snapshot()
    for _ in range(30):
        with pytest.raises(WeChatRequestDeferred):
            WeChatRequestGuard(alternate).check()
    assert guard.snapshot() == before


def test_recovery_one_session_survives_restart_and_all_other_purposes(account, monkeypatch):
    from video_processing.core import wechat_request_guard as module
    now = [1000000.0]
    monkeypatch.setattr(module.time, 'time', lambda: now[0])
    guard = WeChatRequestGuard(account)
    guard.record_limited(endpoint='/post/post_list')
    now[0] = guard.snapshot()['blocked_until'] + 1
    guard.admission('发布', 'first')
    guard.start_session('发布')
    now[0] += 3601
    for purpose in ['发布', '登录', '评论', '回复']:
        with pytest.raises(WeChatRequestDeferred, match='额度|恢复期'):
            WeChatRequestGuard(account.parent / 'copy.json').admission(purpose, 'second')
    assert len(guard.snapshot()['schedule']['sessions']) == 1


def test_automatic_login_requires_switch_and_single_use_permit(account, monkeypatch, tmp_path):
    """2026-11-02 起账户调度下也允许按授权时长自动快捷重登，但必须显式开关并走单次登录许可。"""
    from unittest.mock import MagicMock, patch
    import web.app as app
    fake_app = tmp_path / 'project' / 'src' / 'web' / 'app.py'
    fake_app.parent.mkdir(parents=True)
    (tmp_path / 'project' / 'output').mkdir()
    monkeypatch.setattr(app, '__file__', str(fake_app))
    monkeypatch.setattr(app, '_is_wechat_login_running', lambda: False)
    monkeypatch.setattr(app.settings, 'wechat_keepalive_enabled', True)
    monkeypatch.setattr(app.settings, 'wechat_auto_relogin_enabled', False)
    marker = tmp_path / 'project' / 'output' / 'wechat_login_at.txt'
    marker.write_text('old')
    assert app._wechat_session_needs_auto_relogin() is False
    with patch('subprocess.run') as run:
        result = app._start_wechat_login_flow(reason='automatic pre-expiry relogin')
    assert result['deferred'] and not result['success'] and not run.called
    monkeypatch.setattr(app.settings, 'wechat_auto_relogin_enabled', True)
    with patch('subprocess.run', return_value=MagicMock(returncode=11)) as run:
        result = app._start_wechat_login_flow(reason='automatic pre-expiry relogin')
        if app._wechat_login_thread:
            app._wechat_login_thread.join(timeout=5)
        assert result['success'] and not result.get('deferred')
        assert '--manual-login-token' in run.call_args[0][0]
        again = app._start_wechat_login_flow(reason='automatic pre-expiry relogin')
    assert again['deferred'] and run.call_count == 1
    assert marker.read_text() == 'old'


def test_context_rejects_requests_after_limit_and_bounds_list_requests(account):
    handlers = {}
    class Context:
        def on(self, name, fn):
            handlers[name] = fn
        def route(self, pattern, fn):
            handlers['route'] = fn
    calls = []
    route = SimpleNamespace(request=SimpleNamespace(url='https://channels.weixin.qq.com/micro/cgi-bin/mmfinderassistant-bin/post/post_list'),
                            abort=lambda: calls.append('abort'), continue_=lambda: calls.append('send'))
    with WeChatSessionLock(account, purpose='发布', video='one') as session:
        session.request_guard.admission('发布', 'one')
        guard_wechat_context(Context())
        for _ in range(3):
            handlers['route'](route)
        assert calls == ['send', 'send', 'abort']
        session._request_limited = True
        route.request.url = 'https://channels.weixin.qq.com/micro/cgi-bin/mmfinderassistant-bin/comment/create_comment'
        handlers['route'](route)
        assert calls[-1] == 'abort'

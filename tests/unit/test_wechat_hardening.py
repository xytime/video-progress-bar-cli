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


def test_automatic_login_has_no_child_or_marker_mutation(account, monkeypatch):
    import web.app as app
    monkeypatch.setattr(app.settings, 'wechat_keepalive_enabled', True)
    monkeypatch.setattr(app.settings, 'wechat_auto_relogin_enabled', True)
    marker = account.parent / 'wechat_login_at.txt'
    marker.write_text('old')
    assert app._wechat_session_needs_auto_relogin() is False
    result = app._start_wechat_login_flow(reason='automatic pre-expiry relogin')
    assert result['deferred'] and not result['success']
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

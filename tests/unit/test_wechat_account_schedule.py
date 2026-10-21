"""账户降频的离线验收，不启动浏览器或访问平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 模拟时钟验证优先、总量、重启、旧查询关闭和防重发。 |
"""
import json
import pytest
from video_processing.core import wechat_request_guard as module
from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
from video_processing.core.wechat_account_schedule import admission


@pytest.fixture
def clock(monkeypatch, tmp_path):
    monkeypatch.setattr(type(module.settings), "default_output_dir", property(lambda _: tmp_path))
    now = [1000000.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    monkeypatch.setattr(module.settings, "wechat_account_scheduler_enabled", True)
    monkeypatch.setattr(module.settings, "wechat_scheduler_priority_video", "")
    return now


def start(path, task, purpose="发布"):
    guard = WeChatRequestGuard(path)
    guard.admission(purpose, task, "test")
    guard.start_session(purpose)
    return guard


def test_old_205_queries_cancelled_without_queue(tmp_path, clock):
    path = tmp_path / 'state.json'
    for i in range(205):
        with pytest.raises(WeChatRequestDeferred, match="旧作品"):
            start(path, str(i % 9), "状态核对")
    row = WeChatRequestGuard(path).snapshot()
    assert row['schedule']['sessions'] == []
    assert row['schedule']['queue'] == []


def test_priority_survives_failure_restart_and_cold_rejections(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(module.settings, "wechat_scheduler_priority_video", "enhanced")
    path = tmp_path / 'state.json'
    guard = WeChatRequestGuard(path)
    guard.record_limited(endpoint='/post/post_list')
    until = guard.snapshot()['blocked_until']
    for _ in range(10):
        with pytest.raises(WeChatRequestDeferred):
            start(path, 'other')
    assert guard.snapshot()['blocked_until'] == until
    clock[0] = until + 1
    with pytest.raises(WeChatRequestDeferred, match="首次访问"):
        start(path, 'other')
    guard = start(path, 'enhanced')
    guard.record_limited(endpoint='/post/post_list')
    assert guard.snapshot()['blocked_until'] >= clock[0] + 86400
    clock[0] = guard.snapshot()['blocked_until'] + 1
    with pytest.raises(WeChatRequestDeferred, match="首次访问"):
        start(path, 'other')
    start(path, 'enhanced')


def test_recovery_six_sessions_global_and_restart(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(module.settings, "wechat_scheduler_recovery_limit", 6)
    path = tmp_path / 'state.json'
    guard = WeChatRequestGuard(path)
    guard.record_limited(endpoint='/post/post_list')
    clock[0] = guard.snapshot()['blocked_until'] + 1
    for i in range(6):
        start(path, f'task{i}')
        clock[0] += 3600
    with pytest.raises(WeChatRequestDeferred, match="额度"):
        start(path, 'seventh')
    assert len(WeChatRequestGuard(path).snapshot()['schedule']['sessions']) == 6


def test_stable_twenty_and_minimum_interval(tmp_path, clock):
    path = tmp_path / 'state.json'
    for i in range(20):
        start(path, f'task{i}')
        with pytest.raises(WeChatRequestDeferred):
            start(path, 'racer')
        clock[0] += 900
    with pytest.raises(WeChatRequestDeferred, match="额度"):
        start(path, 'twentyfirst')


def test_receipt_binding_and_three_bounded_checks_no_resend(tmp_path, clock):
    path = tmp_path / 'state.json'
    submitted = clock[0]
    guard = start(path, 'video')
    guard.mark_submit_intent()
    guard.bind_publication('native')
    clock[0] += 900
    with pytest.raises(WeChatRequestDeferred, match="禁止再次上传"):
        start(path, 'video')
    with pytest.raises(WeChatRequestDeferred, match="尚未到"):
        start(path, 'native', '状态核对')
    for offset in (3600, 21600, 86400):
        clock[0] = submitted + offset
        start(path, 'native', '状态核对')
    clock[0] += 900
    with pytest.raises(WeChatRequestDeferred):
        start(path, 'native', '状态核对')
    assert WeChatRequestGuard(path).snapshot()['schedule']['publications']['native']['checks'] == 3


def test_pending_intent_alone_blocks_resend(tmp_path, clock):
    path = tmp_path / 'state.json'
    start(path, 'video').mark_submit_intent()
    clock[0] += 900
    with pytest.raises(WeChatRequestDeferred, match="禁止再次上传"):
        start(path, 'video')


def test_comment_reply_share_interval_and_keepalive_off(tmp_path, clock):
    path = tmp_path / 'state.json'
    start(path, 'post1', '评论')
    clock[0] += 3600
    with pytest.raises(WeChatRequestDeferred, match="六小时"):
        start(path, 'post2', '回复')
    with pytest.raises(WeChatRequestDeferred, match="保活已停用"):
        start(path, 'idle', '保活')


def test_queue_order_persisted_before_consumption(tmp_path, clock):
    path = tmp_path / 'state.json'
    first = WeChatRequestGuard(path)
    first.admission('发布', 'first')
    with pytest.raises(WeChatRequestDeferred, match='排队'):
        start(path, 'second')
    assert [q['task'] for q in WeChatRequestGuard(path).snapshot()['schedule']['queue']] == ['first', 'second']
    first.start_session('发布')
    assert len(first.snapshot()['schedule']['sessions']) == 1


def test_context_blocks_third_list_request_and_stops_after_limit(tmp_path, clock):
    from types import SimpleNamespace
    from video_processing.core.wechat_session_lock import WeChatSessionLock, guard_wechat_context
    class Context:
        def __init__(self):
            self.events = {}
        def on(self, name, callback):
            self.events[name] = callback
        def route(self, pattern, callback):
            self.interceptor = callback
    context = Context()
    results = []
    with WeChatSessionLock(tmp_path / 'state.json', purpose='发布', video='video'):
        guard_wechat_context(context)
        route = SimpleNamespace(request=SimpleNamespace(url='https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/post/post_list'),
                                abort=lambda: results.append('abort'), continue_=lambda: results.append('continue'))
        for _ in range(3):
            context.interceptor(route)
        assert results == ['continue', 'continue', 'abort']
        context.events['response'](SimpleNamespace(url=route.request.url, status=200,
                                                   json=lambda: {'errCode': -360}))
        route.request.url = 'https://channels.weixin.qq.com/other'
        context.interceptor(route)
        assert results[-1] == 'abort'
    audit = [json.loads(line) for line in WeChatRequestGuard(tmp_path / 'state.json').audit_path.read_text().splitlines()]
    assert audit[-1]['event'] == 'SESSION_ENDED'
    assert audit[-1]['list_requests'] == 2


def test_unlocked_context_fails_before_navigation(clock):
    from video_processing.core.wechat_session_lock import guard_wechat_context, WeChatSessionLockBusy
    with pytest.raises(WeChatSessionLockBusy, match='没有账户调度'):
        guard_wechat_context(object())


def test_new_receipt_dispatch_is_verify_only_and_stops_when_public(tmp_path, clock, monkeypatch):
    from types import SimpleNamespace
    from scripts import wechat_scheduled_readback as worker
    path = tmp_path / 'output/wechat_state.json'
    guard = start(path, 'new-video')
    guard.metadata = {'copy_path': str(tmp_path / 'copy.txt')}
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'platform_post_id': 'native'}))
    guard.bind_publication('native', receipt)
    clock[0] += 3600
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        assert '--verify-only' in command and '--video' not in command
        start(path, 'native', '状态核对')
        evidence = worker.Path(command[command.index('--evidence-dir') + 1])
        (evidence / 'management_readback.json').write_text(json.dumps({'platform_post_id': 'native', 'state': 'PUBLISHED'}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(worker.subprocess, 'run', run)
    assert worker.reconcile_new_submissions(tmp_path)
    clock[0] += 3600
    assert not worker.reconcile_new_submissions(tmp_path)
    assert len(commands) == 1
    assert guard.snapshot()['schedule']['publications']['native']['state'] == 'PUBLISHED'

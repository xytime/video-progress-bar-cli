"""人工冷却确认：真实文件、SQLite、互斥锁和单次许可，不访问平台。"""
import fcntl
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from video_processing.core import wechat_request_guard as requests
from video_processing.core.wechat_session_lock import (
    WeChatSessionLock, WeChatSessionLockBusy, WeChatOverrideInvalid,
    EXIT_WECHAT_COOLDOWN, EXIT_WECHAT_OVERRIDE_INVALID, guarded_wechat_browser_session,
)
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from web import app as web_app


@pytest.fixture
def guard(tmp_path):
    g = requests.WeChatRequestGuard(tmp_path / 'wechat_state.json')
    g.record_limited(endpoint='/post/post_list')
    return g


def test_override_preserves_cooldown_binds_video_and_cannot_replay(guard):
    before = guard.cooldown()
    token = guard.issue_override('video_s2', before['version'])
    with pytest.raises(requests.WeChatRequestDeferred):
        guard.consume_override(token, 'other')
    one = requests.WeChatRequestGuard(guard.path.with_name('wechat_state.json'))
    one.consume_override(token, 'video_s2')
    one.check(); one.start_session('发布')
    assert one.snapshot()['blocked_until'] == before['until']
    with pytest.raises(requests.WeChatRequestDeferred):
        guard.consume_override(token, 'video_s2')
    with pytest.raises(requests.WeChatRequestDeferred):
        requests.WeChatRequestGuard(guard.path.with_name('wechat_state.json')).check()


def test_concurrent_consumers_only_one_succeeds(guard):
    token = guard.issue_override('one', guard.cooldown()['version'])
    def consume(_):
        try:
            guard.consume_override(token, 'one'); return True
        except requests.WeChatRequestDeferred:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == [False, True]


def test_real_busy_lock_does_not_consume_override(guard):
    token = guard.issue_override('one', guard.cooldown()['version'])
    path = guard.path.with_name('wechat_state.json')
    lock_path = path.with_name('.wechat_state.json.browser.lock')
    with lock_path.open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        with pytest.raises(WeChatSessionLockBusy):
            WeChatSessionLock(path, video='one', cooldown_override=token).acquire()
    with WeChatSessionLock(path, video='one', cooldown_override=token):
        pass
    with pytest.raises(WeChatOverrideInvalid):
        WeChatSessionLock(path, video='one', cooldown_override=token).acquire()


def test_force_limit_updates_deadline_once_and_retains_failure_streak(guard):
    first = guard.snapshot()
    token = guard.issue_override('one', guard.cooldown()['version'])
    guard.consume_override(token, 'one')
    guard.start_session('发布')
    guard.record_limited(endpoint='/post/post_list')
    after = guard.snapshot()
    assert after['failure_streak'] == first['failure_streak'] + 1
    assert after['blocked_until'] > first['blocked_until']
    guard.record_limited(endpoint='/post/post_list')
    assert guard.snapshot() == after


def test_stale_confirmation_and_expired_grants_fail_closed(guard, monkeypatch):
    info = guard.cooldown()
    token = guard.issue_override('one', info['version'])
    with pytest.raises(requests.WeChatRequestDeferred):
        guard.issue_override('two', 'old-version')
    now = requests.time.time()
    monkeypatch.setattr(requests.time, 'time', lambda: now + 901)
    with pytest.raises(requests.WeChatRequestDeferred):
        guard.consume_override(token, 'one')


def test_new_platform_limit_invalidates_issued_grant(guard, monkeypatch):
    info = guard.cooldown()
    token = guard.issue_override('one', info['version'])
    # 模拟另一次已授权尝试得到新限流；旧确认不能穿透新保护。
    other = guard.issue_override('two', info['version'])
    guard.consume_override(other, 'two')
    guard.record_limited(endpoint='/post/post_list')
    with pytest.raises(requests.WeChatRequestDeferred):
        guard.consume_override(token, 'one')


def test_new_session_invalidates_previous_confirmation_without_breaking_own_session(guard):
    info = guard.cooldown()
    old = guard.issue_override('one', info['version'])
    current = guard.issue_override('two', info['version'])
    guard.consume_override(current, 'two')
    guard.start_session('发布')
    guard.check()
    with pytest.raises(requests.WeChatRequestDeferred):
        guard.consume_override(old, 'one')


def test_decorator_distinguishes_cooldown_and_checks_actual_media_identity(guard):
    calls = []
    @guarded_wechat_browser_session(enabled=lambda: True, busy_result=11, purpose='发布')
    def upload(state_path, video_path, cooldown_override=None, verify_only=False, cooldown_result_codes=False):
        calls.append(video_path); return 0
    state = str(guard.path.with_name('wechat_state.json'))
    assert upload(state, 'one_vertical.mp4') == 11  # 旧调用方保留 busy 契约
    assert upload(state, 'one_vertical.mp4', cooldown_result_codes=True) == EXIT_WECHAT_COOLDOWN
    token = guard.issue_override('one', guard.cooldown()['version'])
    assert upload(state, 'other_vertical.mp4', token) == EXIT_WECHAT_OVERRIDE_INVALID
    assert upload(state, 'one_vertical.mp4', token, verify_only=True) == EXIT_WECHAT_OVERRIDE_INVALID
    assert upload(state, 'one_vertical_interactive.mp4', token) == 0
    assert upload(state, 'one_vertical_interactive.mp4', token) == EXIT_WECHAT_OVERRIDE_INVALID
    assert calls == ['one_vertical_interactive.mp4']


@pytest.mark.parametrize('filename', ['one_vocab.mp4', 'one_s2_vocab.mp4', 'one_s2_vertical.mp4', 'one_insight.mp4'])
def test_override_binds_all_final_media_variants(guard, filename):
    @guarded_wechat_browser_session(enabled=lambda: True, busy_result=11, purpose='发布')
    def upload(state_path, video_path, cooldown_override=None):
        return 0
    prefix = 'one_s2' if filename.startswith('one_s2') else 'one'
    token = guard.issue_override(prefix, guard.cooldown()['version'])
    assert upload(guard.path.with_name('wechat_state.json'), filename, token) == 0


@pytest.mark.parametrize('flags,expected', [([], 11), (['--cooldown-result-codes'], 15)])
def test_real_uploader_cli_stops_before_browser_with_compatible_result(guard, flags, expected):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / 'scripts/wechat_uploader.py'),
                             '--state', str(guard.path.with_name('wechat_state.json')),
                             '--video', str(guard.path.parent / 'one_vertical.mp4'), *flags],
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == expected, result.stderr


@pytest.fixture
def api(tmp_path, monkeypatch, guard):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    db.add_video('one', '测试视频', 'channel', score=100, source='MANUAL')
    db.mark_video_ready_for_publication('one')
    calls = []
    monkeypatch.setattr(web_app, 'db', db)
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    monkeypatch.setattr(web_app, '_trigger_video_async', lambda video: calls.append(video))
    client = TestClient(web_app.app)
    yield client, db, guard, calls
    client.close()


def test_api_initial_check_and_wait_do_not_claim_or_start(api):
    client, db, guard, calls = api
    before = db.get_video_by_youtube_id('one')
    result = client.post('/api/videos/one/process').json()
    assert result['code'] == 'WECHAT_COOLDOWN' and result['prepared']
    assert client.post('/api/videos/one/process?cooldown_action=wait').json()['waiting']
    assert db.get_video_by_youtube_id('one') == before
    assert not calls


def test_api_force_claims_one_task_without_clearing_cooldown(api):
    client, db, guard, calls = api
    info = client.post('/api/videos/one/process').json()['cooldown']
    result = client.post('/api/videos/one/process', params={
        'cooldown_action': 'force', 'cooldown_version': info['version']}).json()
    assert result['success'] and len(calls) == 1
    assert calls[0]['preparation_ready']
    token = calls[0]['_wechat_cooldown_override']
    assert guard.cooldown()['until'] == info['until']
    assert not client.post('/api/videos/one/process', params={
        'cooldown_action': 'force', 'cooldown_version': info['version']}).json()['success']
    assert len(calls) == 1
    guard.consume_override(token, 'one')


def test_api_stale_or_unknown_choice_does_not_start(api):
    client, db, guard, calls = api
    result = client.post('/api/videos/one/process?cooldown_action=force&cooldown_version=stale').json()
    assert result['code'] == 'WECHAT_COOLDOWN'
    assert not client.post('/api/videos/one/process?cooldown_action=unknown').json()['success']
    assert db.get_video_by_youtube_id('one')['status'] == 'PENDING'
    assert not calls


def test_queue_explains_ready_cooldown(api):
    _, db, _, _ = api
    rows = [db.get_video_by_youtube_id('one')]
    web_app._attach_ready_publication_fields(rows)
    assert rows[0]['display_status'] == 'READY_COOLDOWN'
    assert '加工完成 · 等待账号冷却' in rows[0]['publication_wait_reason']
    assert rows[0]['wechat_cooldown']['business_code'] == -360


def test_corrupt_guard_cannot_be_overridden_or_claim_task(api):
    client, db, guard, calls = api
    guard.path.write_text('{corrupt')
    response = client.post('/api/videos/one/process?cooldown_action=force&cooldown_version=anything').json()
    assert not response['success'] and '不可验证' in response['error']
    assert db.get_video_by_youtube_id('one')['status'] == 'PENDING'
    assert not calls


def test_ready_dispatch_skips_without_claim_or_subprocess(tmp_path, guard):
    from scripts.run_ready_publications import dispatch_once
    class ForbiddenDB:
        def get_high_score_pending_videos(self, **kwargs):
            pytest.fail('冷却期间不应查询并领取候选')
    manager = SimpleNamespace(_OUT_DIR=tmp_path, db=ForbiddenDB())
    assert dispatch_once(manager) == 0


def test_ready_submission_keeps_artifacts_and_state_while_cooling(tmp_path, guard):
    manager = PipelineManager(str(tmp_path / 'pipeline.db'))
    manager._OUT_DIR = tmp_path
    manager.db.add_video('one', '测试视频', 'channel', score=100, source='MANUAL')
    manager.db.mark_video_ready_for_publication('one')
    artifact = tmp_path / 'one_vertical.mp4'; artifact.write_bytes(b'existing artifact')
    manager._submit_ready_video(manager.db.get_video_by_youtube_id('one'))
    row = manager.db.get_video_by_youtube_id('one')
    assert row['status'] == 'PENDING' and row['preparation_ready'] == 1
    assert '等待账号冷却' in row['publication_wait_reason']
    assert artifact.read_bytes() == b'existing artifact'


@pytest.fixture(autouse=True)
def legacy_guard_mode(monkeypatch):
    """旧退避/人工凭据契约单独验证；新默认调度由 account_schedule 测试覆盖。"""
    from config.settings import settings
    monkeypatch.setattr(settings, "wechat_account_scheduler_enabled", False)
    monkeypatch.setenv("WECHAT_ACCOUNT_SCHEDULER_ENABLED", "false")

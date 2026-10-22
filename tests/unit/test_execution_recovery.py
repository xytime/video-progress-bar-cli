"""恢复意图全链路：真实 SQLite/锁/维护/账号策略，外部加工与提交在边界替身。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Codex | 验证持久等待、额度、并发认领和未知结果防重。 |
"""
from concurrent.futures import ThreadPoolExecutor
import os
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from config.settings import settings
from video_processing.core import wechat_request_guard as guards
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing.utils.execution_recovery import dispatch_recovery_once, recovery_view
from web import app as web


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(type(settings), 'default_output_dir', property(lambda self: tmp_path))
    monkeypatch.setattr(settings, 'wechat_account_scheduler_enabled', True)
    monkeypatch.setattr(settings, 'wechat_scheduler_priority_video', '')
    monkeypatch.setattr(settings, 'wechat_publishing_paused', False)
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    db.add_video('one', '低分人工任务', 'channel', score=20, source='MANUAL')
    db.mark_video_ready_for_publication('one')
    monkeypatch.setattr(web, 'db', db)
    monkeypatch.setattr(web, '_OUT_DIR', tmp_path)
    manager = PipelineManager.__new__(PipelineManager)
    manager.db, manager._OUT_DIR, manager._trigger_source = db, tmp_path, 'execution_recovery'
    manager._get_published_video_path = lambda prefix: tmp_path / (prefix + '_vertical.mp4')
    calls = []
    def submit(video):
        calls.append(video['youtube_id'])
        db.update_video_status(video['youtube_id'], 'UNDER_REVIEW', slice_index=video.get('slice_index', 0))
    manager._submit_ready_video = submit
    return db, manager, guards.WeChatRequestGuard(tmp_path / 'wechat_state.json'), calls


def test_wait_persists_through_restart_and_dispatches_once(setup):
    db, manager, guard, calls = setup
    guard.record_limited(endpoint='/post/post_list')
    with closing(TestClient(web.app)) as client:
        first = client.post('/api/videos/one/process').json()
        assert first['code'] == 'EXECUTION_WAIT'
        requests = [client.post('/api/execution-recovery/one').json()['request'] for _ in range(2)]
        assert requests[0]['id'] == requests[1]['id']
        assert not client.post('/api/videos/one/process?cooldown_action=force').json()['success']
    restarted = PipelineDB(db.db_path)
    assert restarted.execution_recovery('one')['state'] == 'WAITING'
    manager.db = restarted
    assert dispatch_recovery_once(manager) == 0 and not calls
    # 等待真实保护截止时间；不调用任何清冷却/覆盖方法。
    from unittest.mock import patch
    with patch.object(guards.time, 'time', return_value=guard.cooldown()['until'] + 1):
        assert dispatch_recovery_once(manager) == 1
        assert dispatch_recovery_once(manager) == 0
    assert calls == ['one']
    assert restarted.execution_recovery('one')['state'] == 'FINISHED'
    assert guard.snapshot()['failure_streak'] == 1


def test_expired_cooldown_with_exhausted_account_quota_stays_waiting(setup, monkeypatch):
    db, manager, guard, calls = setup
    now = guards.time.time()
    guard.record_limited(endpoint='/post/post_list')
    later = guard.cooldown()['until'] + 1
    with guard._locked():
        row = guard._read()
        row['schedule'] = {'queue': [], 'sessions': [{'at': later-1, 'purpose':'发布', 'task':'other'}], 'publications': {}}
        guard._save(row, {'event':'TEST'})
    db.enqueue_execution_recovery('one')
    monkeypatch.setattr(guards.time, 'time', lambda: later)
    assert dispatch_recovery_once(manager) == 0 and not calls
    assert db.execution_recovery('one')['state'] == 'WAITING'
    assert recovery_view(db, manager._OUT_DIR)['blockers']


def test_concurrent_registration_and_claim_only_one_wins(setup):
    db, manager, _, calls = setup
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: db.enqueue_execution_recovery('one'), range(8)))
    assert len({r['id'] for r in rows}) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: db.claim_execution_recovery(rows[0]['id'], 'one', 0, os.getpid()), range(8)))
    assert sum(claims) == 1
    assert not db.claim_video_for_processing('one')
    restarted = PipelineDB(db.db_path)
    assert restarted.execution_recovery('one')['state'] == 'RUNNING'
    assert dispatch_recovery_once(manager) == 0 and not calls
    assert recovery_view(db, manager._OUT_DIR)['requests'][0]['display_state'] == 'ATTENTION'


def test_maintenance_allows_only_intent_then_resumes(setup, isolated_running_maintenance):
    db, manager, _, calls = setup
    gate = isolated_running_maintenance
    version = gate.enter('维护中的等待登记')['version']
    with closing(TestClient(web.app)) as client:
        assert client.post('/api/videos/one/process').json()['code'] == 'EXECUTION_WAIT'
        assert client.post('/api/execution-recovery/one').json()['waiting']
        assert dispatch_recovery_once(manager) == 0 and not calls
    gate.resume(version, validated=True)
    assert dispatch_recovery_once(manager) == 1
    assert calls == ['one']


def test_automatic_candidates_and_stale_executor_cannot_steal_request(setup):
    db, manager, _, calls = setup
    db.enqueue_execution_recovery('one')
    assert not db.get_high_score_pending_videos(min_score=0)
    assert not db.claim_video_for_processing('one')
    assert not manager._process_single_video(db.get_video_by_youtube_id('one'), submission_only=True)
    assert not calls


def test_unknown_execution_outcome_never_replays(setup):
    db, manager, _, calls = setup
    db.enqueue_execution_recovery('one')
    def interrupted(video):
        calls.append('attempt')
        raise RuntimeError('submission outcome unknown')
    manager._submit_ready_video = interrupted
    with pytest.raises(RuntimeError):
        dispatch_recovery_once(manager)
    assert db.execution_recovery('one')['state'] == 'ATTENTION'
    assert dispatch_recovery_once(manager) == 0
    assert calls == ['attempt']


def test_preparation_finishes_before_separate_submission(setup):
    db, manager, _, calls = setup
    db.add_video('raw', '未加工', 'channel', score=1, source='MANUAL')
    db.enqueue_execution_recovery('raw')
    def prepare(video, *, preparation_only):
        assert preparation_only
        calls.append('prepare')
        db.mark_video_ready_for_publication('raw')
    manager._prepare_single_video = prepare
    assert dispatch_recovery_once(manager) == 1
    assert db.execution_recovery('raw')['state'] == 'WAITING'
    assert dispatch_recovery_once(manager) == 1
    assert calls == ['prepare', 'raw']


def test_shared_publish_lock_waits_without_losing_request(setup):
    from video_processing.core.task_lease import TaskLease
    db, manager, _, calls = setup
    manager._wechat_submission_evidence_paths = lambda prefix: []
    db.enqueue_execution_recovery('one')
    with TaskLease(manager._OUT_DIR / 'wechat_publish_priority.lock', video='other'):
        assert dispatch_recovery_once(manager) == 1
    assert not calls and db.execution_recovery('one')['state'] == 'WAITING'
    assert db.get_video_by_youtube_id('one')['status'] == 'PENDING'
    assert dispatch_recovery_once(manager) == 1
    assert calls == ['one']


def test_slice_sequence_waits_then_dispatches_once(setup):
    db, manager, _, calls = setup
    parent_id = db.get_video_by_youtube_id('one')['id']
    for index in (1, 2):
        db.add_video('one', f'分集{index}', 'channel', score=1, source='MANUAL', slice_index=index, parent_id=parent_id)
        db.mark_video_ready_for_publication('one', slice_index=index)
    manager._find_downloaded_video = lambda _: manager._OUT_DIR / 'parent.mp4'
    db.enqueue_execution_recovery('one', 2)
    assert dispatch_recovery_once(manager) == 0
    assert '前序' in db.execution_recovery('one', 2)['message']
    db.update_video_status('one', 'PUBLISHED', slice_index=1)
    assert dispatch_recovery_once(manager) == 1
    assert dispatch_recovery_once(manager) == 0
    assert calls == ['one']


def test_wait_does_not_override_blacklist(setup):
    db, manager, _, calls = setup
    db.enqueue_execution_recovery('one')
    db.add_to_blacklist('one')
    assert dispatch_recovery_once(manager) == 0
    assert not calls


def test_busy_task_rejects_new_wait_registration(setup):
    from video_processing.core.task_lease import TaskLease
    db, manager, _, _ = setup
    with TaskLease(manager._OUT_DIR / 'task_locks/one.lock', video='one'):
        with closing(TestClient(web.app)) as client:
            result = client.post('/api/execution-recovery/one').json()
            assert not result['success'] and '已有执行者' in result['error']
    assert db.execution_recovery('one') is None

"""维护对账须有真实锁与精确旧记录，且不得改动视频和提交保护。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 验证封面等待悬空项的最小维护对账及拒绝条件。 |
"""
import os
import sqlite3

import pytest
from config.settings import settings
from video_processing.core.maintenance import gate, MaintenanceDenied
from video_processing.core.task_lease import TaskLease
from video_processing.db.database import PipelineDB


@pytest.fixture
def stopped(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(type(settings), "default_output_dir", property(lambda _: out))
    path = out / "pipeline.db"
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE processed_videos (id INTEGER PRIMARY KEY, youtube_id TEXT, slice_index INTEGER, "
                     "status TEXT, updated_at TEXT, source TEXT, process_pid INTEGER, error_msg TEXT)")
        conn.execute("INSERT INTO processed_videos VALUES (1,'sample',2,'AI_COVER_PENDING','before','AUTO',NULL,'等待专属封面')")
        conn.execute("CREATE TABLE publishing_recovery_operations (id TEXT PRIMARY KEY,state TEXT,updated REAL)")
        conn.execute("INSERT INTO publishing_recovery_operations VALUES ('operation','QUEUED',10)")
        conn.execute("CREATE TABLE publishing_recovery_items (id INTEGER PRIMARY KEY,video_id INTEGER,operation_id TEXT,"
                     "state TEXT,reason TEXT,updated REAL)")
        conn.execute("INSERT INTO publishing_recovery_items VALUES (10,1,'operation','RUNNING','等待实际锁',10)")
        conn.execute("CREATE TABLE manual_publish_leases (lease_id TEXT)")
        conn.execute("INSERT INTO manual_publish_leases VALUES ('unchanged')")
        for table in ('wechat_publications', 'wechat_publications_historical_archive',
                      'wechat_submission_attempts', 'douyin_publications', 'kuaishou_publications'):
            conn.execute(f'CREATE TABLE {table} (video_id INTEGER)')
        item = dict(conn.execute('SELECT * FROM publishing_recovery_items').fetchone())
        video = dict(conn.execute('SELECT * FROM processed_videos').fetchone())
    original = os.kill
    def kill(pid, sig):
        if pid == 999999:
            raise ProcessLookupError()
        return original(pid, sig)
    monkeypatch.setattr(os, 'kill', kill)
    version = gate().enter('test stopped cover wait')['version']
    return path, dict(expected_item=item, expected_video=video, pid=999999, expected_version=version)


def snapshot(path):
    with sqlite3.connect(path) as conn:
        return {name: conn.execute(f'SELECT * FROM {name}').fetchall()
                for name in ['processed_videos','publishing_recovery_items','publishing_recovery_operations','manual_publish_leases']}


def test_finished_preparation_only_closes_item_and_preserves_video_and_permit(stopped):
    path, args = stopped
    before = snapshot(path)
    result = PipelineDB.maintenance_finish_stopped_cover_wait(path, **args)
    after = snapshot(path)
    assert result == dict(item_id=10, video_id=1, state='FAILED', reason='等待专属封面', video_unchanged=True)
    assert after['processed_videos'] == before['processed_videos']
    assert after['manual_publish_leases'] == before['manual_publish_leases']
    assert after['publishing_recovery_items'][0][3:5] == ('FAILED','等待专属封面')
    assert after['publishing_recovery_operations'][0][1] == 'COMPLETED'
    with pytest.raises(ValueError, match='STATE_CHANGED'):
        PipelineDB.maintenance_finish_stopped_cover_wait(path, **args)


@pytest.mark.parametrize('blocker', ['pid','pid_permission','version','running','status','updated_at','item','operation',
    'wechat_publications','wechat_publications_historical_archive','wechat_submission_attempts',
    'douyin_publications','kuaishou_publications','pipeline.lock','task_locks/sample_s2.lock',
    'publishing_recovery_worker.lock','publication_window_runner.lock'])
def test_changes_live_owner_and_submission_fail_closed_without_mutation(stopped, blocker, monkeypatch):
    path, args = stopped
    if blocker == 'pid': args['pid'] = os.getpid()
    if blocker == 'pid_permission':
        def denied(pid, sig): raise PermissionError('unknown')
        monkeypatch.setattr(os, 'kill', denied)
    if blocker == 'version': args['expected_version'] -= 1
    if blocker == 'running': gate().resume(expected_version=args['expected_version'], validated=True)
    with sqlite3.connect(path) as conn:
        if blocker == 'status': conn.execute("UPDATE processed_videos SET status='UNCERTAIN'")
        if blocker == 'updated_at': conn.execute("UPDATE processed_videos SET updated_at='changed'")
        if blocker == 'item': conn.execute("UPDATE publishing_recovery_items SET reason='changed'")
        if blocker == 'operation': conn.execute("UPDATE publishing_recovery_operations SET state='CANCELLED'")
        if blocker in {'wechat_publications','wechat_publications_historical_archive','wechat_submission_attempts',
                       'douyin_publications','kuaishou_publications'}:
            conn.execute(f'INSERT INTO {blocker} VALUES (1)')
    before = snapshot(path)
    if blocker.endswith('.lock'):
        with TaskLease(path.parent / blocker, stage='actual-owner'):
            with pytest.raises((BlockingIOError, MaintenanceDenied)):
                PipelineDB.maintenance_finish_stopped_cover_wait(path, **args)
    else:
        with pytest.raises((ValueError, MaintenanceDenied, PermissionError)):
            PipelineDB.maintenance_finish_stopped_cover_wait(path, **args)
    assert snapshot(path) == before

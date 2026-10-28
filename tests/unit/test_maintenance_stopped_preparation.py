"""维护对账只处理已停止、无任何提交账本的加工占位，不重试发布。"""
import os
import sqlite3

import pytest

from video_processing.core.maintenance import gate, MaintenanceDenied
from video_processing.db.database import PipelineDB


@pytest.fixture
def stopped(tmp_path, monkeypatch):
    path = tmp_path / 'stopped.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE processed_videos (id INTEGER PRIMARY KEY, youtube_id TEXT, '
                     'slice_index INTEGER, status TEXT, updated_at TEXT, source TEXT, process_pid INTEGER, error_msg TEXT)')
        conn.execute("INSERT INTO processed_videos VALUES (1,'sample',0,'PROCESSING','before','AUTO',123,NULL)")
        for table in ('wechat_publications', 'wechat_publications_historical_archive',
                      'wechat_submission_attempts', 'douyin_publications', 'kuaishou_publications'):
            conn.execute(f'CREATE TABLE {table} (video_id INTEGER)')
    original = os.kill
    def kill(pid, sig):
        if pid == 999999:
            raise ProcessLookupError()
        return original(pid, sig)
    monkeypatch.setattr(os, 'kill', kill)
    state = gate().enter('test stopped preparation')
    return path, [dict(youtube_id='sample', pid=999999, updated_at='before')], state['version']


def test_explicit_reconciliation_marks_failed_and_preserves_other_fields(stopped):
    path, records, version = stopped
    assert PipelineDB.maintenance_fail_stopped_preparation(path, records, expected_version=version) == ['sample']
    with sqlite3.connect(path) as conn:
        row = conn.execute('SELECT status, process_pid, source, error_msg FROM processed_videos').fetchone()
    assert row[:3] == ('FAILED', None, 'AUTO') and row[3].startswith('[RecoveryInterrupted]')


@pytest.mark.parametrize('blocker', ['pid', 'version', 'status', 'publication', 'updated_at'])
def test_live_changed_or_submitted_record_is_never_rewritten(stopped, blocker):
    path, records, version = stopped
    if blocker == 'pid': records[0]['pid'] = os.getpid()
    if blocker == 'version': version -= 1
    if blocker == 'updated_at': records[0]['updated_at'] = 'changed'
    with sqlite3.connect(path) as conn:
        if blocker == 'status': conn.execute("UPDATE processed_videos SET status='UNCERTAIN'")
        if blocker == 'publication': conn.execute('INSERT INTO wechat_submission_attempts VALUES (1)')
        before = conn.execute('SELECT * FROM processed_videos').fetchall()
    with pytest.raises((ValueError, MaintenanceDenied)):
        PipelineDB.maintenance_fail_stopped_preparation(path, records, expected_version=version)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT * FROM processed_videos').fetchall() == before

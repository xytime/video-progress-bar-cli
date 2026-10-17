"""M08–M12：真实候选 SQLite/文件故障、有界单飞恢复与关闭回读。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 隔离故障与恢复验收，无网络/业务执行 |
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import fcntl
import os
import sqlite3
import time
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.topic_candidate_fixtures import tracker, topic, run, decision
from video_processing.core.topic_candidates import TopicError
from video_processing.db.topic_candidates import TopicCandidateDAL
from video_processing.topic_tracker.runtime import TopicRuntime
from web.topic_candidates import create_topic_candidates_router


def test_m08_real_directory_lock_keeps_old_get_available(tracker):
    tracker.lock_path.unlink(missing_ok=True)
    tracker.lock_path.mkdir()
    app = FastAPI()
    app.get('/old-health')(lambda: {'ok': True})
    app.include_router(create_topic_candidates_router(lambda: tracker, port=9100))
    with TestClient(app, base_url='http://127.0.0.1:9100', client=('127.0.0.1', 1)) as client:
        assert client.get('/old-health').status_code == 200
        result = client.get('/topic-candidates')
        assert result.status_code == 503
        assert result.json()['detail']['code'] == 'LOCK_UNAVAILABLE'
        assert str(tracker.lock_path) not in result.text
        assert not tracker.adapter.calls


@pytest.mark.parametrize('fault', ['permission', 'flock'])
def test_m08_permission_and_narrow_flock_failure(tracker, monkeypatch, fault):
    tracker.lock_path.touch(exist_ok=True)
    if fault == 'permission':
        tracker.lock_path.chmod(0o400)
    else:
        original = fcntl.flock
        inode = tracker.lock_path.stat().st_ino
        def failing(stream, operation):
            fd = stream if isinstance(stream, int) else stream.fileno()
            if os.fstat(fd).st_ino == inode:
                raise OSError('sensitive-private-lock')
            return original(stream, operation)
        monkeypatch.setattr(fcntl, 'flock', failing)
    try:
        with pytest.raises(TopicError) as result:
            tracker.maintenance()
        assert result.value.code == 'LOCK_UNAVAILABLE'
        assert 'sensitive' not in result.value.message
        assert not tracker.adapter.calls
    finally:
        tracker.lock_path.chmod(0o600)


@pytest.mark.parametrize('fault', ['connect', 'pragma', 'ddl', 'close'])
def test_m09_full_connection_boundary_real_sqlite(tracker, monkeypatch, fault):
    class Fault(sqlite3.Connection):
        def execute(self, sql, *args):
            if (fault == 'pragma' and sql.startswith('PRAGMA')) or (fault == 'ddl' and sql.startswith('CREATE TABLE')):
                raise sqlite3.OperationalError('sensitive-path')
            return super().execute(sql, *args)
        def close(self):
            super().close()
            if fault == 'close':
                raise sqlite3.OperationalError('sensitive-path')
    def connect():
        if fault == 'connect':
            raise sqlite3.OperationalError('sensitive-path')
        return sqlite3.connect(tracker.db.db_path, timeout=2, factory=Fault)
    monkeypatch.setattr(tracker.db, '_connect_topic', connect)
    begin = time.monotonic()
    with pytest.raises(TopicError) as result:
        tracker.db.topic_initialize()
    assert result.value.code == 'DATABASE_ERROR'
    assert 'sensitive' not in result.value.message
    assert time.monotonic() - begin < 10
    def factory():
        tracker.db.topic_initialize()
        return tracker
    app = FastAPI()
    app.get('/old-health')(lambda: {'ok': True})
    app.include_router(create_topic_candidates_router(factory, port=9100))
    with TestClient(app, base_url='http://127.0.0.1:9100', client=('127.0.0.1', 1)) as client:
        assert client.get('/old-health').status_code == 200
        response = client.get('/topic-candidates')
        assert response.status_code == 503
        assert response.json()['detail']['code'] == 'DATABASE_ERROR'
        assert 'sensitive' not in response.text
    assert not tracker.adapter.calls


def test_m09_actual_readonly_sqlite_cannot_create_candidate_tables(tmp_path, monkeypatch):
    path = tmp_path / 'readonly.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE legacy_health (value TEXT)')
        conn.execute("INSERT INTO legacy_health VALUES ('healthy')")
    db = TopicCandidateDAL()
    db.db_path = str(path)
    monkeypatch.setattr(db, '_connect_topic',
        lambda: sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2))
    begin = time.monotonic()
    with pytest.raises(TopicError) as error:
        db.topic_initialize()
    assert error.value.code == 'DATABASE_ERROR'
    assert time.monotonic() - begin < 10
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
        assert conn.execute('SELECT value FROM legacy_health').fetchone()[0] == 'healthy'
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'topic_%'").fetchall() == []


def test_m09_third_ddl_failure_rolls_back_real_partial_initialization(tmp_path, monkeypatch):
    path = tmp_path / 'partial.sqlite'
    calls = []
    class ThirdDDLFailure(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith('CREATE TABLE'):
                calls.append(sql)
                if len(calls) == 3:
                    raise sqlite3.OperationalError('private-third-ddl')
            return super().execute(sql, *args)
    db = TopicCandidateDAL()
    db.db_path = str(path)
    monkeypatch.setattr(db, '_connect_topic',
        lambda: sqlite3.connect(path, timeout=2, factory=ThirdDDLFailure))
    with pytest.raises(TopicError) as error:
        db.topic_initialize()
    assert error.value.code == 'DATABASE_ERROR'
    assert len(calls) == 3
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'topic_%'").fetchall() == []
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_m09_busy_transaction_is_bounded_and_readonly_explicit(tracker):
    with sqlite3.connect(tracker.db.db_path) as held:
        held.execute('BEGIN IMMEDIATE')
        begin = time.monotonic()
        with pytest.raises(TopicError) as error:
            tracker.db.topic_initialize()
        assert error.value.code == 'DATABASE_BUSY'
        assert 1.8 <= time.monotonic() - begin < 3
        held.rollback()
    tracker.db._read_only = True
    with pytest.raises(TopicError) as error:
        tracker.db.topic_initialize()
    assert error.value.code == 'READ_ONLY'
    tracker.db._read_only = False


def test_m10_concurrent_retry_anchor_and_m12_recovery_off(tracker, monkeypatch):
    import video_processing.topic_tracker.runtime as runtime_module
    clock = [100.0]
    calls = []
    def factory():
        calls.append(clock[0])
        tracker.db.topic_initialize()
        tracker.config.topic_search_enabled = False
        tracker.enforce_closed()
        return tracker
    runtime = TopicRuntime(factory, monotonic=lambda: clock[0])
    monkeypatch.setattr(runtime_module, 'TopicRuntime', lambda factory: runtime)
    app = FastAPI()
    app.get('/old-health')(lambda: {'ok': True})
    app.include_router(create_topic_candidates_router(factory, port=9100))
    with sqlite3.connect(tracker.db.db_path) as held:
        held.execute('BEGIN IMMEDIATE')
        with TestClient(app, base_url='http://127.0.0.1:9100', client=('127.0.0.1', 1)) as client:
            for now, expected in [(100, 503), (159, 503), (160, 503), (219, 503), (220, 200)]:
                clock[0] = now
                if now == 220:
                    held.rollback()
                with ThreadPoolExecutor(max_workers=8) as pool:
                    assert set(pool.map(lambda _: client.get('/topic-candidates').status_code, range(20))) == {expected}
                assert client.get('/old-health').status_code == 200
            assert runtime.service().view()['search_open'] is False
            assert tracker.db.topic_control()['mode'] == 'OFF'
            assert tracker.db.topic_jobs() == []
    assert calls == [100, 160, 220]
    assert not tracker.adapter.calls


def test_m11_cleanup_fault_hides_expired_data_recovers_and_stop_unconfirmed(tracker, monkeypatch):
    run(tracker)
    record = tracker.candidates()['candidates'][0]
    tracker.decide(record['key'], decision(record), 'operator')
    runtime = TopicRuntime(lambda: tracker, monotonic=lambda: clock[0])
    clock = [0]
    runtime.service()
    tracker.clock.advance(days=31)
    with sqlite3.connect(tracker.db.db_path) as held:
        held.execute('BEGIN IMMEDIATE')
        with pytest.raises(TopicError): runtime.clean()
        assert runtime.health['ready'] is False
        with pytest.raises(TopicError): runtime.service()
        runtime.stop()
        assert runtime.health['stopped_off_confirmed'] is False
        held.rollback()
    clock[0] = 61
    runtime.clean()
    assert runtime.health['ready'] is True
    assert tracker.db.topic_candidate(record['key'])['metadata'] is None
    with sqlite3.connect(tracker.db.db_path) as conn:
        assert conn.execute('SELECT state FROM topic_decisions WHERE key=?', (record['key'],)).fetchone()[0] == 'SAVED'
    runtime.stop()
    assert runtime.health['stopped_off_confirmed'] is True
    assert not tracker._threads
    assert len(tracker.adapter.calls) == 2

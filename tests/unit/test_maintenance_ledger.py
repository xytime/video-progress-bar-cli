"""维护排空读取真实执行枚举；独立 SQLite 文件，不初始化项目数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-30 | Codex | 独立投稿/制作/恢复账本、双列去重、核心表与旧 schema 的只读闭锁反例。 |
"""
import hashlib
import sqlite3

import pytest

from video_processing.db.database import PipelineDB


ACTIVE = [
    ('processed_videos', 'status', 'PUBLISHING'),
    ('english_world_jobs', 'state', 'RESEARCHING'),
    ('english_world_review_items', 'state', 'SUBMITTING'),
    ('english_world_submission_attempts', 'state', 'SUBMITTING'),
    ('english_world_douyin_publications', 'state', 'SUBMITTING'),
    ('english_world_douyin_attempts', 'state', 'SUBMITTING'),
    ('douyin_publications', 'state', 'SUBMITTING'),
    ('kuaishou_publications', 'state', 'SUBMITTING'),
    ('wallstreet_publications', 'state', 'SUBMITTING'),
    ('wallstreet_version_publications', 'state', 'SUBMITTING'),
    ('wallstreet_pairs', 'state', 'RENDERING'),
    ('wechat_review_notifications', 'delivery_state', 'PROCESSING'),
    ('highlight_jobs', 'state', 'ANALYZING'),
    ('publishing_recovery_items', 'state', 'RUNNING'),
    ('delivery_recoveries', 'state', 'RUNNING'),
    ('delivery_recoveries', 'state', 'PAUSE_REQUESTED'),
]


def core_schema(connection):
    connection.execute('CREATE TABLE processed_videos (id INTEGER PRIMARY KEY, status TEXT)')


@pytest.mark.parametrize('table,column,state', ACTIVE)
def test_independent_execution_ledger_blocks_even_without_video_row(tmp_path, table, column, state):
    path = tmp_path / 'ledger.db'
    with sqlite3.connect(path) as connection:
        core_schema(connection)
        if table != 'processed_videos':
            connection.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, {column} TEXT)')
        connection.execute(f'INSERT INTO {table} VALUES (1,?)', (state,))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert PipelineDB.maintenance_active_work(path) == [dict(table=table, count=1)]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute(f'SELECT {column} FROM {table}').fetchone()[0] == state
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {'processed_videos', table}


@pytest.mark.parametrize('state,production', [('PRODUCTION_REQUESTED', 'PRODUCING'), ('RESEARCHING', 'PRODUCING')])
def test_english_world_production_is_active_and_same_row_is_counted_once(tmp_path, state, production):
    path = tmp_path / 'production.db'
    with sqlite3.connect(path) as connection:
        core_schema(connection)
        connection.execute('CREATE TABLE english_world_jobs (id TEXT, state TEXT, production_state TEXT)')
        connection.execute('INSERT INTO english_world_jobs VALUES (?,?,?)', ('one', state, production))
        connection.execute("INSERT INTO english_world_jobs VALUES ('waiting','PRODUCTION_REQUESTED','REQUESTED')")
    assert PipelineDB.maintenance_active_work(path) == [dict(table='english_world_jobs', count=1)]


def test_english_world_old_schema_still_checks_required_research_state(tmp_path):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as connection:
        core_schema(connection)
        connection.execute('CREATE TABLE english_world_jobs (id TEXT, state TEXT)')
        connection.executemany('INSERT INTO english_world_jobs VALUES (?,?)',
                               [('active', 'RESEARCHING'), ('waiting', 'PRODUCTION_REQUESTED')])
    assert PipelineDB.maintenance_active_work(path) == [dict(table='english_world_jobs', count=1)]


def test_waiting_uncertain_and_platform_review_records_are_preserved_without_execution_count(tmp_path):
    path = tmp_path / 'protected.db'
    states = {
        'processed_videos': ('status', ['UNCERTAIN', 'FAILED', 'PENDING']),
        'wechat_publications': ('state', ['UNCERTAIN', 'UNDER_REVIEW', 'SUBMITTED_UNBOUND', 'SUBMITTED_BOUND']),
        'wechat_submission_attempts': ('state', ['SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND']),
        'english_world_review_items': ('state', ['UNCERTAIN', 'UNDER_REVIEW', 'HELD', 'SUBMISSION_APPROVED']),
        'english_world_submission_attempts': ('state', ['UNCERTAIN', 'UNDER_REVIEW', 'FAILED']),
        'english_world_douyin_publications': ('state', ['UNCERTAIN', 'UNDER_REVIEW', 'QUEUED']),
        'english_world_douyin_attempts': ('state', ['UNCERTAIN', 'UNDER_REVIEW', 'FAILED']),
        'wallstreet_version_publications': ('state', ['UNCERTAIN', 'UNDER_REVIEW', 'WAITING']),
        'wallstreet_pairs': ('state', ['READY']),
        'publishing_recovery_items': ('state', ['RESERVED', 'WAITING']),
        'delivery_recoveries': ('state', ['WAITING', 'QUEUED', 'HELD', 'NEEDS_REVIEW', 'DONE']),
    }
    with sqlite3.connect(path) as connection:
        for table, (column, values) in states.items():
            connection.execute(f'CREATE TABLE {table} ({column} TEXT)')
            connection.executemany(f'INSERT INTO {table} VALUES (?)', [(value,) for value in values])
    original = path.read_bytes()
    assert PipelineDB.maintenance_active_work(path) == []
    assert path.read_bytes() == original


def test_mixed_execution_rows_report_per_table_counts_without_overcounting(tmp_path):
    path = tmp_path / 'mixed.db'
    with sqlite3.connect(path) as connection:
        core_schema(connection)
        connection.execute('CREATE TABLE english_world_jobs (state TEXT, production_state TEXT)')
        connection.executemany('INSERT INTO english_world_jobs VALUES (?,?)',
                               [('RESEARCHING', 'PRODUCING'), ('PRODUCTION_REQUESTED', 'PRODUCING'),
                                ('PRODUCTION_REQUESTED', 'REQUESTED')])
        connection.execute('CREATE TABLE delivery_recoveries (state TEXT)')
        connection.executemany('INSERT INTO delivery_recoveries VALUES (?)', [('RUNNING',), ('PAUSE_REQUESTED',), ('HELD',)])
    assert PipelineDB.maintenance_active_work(path) == [dict(table='english_world_jobs', count=2),
                                                       dict(table='delivery_recoveries', count=2)]


@pytest.mark.parametrize('table,definition', [('processed_videos', 'unknown TEXT'),
                                           ('english_world_jobs', 'production_state TEXT'),
                                           ('wallstreet_version_publications', 'unknown TEXT'),
                                           ('delivery_recoveries', 'unknown TEXT')])
def test_required_column_missing_fails_closed_instead_of_returning_idle(tmp_path, table, definition):
    path = tmp_path / 'broken.db'
    with sqlite3.connect(path) as connection:
        if table != 'processed_videos':
            core_schema(connection)
        connection.execute(f'CREATE TABLE {table} ({definition})')
    original = path.read_bytes()
    with pytest.raises(sqlite3.OperationalError):
        PipelineDB.maintenance_active_work(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize('definition', [None, 'CREATE TABLE unrelated (value TEXT)',
                                      'CREATE TABLE delivery_recoveries (state TEXT)'])
def test_empty_or_wrong_database_missing_core_table_fails_closed(tmp_path, definition):
    path = tmp_path / 'wrong.db'
    with sqlite3.connect(path) as connection:
        connection.execute('PRAGMA user_version = 1')
        if definition:
            connection.execute(definition)
    original = path.read_bytes()
    with pytest.raises(sqlite3.DatabaseError, match='MAINTENANCE_CORE_TABLE_MISSING: processed_videos'):
        PipelineDB.maintenance_active_work(path)
    assert path.read_bytes() == original


def test_empty_valid_core_schema_is_idle_without_initializing_optional_tables(tmp_path):
    path = tmp_path / 'idle.db'
    with sqlite3.connect(path) as connection:
        core_schema(connection)
    original = path.read_bytes()
    assert PipelineDB.maintenance_active_work(path) == []
    assert path.read_bytes() == original


def test_missing_database_is_not_created_by_maintenance_inspection(tmp_path):
    path = tmp_path / 'missing.db'
    with pytest.raises(sqlite3.OperationalError):
        PipelineDB.maintenance_active_work(path)
    assert not path.exists()

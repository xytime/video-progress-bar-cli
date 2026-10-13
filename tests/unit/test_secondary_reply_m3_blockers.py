"""M3 阻断回归：只读入口无副作用，账号在审批绑定及消费事务内校验。"""
import pytest

from tests.unit.test_secondary_reply_cli_real_entry import cli, env, _import
from tests.unit.test_secondary_reply_orchestration import _published
from video_processing.db.database import PipelineDB
from config.settings import settings


def snapshot(root):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir() if p.is_file()}


@pytest.mark.parametrize('command', ['preflight', 'status'])
def test_readonly_keeps_unrelated_task_and_files(env, capsys, command):
    _, imported = _import(env, capsys)
    db = PipelineDB(str(env.db_path))
    _published(db, env.tmp, 'readonly_probe')
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET status='PENDING' WHERE youtube_id='yt_readonly_probe'")
    before = snapshot(env.tmp)
    env.run(capsys, command, '--task-id', str(imported['task_id']))
    assert snapshot(env.tmp) == before
    readonly = PipelineDB(str(env.db_path), read_only=True)
    with readonly.get_connection() as conn:
        row = conn.execute("SELECT status FROM processed_videos WHERE youtube_id='yt_readonly_probe'").fetchone()
    assert row['status'] == 'PENDING'


@pytest.mark.parametrize('command', ['preflight', 'status'])
def test_readonly_missing_database_and_active_wal_refuse_without_changes(env, capsys, command):
    before = snapshot(env.tmp)
    assert env.run(capsys, command, '--task-id', '1')[0] == 2
    assert snapshot(env.tmp) == before
    _import(env, capsys)
    db = PipelineDB(str(env.db_path))
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_secondary_reply_tasks SET reason_code='WAL_PROBE'")
        conn.commit()
        before = snapshot(env.tmp)
        code, result = env.run(capsys, command, '--task-id', '1')
        assert code == 2 and 'ACTIVE_WAL' in result['reason']
        assert snapshot(env.tmp) == before


def test_other_account_cannot_approve_task(env, capsys, monkeypatch):
    _, imported = _import(env, capsys)
    db = PipelineDB(str(env.db_path))
    before = db.get_secondary_reply_task(imported['task_id'])
    monkeypatch.setattr(settings, 'wechat_reply_account_key', 'other_account')
    code, result = env.run(capsys, 'approve', '--task-id', str(imported['task_id']),
                           '--confirm-reply-sha12', imported['reply_sha256'][:12])
    assert code == 1 and result['reason'] == 'ACCOUNT_MISMATCH'
    assert db.get_secondary_reply_task(imported['task_id']) == before
    monkeypatch.setattr(settings, 'wechat_reply_account_key', 'acct_cli')
    assert env.run(capsys, 'approve', '--task-id', str(imported['task_id']),
                   '--confirm-reply-sha12', imported['reply_sha256'][:12])[0] == 0


def test_dal_checks_account_on_bind_and_atomic_consume(env, capsys):
    _, imported = _import(env, capsys)
    db = PipelineDB(str(env.db_path))
    tid = imported['task_id']
    before = db.get_secondary_reply_task(tid)
    kwargs = dict(approval_token='random-test-token', expires_at_iso='2099-01-01 00:00:00',
                  approver_id='777', approver_chat_id='chat')
    assert not db.bind_reply_task_approval_request(tid, expected_account_key='other', **kwargs)
    assert db.get_secondary_reply_task(tid) == before
    assert db.bind_reply_task_approval_request(tid, expected_account_key='acct_cli', **kwargs)
    bound = db.get_secondary_reply_task(tid)
    consume = dict(task_id=tid, token='random-test-token', approver_id='777', chat_id='chat', action='APPROVE')
    assert db.consume_reply_task_approval(expected_account_key='other', **consume) == (False, 'ACCOUNT_MISMATCH')
    assert db.get_secondary_reply_task(tid) == bound
    assert db.consume_reply_task_approval(expected_account_key='acct_cli', **consume) == (True, 'APPROVED')

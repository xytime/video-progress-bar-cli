"""一次性孤儿隔离：真实 SQLite、真实 DAL 领取、维护门禁及触发器回滚。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1 | 2026-10-31 | Codex | 历史模式夹具与当前模式拒绝分开验证，保留原一次性工具写入保护。 |
| 1.0 | 2026-10-13 | Codex | 授权目标及禁止自动入队的针对性验收 |
"""
import importlib.util
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from video_processing.db.database import PipelineDB as BusinessDB
from video_processing.core.deployment import DeploymentDenied

DIRECTORY = Path(__file__).resolve().parents[2] / "docs/handoffs/2026-10-13-article-release"
for name in ("repair_dal", "recover_orphan", "continue_stopped_deployment"):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
dal = sys.modules["repair_dal"]
recovery = sys.modules["recover_orphan"]


@pytest.fixture
def record(tmp_path):
    path = tmp_path / "pipeline.db"
    business = BusinessDB(str(path))
    with sqlite3.connect(path) as conn:
        # 本文档工具仅适用于 10 月 13 日冻结的写入范围；10 月 23 日新加的
        # 失败事件触发器不属于该历史模式。只在一次性测试库还原历史模式，
        # 不放宽已审计工具的 authorizer；另测其对当前模式必须拒绝写入。
        conn.execute("DROP TRIGGER publishing_failed_update")
        conn.execute("DROP TRIGGER publishing_failed_insert")
        values = dict(dal.TARGET, title="需人工复核的原任务", channel_id="test", score=99)
        conn.execute(f"INSERT INTO processed_videos ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
        conn.execute("INSERT INTO processed_videos(id,youtube_id,title,channel_id,status) VALUES (5788,'unrelated','title','test','PENDING')")
        conn.execute("INSERT INTO wechat_publications(video_id,subject_id,state) VALUES (5788,'unrelated','PUBLISHED')")
    return path, business, dal.PipelineDB.repair_snapshot(path)


def test_historical_tool_refuses_current_schema_without_partial_writes(record):
    path, business, before = record
    business.initialize_publishing_recovery()
    with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
        dal.PipelineDB.hold_authorized_orphan(path, before)
    assert dal.PipelineDB.repair_snapshot(path) == before
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM publishing_failure_events').fetchone() == (0,)


def test_hold_preserves_task_ledgers_and_real_claims_refuse(record):
    path, business, before = record
    result = dal.PipelineDB.hold_authorized_orphan(path, before)
    assert result['updated_rows'] == 1 and result['enqueued'] is False
    after = dal.PipelineDB.repair_snapshot(path)
    assert after['status'] == 'FAILED' and after['publication_review_required'] == 1
    assert after['retry_count'] == 0 and after['process_pid'] is None
    assert all(after[k] == v for k, v in before.items() if k not in dal.CHANGED)
    assert not business.claim_video_for_processing(dal.TARGET['youtube_id'])
    assert not business.claim_video_for_publication(dal.TARGET['youtube_id'], 123)
    assert all(v['youtube_id'] != dal.TARGET['youtube_id'] for v in business.get_high_score_pending_videos())
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT state FROM wechat_publications WHERE video_id=5788").fetchone() == ('PUBLISHED',)
        assert conn.execute("SELECT status FROM processed_videos WHERE id=5788").fetchone() == ('PENDING',)
    with pytest.raises(ValueError, match='RECORD_DRIFT'):
        dal.PipelineDB.hold_authorized_orphan(path, before)


@pytest.mark.parametrize('field,value', [('id',5788),('youtube_id','other'),('slice_index',1),('status','PUBLISHING'),('process_pid',123),('retry_count',1),('updated_at','changed')])
def test_wrong_authorization_never_writes(record, field, value):
    path, _, before = record
    with pytest.raises(ValueError, match='TARGET_NOT_AUTHORIZED'):
        dal.PipelineDB.hold_authorized_orphan(path, dict(before, **{field:value}))
    assert dal.PipelineDB.repair_snapshot(path) == before


def test_actual_record_drift_refused(record):
    path, _, before = record
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE processed_videos SET title='changed' WHERE id=5787")
    with pytest.raises(ValueError, match='RECORD_DRIFT'):
        dal.PipelineDB.hold_authorized_orphan(path, before)
    assert dal.PipelineDB.repair_snapshot(path)['status'] == 'PROCESSING'


@pytest.mark.parametrize('table,values', [
    ('wechat_publications', {'subject_id':'target','state':'UNCERTAIN'}),
    ('wechat_submission_attempts', {'attempt_id':'target','subject_id':'target','state':'SUBMITTED_UNBOUND','final_title':'title'}),
    ('wechat_publications_historical_archive', {'archived_at':'now','archive_reason':'test','state':'PUBLISHED'}),
    ('wechat_upload_retries', {'evidence_path':'test','attempt_number':1,'next_attempt_at':'later'}),
    ('douyin_publications', {'asset_sha256':'test','source_kind':'NEW','video_path':'test.mp4'}),
    ('kuaishou_publications', {'asset_sha256':'test','source_kind':'NEW','video_path':'test.mp4'}),
])
def test_any_target_ledger_evidence_refuses(record, table, values):
    path, _, before = record
    values = dict(values, video_id=5787)
    with sqlite3.connect(path) as conn:
        conn.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
    with pytest.raises(ValueError, match='SUBMISSION_EVIDENCE_PRESENT'):
        dal.PipelineDB.hold_authorized_orphan(path, before)
    assert dal.PipelineDB.repair_snapshot(path) == before


@pytest.mark.parametrize('action', ["UPDATE processed_videos SET status='FAILED' WHERE id=5788", "DELETE FROM wechat_publications WHERE video_id=5788"])
def test_trigger_side_effect_rolls_back_whole_transaction(record, action):
    path, _, before = record
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TRIGGER surprise AFTER UPDATE ON processed_videos WHEN NEW.id=5787 BEGIN {action}; END")
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        dal.PipelineDB.hold_authorized_orphan(path, before)
    assert dal.PipelineDB.repair_snapshot(path) == before
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM processed_videos WHERE id=5788").fetchone() == ('PENDING',)
        assert conn.execute("SELECT count(*) FROM wechat_publications").fetchone() == (1,)


@pytest.mark.parametrize('state,version,active,unknown', [('RUNNING',9,[],[]),('MAINTENANCE',10,[],[]),('MAINTENANCE',9,[{'pid':1}],[]),('MAINTENANCE',9,[],[{'code':'UNKNOWN'}])])
def test_control_change_refuses(state, version, active, unknown):
    with pytest.raises(DeploymentDenied):
        recovery.require_control({'state':state,'version':version}, active, unknown)


def test_backup_verification_failure_precedes_database_mutation(record, tmp_path, monkeypatch):
    # 将备份完整性与单条操作串联；不把一份损坏副本用作恢复依据。
    path, _, before = record
    backup = tmp_path / 'backup.sqlite'
    proof = dal.PipelineDB.maintenance_backup(path, backup)
    backup.write_bytes(b'corrupt')
    assert not dal.PipelineDB.verify_recovery_backup(backup, proof)
    assert dal.PipelineDB.repair_snapshot(path) == before


def test_sealed_backup_rejects_wal_and_relocation(record, tmp_path):
    path, _, before = record
    backup = tmp_path/'sealed backup.sqlite'
    proof = dal.PipelineDB.maintenance_backup(path, backup)
    assert dal.PipelineDB.verify_recovery_backup(backup, proof)
    assert dal.PipelineDB.repair_snapshot(backup, verified_backup=True)==before
    assert not dal.PipelineDB.verify_recovery_backup(backup, dict(proof,path='other'))
    Path(str(backup)+'-wal').write_bytes(b'unsealed')
    assert not dal.PipelineDB.verify_recovery_backup(backup, proof)


@pytest.mark.parametrize('failure', [None,'source','schedule','backup','version','other_unknown','existing_intent'])
def test_controlled_recovery_chain(record, tmp_path, monkeypatch, isolated_running_maintenance, failure):
    path, _, before = record
    directory = tmp_path / 'deployment'
    directory.mkdir()
    (directory / 'plan.json').write_text('{}')
    proof = dal.PipelineDB.maintenance_backup(path, directory / 'ledger-inspection.sqlite')
    recovery.write_json(directory/'ledger-inspection-backup.json', proof)
    control = isolated_running_maintenance
    while control.status()['version'] < 9:
        value = control.status()
        if value['state'] == 'RUNNING':
            control.enter('test')
        else:
            control.resume(value['version'], validated=True)
    if failure == 'version':
        control.resume(9, validated=True)
    if failure == 'backup':
        (directory / 'before-orphan-recovery.sqlite').mkdir()
    if failure == 'existing_intent':
        (directory / 'orphan-recovery-intent.json').write_text('{}')
    def check(label):
        if label == failure:
            raise DeploymentDenied(label)
    def observe(*args, **kwargs):
        value = control.status()
        unknown = [{'code':'UNFINISHED_LEDGER'}] if dal.PipelineDB.maintenance_active_work(path) else []
        if failure == 'other_unknown':
            unknown.append({'code':'LEGACY_WORKER'})
        return dict(value, unknown=unknown, safe=not unknown and value['state']=='MAINTENANCE')
    def safe():
        seen = observe()
        if seen['unknown']:
            raise DeploymentDenied('MAINTENANCE_INSPECTION_REJECTED')
        return seen
    host = SimpleNamespace(control=control, lock_path=tmp_path/'deploy.lock', plan={'schedules':{}},
        sources=SimpleNamespace(baseline=lambda:check('source')),
        schedules=SimpleNamespace(frozen=lambda _:check('schedule')), protections=lambda:None, safe=safe)
    monkeypatch.setattr(recovery,'HostDeployment',lambda *args:host)
    monkeypatch.setattr(recovery,'settings',SimpleNamespace(default_output_dir=tmp_path))
    monkeypatch.setattr(recovery,'inspection',observe)
    if failure:
        with pytest.raises((DeploymentDenied, OSError, sqlite3.DatabaseError, ValueError)):
            recovery.recover(directory)
        assert dal.PipelineDB.repair_snapshot(path) == before
        assert not (directory/'orphan-recovery.json').exists()
    else:
        result = recovery.recover(directory)
        assert result['safe'] and result['maintenance']=='MAINTENANCE'
        assert control.status()['version']==9
        assert result['status']=='FAILED' and result['retry_count']==0
        assert (directory/'orphan-recovery.json').is_file()
        assert (directory/'before-orphan-recovery-backup.json').is_file()
        with pytest.raises(DeploymentDenied, match='RECOVERY_ALREADY_ATTEMPTED'):
            recovery.recover(directory)


@pytest.mark.parametrize('failure', [None,'initial','adopt','start','resume'])
def test_continuation_never_advances_after_unverified_step(tmp_path, monkeypatch, failure):
    module = sys.modules['continue_stopped_deployment']
    (tmp_path/'plan.json').write_text('{"supersedes":"original-failed-plan"}')
    actions = []
    def preflight(step):
        if failure == 'initial':
            raise DeploymentDenied('WORKERS_NOT_STOPPED')
    def verify(step, result):
        if step == failure:
            raise DeploymentDenied('POSTCONDITION_FAILED')
    def action(step):
        actions.append(step)
        return {'ok':True}
    host = SimpleNamespace(lock_path=tmp_path/'lock', preflight=preflight, action=action,
        verify=verify, final_status=lambda:None)
    monkeypatch.setattr(module,'HostDeployment',lambda *args:host)
    if failure:
        with pytest.raises(DeploymentDenied):
            module.continue_stopped(tmp_path)
        expected = [] if failure=='initial' else list(module.STEPS[:module.STEPS.index(failure)+1])
        assert actions == expected
    else:
        result = module.continue_stopped(tmp_path)
        assert result['state']=='COMPLETE' and actions==list(module.STEPS)
        with pytest.raises(DeploymentDenied, match='CONTINUATION_ALREADY_ATTEMPTED'):
            module.continue_stopped(tmp_path)

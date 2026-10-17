"""长期阶段真实文件/数据库迁移与旧回执兼容；不连接Cloud或修改宿主调度。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 0.5.0 | 2026-10-15 | Codex | LONG_TERM原生采用、重启回读、账本漂移和旧回执 |
"""
from copy import deepcopy
from datetime import timedelta
import sqlite3
import time

import pytest
from config.settings import Settings, settings
from config.keyword_rollout import phase_values, transition, protection_values
from video_processing.core.deployment import DeploymentDenied, digest, write_json, read_json, STEPS
from video_processing.core.keyword_rollout import KeywordTransition, verify_loaded, values
from video_processing.core.maintenance import gate
from video_processing.db.database import PipelineDB
from tests.topic_candidate_fixtures import tracker, topic, run
from tests.unit.test_keyword_rollout_contract import evidence
from tests.unit.test_keyword_long_term import historical


@pytest.fixture
def long_rollout(tracker,tmp_path,monkeypatch):
    manual=run(tracker)
    tracker.clock.advance(minutes=16)
    tracker.config.topic_scheduler_enabled=True
    selected=topic(tracker,query='another event')
    tracker.schedule(selected['id'],selected['version'],True,'test')
    tracker.tick(verify_runtime=False)
    scheduled=next(j for j in tracker.db.topic_jobs() if j['kind']=='SCHEDULED')
    tracker.clock.advance(hours=4)
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('UPDATE topic_definitions SET next_run_at=?',((tracker.clock()+timedelta(hours=4)).isoformat(),))
    tracker.tick(verify_runtime=False)
    refresh=next(j for j in tracker.db.topic_jobs() if j['kind']=='REFRESH')
    historical(tracker,tracker.clock())
    output=tmp_path/'output';output.mkdir()
    PipelineDB.maintenance_backup(tracker.db.db_path,output/'pipeline.db')
    monkeypatch.setattr(Settings,'default_output_dir',property(lambda self:output))
    monkeypatch.setattr(settings,'topic_rollout_path',tmp_path/'keyword-rollout.json')
    monkeypatch.setattr(settings,'_topic_rollout_error',False)
    monkeypatch.setattr(settings,'enable_market_hours_guard',True)
    proof=evidence();proof.update(observed_at=time.time(),trial_job_ids=[manual['id']],
        scheduled_job_ids=[scheduled['id']],refresh_job_ids=[refresh['id']],project='isolated-project')
    previous_dir=tmp_path/'previous'
    previous_transition=transition(phase_values('SCHEDULED','isolated-project'),'ADMISSION',proof,time.time())
    for key,value in phase_values('ADMISSION','isolated-project').items():monkeypatch.setattr(settings,key,value)
    protections=dict(protection_values(settings),**phase_values('SCHEDULED','isolated-project'))
    previous=dict(schema=1,id='previous',root=str(settings.project_root),protections=protections,
                  keyword_transition=previous_transition)
    write_json(previous_dir/'plan.json',previous)
    write_json(previous_dir/'journal.json',dict(schema=1,plan=digest(previous),done=list(STEPS),pending=None,state='COMPLETE'))
    record=dict(transition=previous_transition,deployment_id='previous',directory=str(previous_dir))
    write_json(settings.topic_rollout_path,record)
    monkeypatch.setattr(settings,'_topic_rollout_record',record)
    assert verify_loaded(settings,complete=True)
    directory=tmp_path/'long-term'
    plan=dict(schema=1,id='long-term',root=str(settings.project_root),protections=protection_values(settings),
        keyword_profile_before=settings.topic_rollout_snapshot(),
        keyword_transition=transition(values(settings),'LONG_TERM',proof,time.time()))
    adapter=KeywordTransition(plan,directory,settings)
    plan['keyword_job_proof']=adapter.job_proof(planning=True)
    write_json(directory/'plan.json',plan)
    write_json(directory/'journal.json',dict(schema=1,plan=digest(plan),done=list(STEPS[:4]),pending='adopt',state='RUNNING'))
    gate().enter('长期阶段隔离验收')
    return adapter,plan,directory,output/'pipeline.db'


def test_native_long_term_adopt_restart_preserves_ledger_and_all_guards(long_rollout):
    adapter,plan,directory,database=long_rollout
    before=PipelineDB(database).keyword_admission_ledger()
    adapter.apply()
    assert values(settings)==phase_values('LONG_TERM','isolated-project')
    assert PipelineDB(database).keyword_admission_ledger()==before
    assert plan['keyword_job_proof']['_admission_ledger']==before
    loaded=Settings(_env_file=None,topic_rollout_path=settings.topic_rollout_path,
                    **{k:v for k,v in protection_values(settings).items() if k not in values(settings)})
    with pytest.raises(DeploymentDenied,match='DEPLOYMENT_INCOMPLETE'):verify_loaded(loaded,complete=True)
    journal=read_json(directory/'journal.json');journal.update(done=list(STEPS),pending=None,state='COMPLETE')
    write_json(directory/'journal.json',journal)
    assert verify_loaded(loaded,complete=True)
    assert protection_values(loaded)==dict(plan['protections'],**plan['keyword_transition']['after'])


def test_ledger_drift_since_plan_stops_before_profile_write(long_rollout):
    adapter,plan,directory,database=long_rollout
    before=read_json(settings.topic_rollout_path)
    with sqlite3.connect(database) as c:c.execute("UPDATE keyword_admissions SET score=99")
    with pytest.raises(DeploymentDenied,match='KEYWORD_JOB_PROOF_DRIFT'):adapter.apply()
    assert read_json(settings.topic_rollout_path)==before
    assert not (directory/'keyword-profile-before.json').exists()

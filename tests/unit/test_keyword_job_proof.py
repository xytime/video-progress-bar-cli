"""真实 SQLite 作业证据链，官方响应使用隔离适配器，不连接生产。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-14 | Codex | 缺失、失败、项目/评分漂移和自然刷新反例 |
"""
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3

import pytest
from video_processing.core.deployment import DeploymentDenied
from video_processing.core.keyword_job_proof import job_proof
from tests.topic_candidate_fixtures import tracker, topic, run


def manual_case(tracker):
    prior = dict(transition=dict(target='TRIAL', created_at=tracker.clock().timestamp()-1))
    job = run(tracker)
    assert job['state'] == 'COMPLETE'
    transition = dict(source='TRIAL', target='MANUAL', evidence=dict(project='isolated-project',
                      trial_job_ids=[job['id']], scheduled_job_ids=[], refresh_job_ids=[]))
    return transition, prior, job['id']


def check(tracker, transition, prior):
    return job_proof(tracker.db, transition, tracker.config, prior, tracker.clock().timestamp())


def test_successful_real_dal_snapshot_binds_budget_and_score(tracker):
    transition, prior, job_id = manual_case(tracker)
    proof = check(tracker, transition, prior)
    assert proof[job_id]['snapshot']['rows'][0]['score'] is not None
    assert proof[job_id]['budget'] == [dict(project='isolated-project',bucket='general',units=1),
                                      dict(project='isolated-project',bucket='search',units=1)]
    # 后续候选重评分不能改写已发生作业的原快照。
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('UPDATE topic_candidates SET score=99')
    assert check(tracker, transition, prior) == proof


@pytest.mark.parametrize('change,code', [
    ('missing','KEYWORD_JOB_EVIDENCE_MISSING'), ('failed','KEYWORD_JOB_NOT_SUCCESSFUL'),
    ('kind','KEYWORD_JOB_NOT_SUCCESSFUL'), ('project','KEYWORD_JOB_BUDGET_MISMATCH'),
    ('budget','KEYWORD_JOB_REQUESTS_MISSING'), ('snapshot','KEYWORD_JOB_EVIDENCE_MISSING'),
    ('score','KEYWORD_JOB_SCORE_MISMATCH'), ('empty','KEYWORD_JOB_RESULTS_MISSING'),
    ('old_stage','KEYWORD_JOB_PRECEDES_STAGE'), ('future','KEYWORD_JOB_TIME_INVALID'),
])
def test_identifiers_do_not_replace_actual_evidence(tracker, change, code):
    transition, prior, job_id = manual_case(tracker)
    with sqlite3.connect(tracker.db.db_path) as c:
        if change == 'missing': transition['evidence']['trial_job_ids'] = ['a'*32]
        elif change == 'failed': c.execute("UPDATE topic_jobs SET state='FAILED'")
        elif change == 'kind': c.execute("UPDATE topic_jobs SET kind='SCHEDULED'")
        elif change == 'project': c.execute("UPDATE topic_budget SET project='another-project'")
        elif change == 'budget': c.execute("DELETE FROM topic_budget WHERE bucket='general'")
        elif change == 'snapshot': c.execute('DELETE FROM keyword_job_evidence')
        elif change == 'old_stage': prior['transition']['created_at'] = tracker.clock().timestamp()+1
        elif change == 'future': c.execute('UPDATE topic_jobs SET ended_at=?', ((tracker.clock()+timedelta(seconds=1)).isoformat(),))
        else:
            snapshot=json.loads(c.execute('SELECT snapshot FROM keyword_job_evidence').fetchone()[0])
            if change == 'score': snapshot['rows'][0]['score']=99
            else: snapshot['rows']=[]
            c.execute('UPDATE keyword_job_evidence SET snapshot=?', (json.dumps(snapshot),))
    with pytest.raises(DeploymentDenied, match=code): check(tracker, transition, prior)


def test_trial_proof_chain_cannot_switch_job_ids(tracker):
    transition, prior, job_id = manual_case(tracker)
    prior=dict(transition=dict(target='MANUAL',created_at=tracker.clock().timestamp(),
                              evidence=deepcopy(transition['evidence'])))
    transition.update(source='MANUAL',target='SCHEDULED')
    assert check(tracker, transition, prior)
    transition['evidence']['trial_job_ids']=['a'*32]
    with pytest.raises(DeploymentDenied, match='KEYWORD_TRIAL_CHAIN_MISMATCH'): check(tracker,transition,prior)


def test_deployment_adapter_binds_actual_snapshot_and_rejects_drift(tracker, tmp_path):
    from types import SimpleNamespace
    from video_processing.db.database import PipelineDB
    from video_processing.core.keyword_rollout import KeywordTransition
    transition, prior, job_id = manual_case(tracker)
    output = tmp_path / 'deployment-output'
    output.mkdir()
    database = output / 'pipeline.db'
    PipelineDB.maintenance_backup(tracker.db.db_path, database)
    config = SimpleNamespace(**vars(tracker.config), default_output_dir=output, _topic_rollout_record=prior)
    plan = dict(keyword_transition=transition)
    adapter = KeywordTransition(plan, tmp_path/'plan', config)
    plan['keyword_job_proof'] = adapter.job_proof(planning=True)
    assert adapter.job_proof() == plan['keyword_job_proof']
    with sqlite3.connect(database) as c:
        c.execute("UPDATE topic_budget SET units=units+1 WHERE bucket='general'")
    with pytest.raises(DeploymentDenied, match='KEYWORD_JOB_PROOF_DRIFT'): adapter.job_proof()


def test_missing_snapshot_is_not_backfilled_from_current_candidate(tracker):
    transition, prior, job_id = manual_case(tracker)
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('DELETE FROM keyword_job_evidence')
    type(tracker.db)(tracker.db.db_path)
    with pytest.raises(DeploymentDenied, match='KEYWORD_JOB_EVIDENCE_MISSING'): check(tracker,transition,prior)


def test_scheduled_search_natural_refresh_and_admission_proof(tracker):
    transition, _, manual_id = manual_case(tracker)
    tracker.clock.advance(minutes=16)
    tracker.config.topic_scheduler_enabled=True
    t=topic(tracker, query='another event')
    t=tracker.schedule(t['id'],t['version'],True,'test')
    prior=dict(transition=dict(target='SCHEDULED',created_at=tracker.clock().timestamp(),
                              evidence=deepcopy(transition['evidence'])))
    assert tracker.tick(verify_runtime=False)=='SEARCH'
    scheduled=next(j for j in tracker.db.topic_jobs() if j['kind']=='SCHEDULED')
    tracker.clock.advance(hours=4)
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('UPDATE topic_definitions SET next_run_at=?',((tracker.clock()+timedelta(hours=4)).isoformat(),))
    assert tracker.tick(verify_runtime=False)=='REFRESH_OR_ADMISSION'
    refresh=next(j for j in tracker.db.topic_jobs() if j['kind']=='REFRESH')
    transition.update(source='SCHEDULED',target='ADMISSION')
    transition['evidence'].update(scheduled_job_ids=[scheduled['id']],refresh_job_ids=[refresh['id']])
    assert len(check(tracker,transition,prior))==3
    # 时间链不完整不能借一个成功详情作业宣称自然刷新验收。
    with sqlite3.connect(tracker.db.db_path) as c:
        snapshot=json.loads(c.execute('SELECT snapshot FROM keyword_job_evidence WHERE job_id=?',(refresh['id'],)).fetchone()[0])
        snapshot['rows'][0]['key']='unrelated-key'
        c.execute('UPDATE keyword_job_evidence SET snapshot=? WHERE job_id=?',(json.dumps(snapshot),refresh['id']))
    with pytest.raises(DeploymentDenied,match='KEYWORD_NATURAL_REFRESH_MISSING'): check(tracker,transition,prior)

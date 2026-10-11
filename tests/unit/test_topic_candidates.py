"""A01–A19/A21：临时真实 SQLite、故障、预算与线程/进程并发验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-11 | Codex | v0.2 隔离验收，不访问真实搜索或主库 |
"""
import json
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from tests.topic_candidate_fixtures import tracker, topic, run, decision, video
from video_processing.core.topic_candidates import TopicError, metadata, quota_day, eligibility, content_version
from video_processing.db.database import PipelineDB
from video_processing.topic_tracker.service import TopicTracker
from video_processing.utils.topic_search import SearchFailure, ExistingTopicRules


def rows(service):
    return service.candidates()["candidates"]


def test_a01_persist_and_no_automatic_search(tracker):
    created = topic(tracker)
    again = TopicTracker(PipelineDB(tracker.db.db_path), tracker.config, tracker.adapter, tracker.rules, clock=tracker.clock)
    assert again.view()["topics"][0] == tracker.view()["topics"][0]
    assert again.view()["topics"][0]["id"] == created["id"]
    assert tracker.adapter.calls == [] and rows(again) == []


@pytest.mark.parametrize("fields", [dict(name=""),dict(name="x"*41),dict(query=" "),dict(query="x"*121),dict(category="娱乐"),dict(valid_days=0),dict(valid_days=31),dict(valid_days=True),dict(lookback_days=6)])
def test_a02_invalid_fields_atomic(tracker, fields):
    data=dict(name="产业",query="energy",category="科技产业",lookback_days=7,valid_days=7)
    data.update(fields)
    before=tracker.db.topic_audit_records()
    with pytest.raises(TopicError): tracker.db.topic_save(data,"test",tracker.clock())
    assert not tracker.db.topic_list(tracker.clock()) and tracker.db.topic_audit_records()==before


def test_a02_capacity_normalization_and_resume(tracker):
    a=topic(tracker, " ENERGY  industry ")
    with pytest.raises(TopicError,match="相同"): topic(tracker,"ｅｎｅｒｇｙ industry")
    for n in range(9): topic(tracker,f"query {n}")
    with pytest.raises(TopicError,match="10"): topic(tracker,"eleventh")
    paused=tracker.db.topic_transition(a['id'],a['version'],'PAUSED','test',tracker.clock())
    topic(tracker,"eleventh")
    with pytest.raises(TopicError,match="10"): tracker.db.topic_transition(a['id'],paused['version'],'ACTIVE','test',tracker.clock())


def test_a03_single_page_and_exact_identity(tracker):
    tracker.adapter.items=[video(n) for n in range(1,31)]
    job=run(tracker)
    assert job['state']=='COMPLETE' and job['counts']==dict(new=25,duplicate=0,restricted=0)
    assert len(rows(tracker))==25
    assert [r[0] for r in tracker.adapter.calls]==['search','details']
    assert len(tracker.adapter.calls[1][1])==25
    assert {r['metadata']['youtube_id'] for r in rows(tracker)} == {f'{n:011d}' for n in range(1,26)}


@pytest.mark.parametrize('failure', [None,SearchFailure('NETWORK','request failed'),RuntimeError('secret must not appear')])
def test_a04_zero_and_failure_distinct(tracker, failure):
    tracker.adapter.items=[];tracker.adapter.search_error=failure
    job=run(tracker)
    assert job['state']==('COMPLETE' if failure is None else 'FAILED')
    assert 'secret' not in json.dumps(job)
    assert tracker.db.topic_budget('isolated-project',tracker.clock())['search']==1
    assert not rows(tracker)


def test_a05_dedup_across_topics_and_existing_slices(tracker):
    run(tracker,topic(tracker,'first'))
    row=rows(tracker)[0];tracker.decide(row['key'],decision(row),'test')
    run(tracker,topic(tracker,'second'))
    row=rows(tracker)[0]
    assert len(rows(tracker))==1 and len(row['topics'])==2 and row['state']=='SAVED'
    tracker.db.add_video('00000000001','Existing parent','UC-isolated',score=90)
    tracker.db.add_video('00000000001','Existing slice','UC-isolated',slice_index=1)
    before=tracker.db.get_video_by_youtube_id('00000000001')
    run(tracker,topic(tracker,'third'))
    row=rows(tracker)[0]
    assert row['pipeline_present'] and len(row['pipeline_states'])==2 and not row['can_save']
    with pytest.raises(TopicError): tracker.decide(row['key'],decision(row),'test')
    assert tracker.db.get_video_by_youtube_id('00000000001')==before


def test_a06_saved_stats_and_content_versions(tracker):
    t=topic(tracker);run(tracker,t);row=rows(tracker)[0]
    tracker.decide(row['key'],decision(row),'test');row=rows(tracker)[0];version=row['content_version']
    tracker.clock.advance(minutes=16);tracker.adapter.items[0]['statistics']['viewCount']='900';run(tracker,t)
    row=rows(tracker)[0];assert row['state']=='SAVED' and not row['needs_review'] and row['content_version']==version
    tracker.clock.advance(minutes=16);tracker.adapter.items[0]['snippet']['title']='Updated industrial source';run(tracker,t)
    row=rows(tracker)[0];assert row['state']=='SAVED' and row['needs_review']
    tracker.decide(row['key'],decision(row),'test');assert not rows(tracker)[0]['needs_review']
    tracker.rules.fingerprint='rules-2';row=rows(tracker)[0];assert row['needs_review']


def test_a07_rejected_survives_archive_and_rediscovery(tracker):
    t=topic(tracker);run(tracker,t);row=rows(tracker)[0]
    tracker.decide(row['key'],decision(row,'REJECTED','不相关'),'test')
    tracker.db.topic_transition(t['id'],t['version'],'ARCHIVED','test',tracker.clock())
    run(tracker,topic(tracker));row=rows(tracker)[0]
    assert row['state']=='REJECTED' and not row['can_save']
    with pytest.raises(TopicError,match='不能恢复'): tracker.decide(row['key'],decision(row,'NEW'),'test')


@pytest.mark.parametrize('duration,state', [('PT179S','RESTRICTED'),('PT180S','CHECKABLE'),('PT1800S','CHECKABLE'),('PT1801S','RESTRICTED'),('unknown','INCOMPLETE')])
def test_a08_duration_boundary(tracker,duration,state):
    tracker.adapter.items=[video(duration=duration)];run(tracker)
    row=rows(tracker)[0];assert row['eligibility']==state and row['can_save']==(state=='CHECKABLE')


@pytest.mark.parametrize('live', ['live','upcoming'])
def test_a08_live_and_missing_stats(tracker,live):
    tracker.adapter.items[0]['snippet']['liveBroadcastContent']=live
    tracker.adapter.items[0]['statistics']={};run(tracker);row=rows(tracker)[0]
    assert row['eligibility']=='UNAVAILABLE' and row['metadata']['views'] is None and row['metadata']['language'] is None


def test_a09_fail_closed_rules_and_blacklist(tracker):
    tracker.rules.fail=True;run(tracker);row=rows(tracker)[0]
    assert row['eligibility']=='INCOMPLETE'
    with pytest.raises(TopicError): tracker.decide(row['key'],decision(row),'test')
    tracker.rules.fail=False;tracker.db.add_to_blacklist('00000000001','original decision')
    row=rows(tracker)[0];assert row['eligibility']=='RESTRICTED' and not row['can_save']
    assert tracker.db.is_blacklisted('00000000001')


def test_a09_current_real_rule_package(tracker):
    from video_processing.censor_engine import dump_default_rules
    rules=ExistingTopicRules()
    assert rules.version()
    default=dump_default_rules()
    # 用真实词库中的已知 P0 词，不修改或绕过现有规则。
    p0=default['blocklist']['P0']
    word=p0['zh'][0] if isinstance(p0,dict) else p0[0]
    meta=metadata('00000000001',video(title=str(word)))
    assert rules.check(meta)


def test_a10_kernel_lock_duplicate_and_no_queue(tracker):
    t=topic(tracker);other=topic(tracker,'other');tracker.adapter.release=threading.Event()
    first=tracker.start(t['id'],t['version'],'same-request-identifier','test');assert tracker.adapter.started.wait(1)
    assert tracker.start(t['id'],t['version'],'same-request-identifier','test')['id']==first['id']
    peer=TopicTracker(PipelineDB(tracker.db.db_path),tracker.config,tracker.adapter,tracker.rules,clock=tracker.clock)
    with pytest.raises(TopicError,match='正在进行'): peer.start(other['id'],other['version'],'other-request-identifier','test')
    tracker.adapter.release.set();tracker.wait(3)
    assert tracker.db.topic_budget('isolated-project',tracker.clock())['search']==1


def test_a10_budget_atomic_across_threads_and_processes(tracker):
    t=topic(tracker);job=tracker.db.topic_create_job(t['id'],t['version'],'budget-concurrent-test','test',tracker.clock())
    def reserve(_):
        try: tracker.db.topic_reserve(job['id'],'isolated-project','search',1,tracker.clock());return True
        except TopicError:return False
    with ThreadPoolExecutor(max_workers=5) as pool: assert sum(pool.map(reserve,range(5)))==1
    script="from video_processing.db.database import PipelineDB; from datetime import datetime; import sys; d=PipelineDB(sys.argv[1]); d.topic_reserve(sys.argv[2],'isolated-project','general',1,datetime.fromisoformat(sys.argv[3]))"
    processes=[subprocess.Popen([sys.executable,'-c',script,tracker.db.db_path,job['id'],tracker.clock().isoformat()],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
    results=[p.communicate(timeout=10) for p in processes]
    assert sum(p.returncode==0 for p in processes)==1
    assert tracker.db.topic_budget('isolated-project',tracker.clock())['general']==1


@pytest.mark.parametrize('date,day', [('2026-10-11T06:59:59+00:00','2026-10-10'),('2026-10-11T07:00:00+00:00','2026-10-11'),('2026-11-01T08:30:00+00:00','2026-11-01'),('2026-11-01T09:30:00+00:00','2026-11-01'),('2026-03-08T07:59:59+00:00','2026-03-07')])
def test_a11_pt_day_and_dst(date,day): assert quota_day(datetime.fromisoformat(date))==day


def test_a11_retry_counts_and_restart_preserves_budget(tracker):
    tracker.adapter.detail_error=SearchFailure('NETWORK','timeout',retryable=True)
    job=run(tracker);assert job['state']=='PARTIAL' and not rows(tracker)
    assert [c[0] for c in tracker.adapter.calls]==['search','details','details']
    assert tracker.db.topic_budget('isolated-project',tracker.clock())['general']==2
    peer=TopicTracker(PipelineDB(tracker.db.db_path),tracker.config,tracker.adapter,tracker.rules,clock=tracker.clock)
    assert peer.view()['budget']['general']==2


@pytest.mark.parametrize('field,value,code', [('topic_search_enabled',False,'SEARCH_CLOSED'),('topic_quota_verified',False,'QUOTA_UNVERIFIED'),('topic_quota_project','','QUOTA_UNVERIFIED'),('enable_market_hours_guard',False,'GUARD_DISABLED')])
def test_a12_configuration_blocks_without_requests(tracker,field,value,code):
    t=topic(tracker);setattr(tracker.config,field,value)
    with pytest.raises(TopicError) as caught: tracker.start(t['id'],t['version'],'configuration-request','test')
    assert caught.value.code==code and not tracker.adapter.calls


def test_a12_missing_api_and_budget_exhaustion(tracker):
    t=topic(tracker);tracker.adapter.has_key=False
    with pytest.raises(TopicError,match='API'): tracker.start(t['id'],t['version'],'missing-api-request','test')
    tracker.adapter.has_key=True;tracker.config.topic_search_daily_limit=1
    run(tracker,t);job=run(tracker,topic(tracker,'second'))
    assert job['state']=='FAILED' and job['code']=='BUDGET' and len(tracker.adapter.calls)==2


@pytest.mark.parametrize('stop', ['pause','archive','off','guard'])
def test_a13_a14_stop_in_flight_and_no_replay(tracker,stop):
    t=topic(tracker);tracker.adapter.release=threading.Event()
    job=tracker.start(t['id'],t['version'],'stop-inflight-request','test');assert tracker.adapter.started.wait(1)
    if stop in ('pause','archive'): tracker.db.topic_transition(t['id'],t['version'],'PAUSED' if stop=='pause' else 'ARCHIVED','test',tracker.clock())
    elif stop=='off': tracker.mode('OFF',tracker.db.topic_control()['version'],'test')
    else: tracker.config.is_us_market_guard_window=lambda now:True
    tracker.adapter.release.set();tracker.wait(3)
    assert tracker.db.topic_jobs(idem=job['idempotency'])[0]['state']=='INTERRUPTED'
    assert len(tracker.adapter.calls)==1 and not rows(tracker)
    tracker.view();assert len(tracker.adapter.calls)==1


def test_a13_future_guard_shortens_deadline(tracker):
    boundary=tracker.clock()+timedelta(seconds=4)
    tracker.config.is_us_market_guard_window=lambda now:now>=boundary
    assert run(tracker)['state']=='COMPLETE'
    assert all(call[2]<=3.5 for call in tracker.adapter.calls)


def test_a14_crashed_job_recovery_keeps_reservation(tracker):
    t=topic(tracker);job=tracker.db.topic_create_job(t['id'],t['version'],'crash-recovery-request','test',tracker.clock())
    tracker.db.topic_reserve(job['id'],'isolated-project','search',20,tracker.clock())
    peer=TopicTracker(PipelineDB(tracker.db.db_path),tracker.config,tracker.adapter,tracker.rules,clock=tracker.clock)
    assert peer.view()['jobs'][0]['state']=='INTERRUPTED' and peer.view()['budget']['search']==1
    assert not tracker.adapter.calls


def test_a18_old_version_and_atomic_audit_rollback(tracker):
    run(tracker);row=rows(tracker)[0]
    tracker.decide(row['key'],decision(row),'test')
    with pytest.raises(TopicError,match='已更新'):tracker.decide(row['key'],decision(row,'REJECTED','不相关'),'test')
    row=rows(tracker)[0];before=tracker.db.topic_audit_records()
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute("CREATE TRIGGER fail_topic_audit BEFORE INSERT ON topic_audit BEGIN SELECT RAISE(ABORT,'fault'); END")
    with pytest.raises(sqlite3.IntegrityError):tracker.decide(row['key'],decision(row,'REJECTED','其他'),'test')
    assert rows(tracker)[0]['state']=='SAVED' and tracker.db.topic_audit_records()==before


def test_a18_database_busy_is_bounded(tracker):
    import time
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('BEGIN IMMEDIATE');started=time.monotonic()
        with pytest.raises(TopicError,match='数据库忙'):topic(tracker)
        assert time.monotonic()-started<2.8


def test_a19_expiry_off_and_rejection_tombstone(tracker):
    t=topic(tracker);run(tracker,t);row=rows(tracker)[0]
    tracker.decide(row['key'],decision(row,'REJECTED','其他'),'test')
    tracker.mode('OFF',tracker.db.topic_control()['version'],'test');tracker.clock.advance(days=30)
    tracker.maintenance();assert not rows(tracker)
    stored=tracker.db.topic_candidate(row['key']);assert stored['youtube_id'] is None and stored['metadata'] is None
    assert 'Energy industry' not in json.dumps(tracker.db.topic_audit_records())
    tracker.mode('DISCOVERY_ONLY',tracker.db.topic_control()['version'],'test')
    run(tracker,topic(tracker,'new topic'));assert rows(tracker)[0]['state']=='REJECTED'


def test_a21_off_main_queue_and_old_dal_compatible(tracker):
    tracker.mode('OFF',tracker.db.topic_control()['version'],'test')
    tracker.db.add_video('old-pending','Old existing task','UC-safe',score=90)
    before=tracker.db.get_video_by_youtube_id('old-pending')
    topic(tracker);tracker.view();tracker.candidates()
    assert tracker.db.get_video_by_youtube_id('old-pending')==before
    assert tracker.db.get_video_by_youtube_id('00000000001') is None
    assert not tracker.adapter.calls


def test_pure_domain_and_entry_import_no_settings_or_effects(tmp_path):
    script="import sys; from pathlib import Path; before=set(Path('.').rglob('*')); import video_processing.core.topic_candidates; import video_processing.topic_tracker; assert 'config.settings' not in sys.modules; assert before==set(Path('.').rglob('*'))"
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr

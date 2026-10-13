"""v0.4：真实 SQLite、原子执行/准入及受控 YouTube 响应的闭环验收。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import sqlite3

import pytest
from config.settings import settings
from video_processing.core.topic_candidates import TopicError
from video_processing.scoring import compute_policy_score, compute_auto_score
from video_processing.utils.topic_search import SearchItems, SearchFailure
from tests.topic_candidate_fixtures import tracker, topic, run, video, decision


def rows(service):
    return service.candidates()['candidates']


def enable(tracker, **fields):
    tracker.config.topic_scheduler_enabled=True
    t=topic(tracker, **fields)
    return tracker.schedule(t['id'],t['version'],True,'test')


def hot(tracker):
    tracker.adapter.items[0]['statistics']=dict(viewCount='3000',likeCount='150')


def admit(tracker, monkeypatch):
    tracker.config.topic_admission_enabled=True
    monkeypatch.setattr(settings,'topic_admission_enabled',True)
    tracker.admission(True,tracker.db.keyword_control()['version'],'test')


def test_scheduled_cold_refresh_hot_admission_and_close(tracker,monkeypatch):
    t=enable(tracker)
    assert tracker.tick(verify_runtime=False)=='SEARCH'
    assert rows(tracker)[0]['collection']['state']=='OBSERVING'
    assert tracker.tick(verify_runtime=False)=='REFRESH_OR_ADMISSION'
    assert len(tracker.adapter.calls)==2
    # 不再次搜索，直接验证周期详情刷新使新报道成长。
    tracker.clock.advance(hours=4)
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('UPDATE topic_definitions SET next_run_at=?',( (tracker.clock()+timedelta(hours=4)).isoformat(),))
    hot(tracker)
    assert tracker.tick(verify_runtime=False)=='REFRESH_OR_ADMISSION'
    row=rows(tracker)[0]
    assert row['collection']['state']=='QUALIFIED' and row['score']>=75
    assert tracker.db.get_video_by_youtube_id('00000000001') is None
    admit(tracker,monkeypatch)
    tracker.tick(verify_runtime=False)
    main=tracker.db.get_video_by_youtube_id('00000000001')
    assert main['source']=='KEYWORD' and not main['is_manually_scored'] and main['score']>=75
    assert tracker.db.get_high_score_pending_videos() and tracker.db.get_high_score_preparation_candidates()
    tracker.admission(False,tracker.db.keyword_control()['version'],'test')
    assert not tracker.db.get_high_score_pending_videos()
    assert not tracker.db.get_high_score_preparation_candidates()
    assert not tracker.db.claim_video_for_processing('00000000001')
    assert not tracker.db.claim_video_for_publication('00000000001',123)
    # 来源与手工标志变更不能绕过已经建立的关键词准入归因。
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute("UPDATE processed_videos SET source='MANUAL',is_manually_scored=1,score=100")
    assert not tracker.db.claim_video_for_processing('00000000001')
    assert not tracker.db.keyword_processing_allowed('00000000001')


def test_parallel_ticks_one_search_restart_no_catchup(tracker):
    enable(tracker)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _:tracker.tick(verify_runtime=False),range(4)))
    assert sum(x[0]=='search' for x in tracker.adapter.calls)==1
    tracker.clock.advance(hours=20)
    tracker.tick(verify_runtime=False)
    assert sum(x[0]=='search' for x in tracker.adapter.calls)==2
    tracker.tick(verify_runtime=False)
    assert sum(x[0]=='search' for x in tracker.adapter.calls)==2


def test_unregistered_scheduler_rejected(tracker):
    enable(tracker)
    assert tracker.tick()=='RUNTIME_UNVERIFIED'
    assert not tracker.adapter.calls


def test_closed_flags_and_expiry(tracker):
    t=topic(tracker)
    with pytest.raises(TopicError,match='尚未开放'):tracker.schedule(t['id'],t['version'],True,'test')
    tracker.config.topic_scheduler_enabled=True
    t=tracker.schedule(t['id'],t['version'],True,'test')
    tracker.config.topic_search_enabled=False
    assert tracker.tick(verify_runtime=False)=='SEARCH_CLOSED'
    assert not tracker.adapter.calls
    tracker.config.topic_search_enabled=True
    tracker.clock.advance(days=8)
    tracker.tick(verify_runtime=False)
    assert not tracker.adapter.calls


def test_default_new_rule_and_legacy_duration_migration(tracker):
    v=tracker.db.topic_save(dict(name='报道',query='news',category='健康科学'),'test',tracker.clock())
    assert (v['lookback_days'],v['min_duration'],v['auto_enabled'])==(1,30,0)
    old=topic(tracker,'legacy')
    tracker.db.topic_initialize()
    assert tracker.db.topic_get(old['id'],tracker.clock())['min_duration']==180
    assert not tracker.db.keyword_control()['admission']


def test_coverage_and_nonwhitelist(tracker):
    enable(tracker)
    tracker.adapter.search=lambda *a,**kw:SearchItems([dict(id=dict(videoId='00000000001'))],True)
    tracker.tick(verify_runtime=False)
    assert tracker.db.topic_jobs()[0]['has_more']==1
    assert rows(tracker)[0]['metadata']['channel_id']=='UC-isolated'
    with sqlite3.connect(tracker.db.db_path) as c:assert not c.execute('SELECT 1 FROM recommended_channels').fetchone()


@pytest.mark.parametrize('views,likes',[(1500,60),(2000,60),(1501,46),(0,0),(9999,600)])
def test_shared_score_boundaries(tracker,views,likes):
    assert compute_policy_score(dict(view_count=views,like_count=likes,channel_id='new'),tracker.config)==compute_auto_score(views,likes)


def test_existing_discovery_and_rejected_never_promoted(tracker,monkeypatch):
    enable(tracker);hot(tracker);tracker.tick(verify_runtime=False)
    tracker.db.add_video('00000000001','old','UC-isolated',source='DISCOVERY',score=0)
    admit(tracker,monkeypatch);tracker.tick(verify_runtime=False)
    main=tracker.db.get_video_by_youtube_id('00000000001')
    assert main['source']=='DISCOVERY' and main['score']==0
    assert rows(tracker)[0]['collection']['state']=='EXISTING'


def test_atomic_admission_race_and_stale(tracker,monkeypatch):
    t=enable(tracker);hot(tracker);tracker.tick(verify_runtime=False);admit(tracker,monkeypatch)
    row=tracker.db.keyword_admission_candidates(tracker.clock())[0]
    def do(_):
        return tracker.db.keyword_admit(row['key'],row['revision'],t['id'],t['version'],tracker.rules.version,tracker.config,tracker.clock())
    with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(do,range(3)))
    assert sum(r['result']=='ADMITTED' for r in results)==1
    tracker.db.topic_transition(t['id'],t['version'],'PAUSED','test',tracker.clock())
    with pytest.raises(TopicError):do(0)


def test_rejection_stale_stats_blacklist(tracker,monkeypatch):
    t=enable(tracker);hot(tracker);tracker.tick(verify_runtime=False);admit(tracker,monkeypatch)
    row=rows(tracker)[0]
    tracker.decide(row['key'],decision(row,state='REJECTED',reason='不相关'),'test')
    tracker.tick(verify_runtime=False)
    assert tracker.db.get_video_by_youtube_id('00000000001') is None


def test_admission_transaction_does_not_lower_keyword_score_line(tracker,monkeypatch):
    t=enable(tracker);tracker.tick(verify_runtime=False);admit(tracker,monkeypatch)
    tracker.config.auto_publish_channel_min_scores={'UC-isolated':0}
    row=rows(tracker)[0]
    with pytest.raises(TopicError,match='评分门槛'):
        tracker.db.keyword_admit(row['key'],row['revision'],t['id'],t['version'],tracker.rules.version,tracker.config,tracker.clock())
    assert tracker.db.get_video_by_youtube_id('00000000001') is None


def test_api_credentials_stop_automatic_retry(tracker):
    enable(tracker)
    tracker.adapter.search_error=SearchFailure('API_CREDENTIALS','invalid')
    tracker.tick(verify_runtime=False)
    tracker.clock.advance(hours=4)
    tracker.tick(verify_runtime=False)
    assert len(tracker.adapter.calls)==1


def test_three_rule_capacity(tracker):
    for n in range(3):enable(tracker,query=f'query{n}')
    t=topic(tracker,'fourth')
    with pytest.raises(TopicError,match='3'):tracker.schedule(t['id'],t['version'],True,'test')


def test_atomic_shared_budget_reserved_manual_and_details(tracker):
    t=enable(tracker)
    job=tracker.db.topic_create_job(t['id'],t['version'],'budget-auto','test',tracker.clock(),kind='SCHEDULED')
    def reserve(bucket,limit):
        try:tracker.db.topic_reserve(job['id'],'isolated-project',bucket,limit,tracker.clock());return True
        except TopicError as exc:assert exc.code=='BUDGET';return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(lambda _:reserve('search',20),range(25)))==18
        assert sum(pool.map(lambda _:reserve('general',40),range(45)))==40
    tracker.db.topic_finish_job(job['id'],'COMPLETE','OK',tracker.clock())
    tracker.clock.advance(minutes=16)
    job=tracker.db.topic_create_job(t['id'],t['version'],'budget-manual','test',tracker.clock())
    assert reserve('search',20) and reserve('search',20) and not reserve('search',20)
    assert tracker.db.topic_budget('isolated-project',tracker.clock())['search']==20


def test_real_role_fingerprint_and_maintenance_refusal(tracker,isolated_running_maintenance):
    from video_processing.core.maintenance_runtime import role_lease
    from video_processing.core.task_lease import TaskLease
    enable(tracker)
    with TaskLease(isolated_running_maintenance.path.with_suffix('.workers')/'queue-runner.lock',source_hash='wrong'):
        assert tracker.tick()=='RUNTIME_UNVERIFIED'
    assert not tracker.adapter.calls
    with role_lease('queue-runner'):
        assert tracker.tick()=='SEARCH'
    assert len(tracker.adapter.calls)==2
    isolated_running_maintenance.enter('隔离维护')
    tracker.clock.advance(hours=4)
    assert tracker.tick()=='MAINTENANCE'
    assert len(tracker.adapter.calls)==2


def test_old_schema_upgrade_keeps_rules_and_decisions(tracker):
    from video_processing.core.topic_candidates import digest
    t=topic(tracker);run(tracker,t)
    row=rows(tracker)[0];tracker.decide(row['key'],decision(row),'test')
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('UPDATE topic_definitions SET identity=?',(digest(['energy industry','科技产业',7]),))
        for name in ('language','min_duration','auto_enabled','next_run_at'):
            c.execute(f'ALTER TABLE topic_definitions DROP COLUMN {name}')
    tracker.db.topic_initialize()
    old=tracker.db.topic_get(t['id'],tracker.clock())
    assert old['min_duration']==180 and old['lookback_days']==7 and not old['auto_enabled']
    assert rows(tracker)[0]['state']=='SAVED'
    with pytest.raises(TopicError,match='已有相同'):
        topic(tracker)


def test_observation_limit_fairness_and_unknown_stats(tracker):
    from video_processing.core.topic_candidates import metadata
    t=enable(tracker)
    job=tracker.db.topic_create_job(t['id'],t['version'],'many-observations','test',tracker.clock())
    items=[tracker._evaluate(metadata(f'{i:011d}',video(i)),t) for i in range(1,202)]
    tracker.db.topic_store_results(job['id'],items,tracker.clock())
    tracker.db.keyword_score_results(job['id'],tracker.config,tracker.clock())
    tracker.db.topic_finish_job(job['id'],'COMPLETE','OK',tracker.clock())
    watching=tracker.db.keyword_observations(tracker.clock(),include_future=True)
    assert len(watching)==200
    all_keys={r['key'] for r in watching}
    with sqlite3.connect(tracker.db.db_path) as c:
        queued=next(r[0] for r in c.execute('SELECT key FROM topic_candidates') if r[0] not in all_keys)
    assert tracker.db.keyword_candidate_state(queued,tracker.config,tracker.clock(),observation_keys=all_keys)['state']=='WAIT_SCHEDULE'
    tracker.db.keyword_defer_refresh(watching,tracker.clock()+timedelta(hours=1))
    assert queued in {r['key'] for r in tracker.db.keyword_observations(tracker.clock(),include_future=True)}


@pytest.mark.parametrize('change',['blacklist','expired','stale','unknown','rules','paused'])
def test_admission_rechecks_current_boundaries(tracker,monkeypatch,change):
    t=enable(tracker);hot(tracker);tracker.tick(verify_runtime=False);admit(tracker,monkeypatch)
    r=tracker.db.keyword_admission_candidates(tracker.clock())[0]
    if change=='blacklist':tracker.db.add_to_blacklist('00000000001')
    elif change=='expired':tracker.clock.advance(days=4)
    elif change=='stale':tracker.clock.advance(hours=4)
    elif change=='rules':tracker.rules.fingerprint='changed'
    elif change=='paused':tracker.db.topic_transition(t['id'],t['version'],'PAUSED','test',tracker.clock())
    else:
        import json
        with sqlite3.connect(tracker.db.db_path) as c:
            meta=dict(r['metadata'],likes=None)
            c.execute('UPDATE topic_candidates SET metadata=? WHERE key=?',(json.dumps(meta),r['key']))
    with pytest.raises(TopicError):
        tracker.db.keyword_admit(r['key'],r['revision'],t['id'],t['version'],tracker.rules.version,tracker.config,tracker.clock())
    assert tracker.db.get_video_by_youtube_id('00000000001') is None


def test_cross_keyword_and_channel_race_preserves_one_task(tracker,monkeypatch):
    first=enable(tracker);hot(tracker);tracker.tick(verify_runtime=False)
    second=enable(tracker,query='other event');tracker.tick(verify_runtime=False)
    admit(tracker,monkeypatch)
    row=tracker.db.keyword_admission_candidates(tracker.clock())[0]
    def keyword():return tracker.db.keyword_admit(row['key'],row['revision'],row['topic_id'],row['topic_version'],tracker.rules.version,tracker.config,tracker.clock())
    def channel():return tracker.db.add_video('00000000001','channel discovery','UC-isolated',score=90,source='AUTO')
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(keyword);b=pool.submit(channel);a.result();b.result()
    with sqlite3.connect(tracker.db.db_path) as c:
        assert c.execute('SELECT COUNT(*) FROM processed_videos WHERE youtube_id=?',('00000000001',)).fetchone()[0]==1
        assert c.execute('SELECT COUNT(DISTINCT topic_id) FROM topic_hits').fetchone()[0]==2
    assert len(rows(tracker)[0]['topics'])==2


def test_missing_statistics_remain_unknown_after_refresh(tracker):
    enable(tracker);tracker.tick(verify_runtime=False)
    tracker.clock.advance(hours=4)
    tracker.adapter.items[0]['statistics'].pop('likeCount')
    tracker.tick(verify_runtime=False)
    row=rows(tracker)[0]
    assert row['metadata']['likes'] is None and row['score'] is None
    assert row['collection']['state']=='INCOMPLETE'


def test_maintenance_during_request_stops_details_and_admission(tracker,isolated_running_maintenance):
    import threading
    enable(tracker)
    tracker.adapter.release=threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(tracker.tick,verify_runtime=False)
        assert tracker.adapter.started.wait(2)
        isolated_running_maintenance.enter('在途有界排空')
        tracker.adapter.release.set();future.result()
    assert [x[0] for x in tracker.adapter.calls]==['search']
    assert isolated_running_maintenance.status()['active']==[]
    assert tracker.db.topic_jobs()[0]['code']=='MAINTENANCE'


@pytest.mark.parametrize('limit', [0, 1])
def test_trial_admission_limit_is_atomic_and_survives_restart(tracker, monkeypatch, limit):
    """不同候选并发只能消费一次累计额度；重新建 DAL 和跨日不退款。"""
    from video_processing.db.database import PipelineDB
    tracker.config.topic_admission_total_limit = limit
    tracker.adapter.items = [video(1), video(2)]
    for item in tracker.adapter.items:
        item['statistics'] = dict(viewCount='3000', likeCount='150')
    t = enable(tracker)
    tracker.tick(verify_runtime=False)
    admit(tracker, monkeypatch)
    candidates = tracker.db.keyword_admission_candidates(tracker.clock())
    assert len(candidates) == 2
    def attempt(row):
        try:
            return tracker.db.keyword_admit(row['key'], row['revision'], t['id'], t['version'],
                tracker.rules.version, tracker.config, tracker.clock())['result']
        except TopicError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, candidates))
    assert results.count('ADMITTED') == limit
    assert results.count('ADMISSION_LIMIT') == 2 - limit
    tracker.db = PipelineDB(tracker.db.db_path)
    tracker.clock.advance(hours=8)  # 从太平洋前一配额日跨到下一日。
    # 搜索重新补齐统计以免过期门禁掩盖累计额度检查。
    tracker.tick(verify_runtime=False)
    pending = tracker.db.keyword_admission_candidates(tracker.clock())
    assert pending
    assert {attempt(row) for row in pending} == {'ADMISSION_LIMIT'}
    # 已存在的主队列只做来源关联，不因新准入额度用尽被错误阻挡。
    row = pending[0]
    tracker.db.add_video(row['youtube_id'], 'existing', 'UC-isolated', source='DISCOVERY')
    assert attempt(row) == 'EXISTING'

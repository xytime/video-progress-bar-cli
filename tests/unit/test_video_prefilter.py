"""预筛选端到端边界；真实 DAL、线程和 API，外部服务使用内存适配器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 时间/统计边界、CAS、共享预算、生产隔离和 API 安全 |
"""
import sqlite3
import uuid
from datetime import timedelta

import pytest
from tests.topic_candidate_fixtures import tracker, video, topic, run
from tests.unit.test_topic_candidates_api import topic_client
from video_processing.core.video_prefilter import DEFAULTS, fields
from video_processing.core.topic_candidates import TopicError
from video_processing.utils.topic_search import SearchFailure, YouTubeTopicSearch


def prepare(tracker, items=None):
    item=video(duration='PT5M')
    item['statistics']=dict(viewCount='10000',likeCount='150')
    tracker.adapter.items=items if items is not None else [item]
    tracker.adapter.prefilter_search=tracker.adapter.search
    tracker.adapter.prefilter_details=tracker.adapter.details
    return tracker.db.prefilter_save(DEFAULTS,'test',tracker.clock())


def execute(tracker, rule):
    job=tracker.prefilter.start(rule['id'],rule['version'],uuid.uuid4().hex,'test')
    tracker.wait(3)
    return tracker.db.prefilter_results(job['id'])


def test_thresholds_precise_time_and_production_isolation(tracker):
    rule=prepare(tracker)
    data=execute(tracker,rule)
    assert data['job']['state']=='COMPLETE'
    row=data['results'][0]
    assert row['observation']['category']=='QUALIFIED'
    tracker.prefilter.decide(data['job']['id'],row['key'],dict(revision=row['revision'],content_version=row['observation']['content_version'],decision='SAVED'),'test')
    assert tracker.db.prefilter_results(data['job']['id'])['results'][0]['decision']=='SAVED'
    with sqlite3.connect(tracker.db.db_path) as c:
        for table in ('processed_videos','topic_candidates','topic_hits'):
            assert c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
    budget=tracker.db.topic_budget('isolated-project',tracker.clock())
    assert budget['search']==budget['general']==1


@pytest.mark.parametrize('change,category',[
    ({'duration':'PT0S'},'REJECTED'),({'duration':'PT5M1S'},'REJECTED'),
    ({'views':'9999'},'REJECTED'),({'likes':'149'},'REJECTED'),({'likes':None},'INCOMPLETE'),
    ({'views':'1.5'},'INCOMPLETE'),({'published':None},'INCOMPLETE'),
    ({'age':48},'QUALIFIED'),({'age':48.0001},'REJECTED'),({'age':-1},'REJECTED'),
    ({'live':'live'},'REJECTED'),({'live':'upcoming'},'REJECTED'),({'live':None},'INCOMPLETE'),
])
def test_mutually_exclusive_boundaries(tracker,change,category):
    rule=prepare(tracker);item=tracker.adapter.items[0]
    for key,value in change.items():
        if key=='duration':item['contentDetails']['duration']=value
        elif key in ('views','likes'):item['statistics'][{'views':'viewCount','likes':'likeCount'}[key]]=value
        elif key=='age':item['snippet']['publishedAt']=(tracker.clock()-timedelta(hours=value)).isoformat()
        elif key=='published':item['snippet']['publishedAt']=value
        elif key=='live':item['snippet']['liveBroadcastContent']=value
    data=execute(tracker,rule)
    assert data['results'][0]['observation']['category']==category
    counts=data['job']['counts']
    assert sum(counts[k] for k in ('QUALIFIED','REJECTED','INCOMPLETE','FAILED'))==counts['returned']==1


def test_rule_cas_idempotency_cooldown_dedup_and_retention(tracker):
    rule=prepare(tracker);data=execute(tracker,rule);job=data['job'];row=data['results'][0]
    assert tracker.prefilter.start(rule['id'],rule['version'],job['idempotency'],'test')['id']==job['id']
    assert len(tracker.adapter.calls)==2
    with pytest.raises(TopicError,match='15'):execute(tracker,rule)
    tracker.prefilter.decide(job['id'],row['key'],dict(revision=1,content_version=row['observation']['content_version'],decision='REJECTED'),'test')
    with pytest.raises(TopicError):tracker.db.prefilter_decide(job['id'],row['key'],1,row['observation']['content_version'],'SAVED','test',tracker.clock())
    with pytest.raises(TopicError):tracker.db.prefilter_save(DEFAULTS,'test',tracker.clock(),rule_id=rule['id'],version=0)
    tracker.clock.advance(minutes=16)
    another=prepare(tracker);data2=execute(tracker,another)
    assert data2['results'][0]['decision']=='REJECTED'
    tracker.clock.advance(days=31);tracker.maintenance()
    assert tracker.db.prefilter_results(job['id'])['results']==[]
    assert tracker.db.prefilter_result(job['id'],row['key'])['observation'] is None


def test_empty_partial_failure_and_policy_fail_closed(tracker):
    rule=prepare(tracker,[]);assert execute(tracker,rule)['job']['state']=='COMPLETE'
    tracker.clock.advance(minutes=16);tracker.adapter.items=[video(duration='PT1M')]
    tracker.adapter.prefilter_details=lambda ids,timeout:[]
    data=execute(tracker,rule);assert data['job']['state']=='PARTIAL'
    assert data['results'][0]['observation']['category']=='INCOMPLETE'
    tracker.clock.advance(minutes=16);tracker.adapter.prefilter_details=tracker.adapter.details
    tracker.adapter.detail_error=SearchFailure('NETWORK','官方请求失败')
    data=execute(tracker,rule);assert data['job']['state']=='FAILED'
    assert data['job']['counts']['FAILED']==1
    tracker.clock.advance(minutes=16);tracker.adapter.detail_error=None;tracker.rules.fail=True
    assert execute(tracker,rule)['results'][0]['observation']['category']=='INCOMPLETE'


def test_shared_budget_closed_gate_and_policy_recheck(tracker):
    rule=prepare(tracker);tracker.config.topic_search_daily_limit=1
    data=execute(tracker,rule);row=data['results'][0]
    assert not tracker.prefilter.view()['can_search']
    tracker.rules.fail=True
    with pytest.raises(TopicError,match='无法核实'):
        tracker.prefilter.decide(data['job']['id'],row['key'],dict(revision=1,content_version=row['observation']['content_version'],decision='SAVED'),'test')
    tracker.rules.fail=False
    existing=topic(tracker)
    assert run(tracker,existing)['code']=='BUDGET'
    tracker.config.topic_search_enabled=False
    assert tracker.prefilter.view()['gate']['code'] in ('SEARCH_CLOSED','BUDGET')
    with pytest.raises(TopicError):tracker.prefilter.start(rule['id'],rule['version'],uuid.uuid4().hex,'test')


def test_prefilter_api_strict_authority_and_no_implicit_search(topic_client):
    client,tracker=topic_client
    assert client.get('/video-prefilter').status_code==200
    state=client.get('/api/video-prefilter/state');assert state.status_code==200
    assert not tracker.adapter.calls
    assert client.post('/api/video-prefilter/rules',json=dict(DEFAULTS,auto_publish=True)).status_code==422
    assert client.post('/api/video-prefilter/rules',json=DEFAULTS,headers={'X-Topic-CSRF':'bad'}).status_code==403
    saved=client.post('/api/video-prefilter/rules',json=DEFAULTS).json()
    assert saved['purpose']=='PREFILTER_ONLY'
    assert client.put('/api/video-prefilter/rules/'+saved['id'],json=dict(DEFAULTS,version=0)).status_code==422
    assert not tracker.adapter.calls
    prepare(tracker)
    response=client.post('/api/video-prefilter/rules/'+saved['id']+'/search',json=dict(version=1,idempotency=uuid.uuid4().hex))
    assert response.status_code==202
    tracker.wait(3)
    assert client.get('/api/video-prefilter/results',params={'job_id':response.json()['id']}).json()['total']==1


def test_official_adapter_uses_exact_window_and_one_page(tracker):
    adapter=YouTubeTopicSearch(tracker.config);calls=[]
    async def get(endpoint,params,timeout):calls.append((endpoint,params));return []
    adapter._get=get
    rule=fields(DEFAULTS);adapter.prefilter_search(rule,tracker.clock(),10);adapter.prefilter_details(['00000000001'],10)
    query=calls[0][1]
    assert query['maxResults']==50 and query['order']=='date'
    assert query['q']=='"Elon Musk"|"Jensen Huang"|"plague"'
    assert query['publishedAfter']=='2026-10-09T04:00:00+00:00'
    assert 'videoDuration' not in query and 'pageToken' not in query
    assert 'liveStreamingDetails' in calls[1][1]['part']


def test_sort_before_pagination_and_global_decisions(tracker):
    items=[]
    for i in range(1,51):
        item=video(i,duration='PT4M59S');item['statistics']=dict(viewCount=str(i*10000),likeCount=str(i*150));items.append(item)
    rule=prepare(tracker,items);data=execute(tracker,rule)
    assert data['total']==50 and len(data['results'])==25
    assert data['results'][0]['observation']['metadata']['views']==500000
    second=tracker.db.prefilter_results(data['job']['id'],'QUALIFIED',2)
    assert second['results'][0]['observation']['metadata']['views']==250000
    assert second['results'][-1]['observation']['metadata']['views']==10000
    assert tracker.db.topic_budget('isolated-project',tracker.clock())['general']==1


def test_busy_lock_duplicate_trial_and_recovery(tracker):
    import threading
    rule=prepare(tracker);tracker.adapter.items*=2;tracker.adapter.release=threading.Event()
    idem=uuid.uuid4().hex
    job=tracker.prefilter.start(rule['id'],1,idem,'test')
    assert tracker.adapter.started.wait(1)
    assert tracker.prefilter.start(rule['id'],1,idem,'test')['id']==job['id']
    with pytest.raises(TopicError,match='搜索'):tracker.start(topic(tracker)['id'],1,uuid.uuid4().hex,'test')
    with pytest.raises(TopicError):tracker.db.prefilter_save(DEFAULTS,'test',tracker.clock(),rule_id=rule['id'],version=1)
    tracker.adapter.release.set();tracker.wait(3)
    data=tracker.db.prefilter_results(job['id']);assert data['job']['counts']['returned']==1
    tracker.config.topic_trial_mode=True
    for _ in range(2):
        tracker.clock.advance(minutes=16);execute(tracker,rule)
    tracker.clock.advance(days=1)
    assert tracker.prefilter.view()['gate']['code']=='TRIAL_BUDGET'
    data=execute(tracker,rule);assert data['job']['code']=='TRIAL_BUDGET'
    assert len(tracker.adapter.calls)==6


def test_closed_during_fetch_does_not_store_or_publish(tracker):
    rule=prepare(tracker)
    def details(ids,timeout):
        control=tracker.db.topic_control();tracker.mode('OFF',control['version'],'test')
        return tracker.adapter.items
    tracker.adapter.prefilter_details=details
    data=execute(tracker,rule)
    assert data['job']['state']=='INTERRUPTED' and data['results']==[]
    assert data['job']['counts']['unprocessed']==0  # 已分类但未获门禁许可写入结果。

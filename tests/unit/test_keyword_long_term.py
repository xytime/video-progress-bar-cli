"""v0.5真实SQLite验收：额度并发、日界、历史、切片和明确续期，不连接生产。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 0.5.0 | 2026-10-15 | Codex | 日周并发、持久消费、切片容量与续期边界 |
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from config.keyword_rollout import phase_values
from video_processing.core.topic_candidates import TopicError
from tests.topic_candidate_fixtures import tracker, topic, run, video
from tests.unit.test_keyword_collection import enable, admit


def long_term(service):
    for name,value in phase_values('LONG_TERM','isolated-project').items():
        setattr(service.config,name,value)


def candidates(service, monkeypatch, count=5, **fields):
    long_term(service)
    selected=enable(service, **fields)
    service.adapter.items=[video(n) for n in range(1,count+1)]
    for item in service.adapter.items:
        item['statistics']=dict(viewCount='3000',likeCount='150')
    assert service.tick(verify_runtime=False)=='SEARCH'
    admit(service,monkeypatch)
    return selected,service.db.keyword_admission_candidates(service.clock())


def insert(service, selected, row):
    try:
        return service.db.keyword_admit(row['key'],row['revision'],selected['id'],selected['version'],
                    service.rules.version,service.config,service.clock())['result']
    except TopicError as exc:
        return exc.code


def usage(service):
    return service.db.keyword_admission_usage(service.config,service.clock())


def historical(service, at, *, index=1, status='FAILED'):
    """测试历史事实直接写入临时SQLite；生产验收不得采用此方式制造证据。"""
    youtube_id=f'{index:011d}'
    service.db.add_video(youtube_id,'Historical keyword','UC-isolated',source='KEYWORD')
    main=service.db.get_video_by_youtube_id(youtube_id)
    with sqlite3.connect(service.db.db_path) as c:
        c.execute('UPDATE processed_videos SET status=? WHERE id=?',(status,main['id']))
        c.execute('''INSERT INTO keyword_admissions(key,video_id,topic_id,topic_version,score,policy,at,result,youtube_id)
            VALUES(?,?,?,1,80,'historical',?,'ADMITTED',?)''',
            (f'history-{index}',main['id'],'historical-topic',at.isoformat(),youtube_id))
    return main


def test_parallel_new_tasks_stop_at_two_and_restart_does_not_refund(tracker,monkeypatch):
    selected,rows=candidates(tracker,monkeypatch)
    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes=list(pool.map(lambda row:insert(tracker,selected,row),rows))
    assert outcomes.count('ADMITTED')==2
    assert set(outcomes)<= {'ADMITTED','ADMISSION_INFLIGHT'}
    before=usage(tracker)
    assert (before['daily_used'],before['rolling_used'],before['inflight'])==(2,2,2)
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute("UPDATE processed_videos SET status='FAILED'")
    assert usage(tracker)['code']=='ADMISSION_DAILY'
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('DELETE FROM processed_videos')
    tracker.db=type(tracker.db)(tracker.db.db_path)
    assert usage(tracker)['daily_used']==2 and usage(tracker)['inflight']==0
    remaining=tracker.db.keyword_admission_candidates(tracker.clock())
    assert insert(tracker,selected,remaining[0])=='ADMISSION_DAILY'
    assert len(tracker.db.keyword_admission_ledger())==2
    # 到额度不关闭采集；下一个自然到期周期仍可请求，未产生额外主任务。
    tracker.clock.advance(hours=4)
    assert tracker.tick(verify_runtime=False)=='SEARCH'
    assert len(tracker.db.keyword_admission_ledger())==2


def test_failed_task_replay_after_delete_cannot_recreate(tracker,monkeypatch):
    selected,rows=candidates(tracker,monkeypatch,count=1)
    assert insert(tracker,selected,rows[0])=='ADMITTED'
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('DELETE FROM processed_videos')
    assert insert(tracker,selected,rows[0])=='EXISTING'
    assert tracker.db.get_video_by_youtube_id('00000000001') is None
    assert usage(tracker)['total_used']==1


def test_beijing_midnight_is_independent_from_api_la_day(tracker):
    long_term(tracker)
    tracker.clock.now=datetime(2026,11,1,15,59,tzinfo=timezone.utc)
    historical(tracker,tracker.clock()-timedelta(minutes=2),index=1)
    historical(tracker,tracker.clock()-timedelta(minutes=1),index=2)
    assert usage(tracker)['code']=='ADMISSION_DAILY'
    api_day=tracker.db.topic_budget('isolated-project',tracker.clock())['day']
    tracker.clock.advance(minutes=1)
    after=usage(tracker)
    assert after['day']=='2026-11-02' and after['daily_used']==0 and after['rolling_used']==2
    assert tracker.db.topic_budget('isolated-project',tracker.clock())['day']==api_day


def test_rolling_exact_168_hours_not_calendar_week_or_dst(tracker):
    long_term(tracker)
    tracker.clock.now=datetime(2026,11,3,4,tzinfo=timezone.utc)
    oldest=tracker.clock()-timedelta(hours=167)
    for n in range(6):
        historical(tracker,oldest+timedelta(hours=n*24),index=n+1)
    before=usage(tracker)
    assert before['rolling_used']==6 and before['code']=='ADMISSION_ROLLING'
    assert datetime.fromisoformat(before['next_at'])==oldest+timedelta(hours=168)
    tracker.clock.advance(hours=1)
    assert usage(tracker)['rolling_used']==5 and usage(tracker)['code']=='OK'


def test_sliced_root_counts_once_until_last_child_finishes(tracker):
    long_term(tracker)
    root=historical(tracker,tracker.clock(),status='SEGMENTED')
    tracker.db.add_video('00000000001','Slice','UC-isolated',source='KEYWORD',slice_index=1,parent_id=root['id'])
    tracker.db.add_video('00000000001','Slice2','UC-isolated',source='KEYWORD',slice_index=2,parent_id=root['id'])
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute("UPDATE processed_videos SET status='PUBLISHED' WHERE slice_index=1")
        c.execute("UPDATE processed_videos SET status='LOGIN_REQUIRED' WHERE slice_index=2")
    assert usage(tracker)['inflight']==1 and usage(tracker)['daily_used']==1
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute("UPDATE processed_videos SET status='FAILED' WHERE slice_index=0")
    assert usage(tracker)['inflight']==1
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute("UPDATE processed_videos SET status='PUBLISHED' WHERE slice_index=2")
    assert usage(tracker)['inflight']==0 and usage(tracker)['rolling_used']==1


@pytest.mark.parametrize('corruption',['naive','future','origin','result','missing_origin'])
def test_invalid_ledger_blocks_only_new_admission(tracker,monkeypatch,corruption):
    selected,rows=candidates(tracker,monkeypatch,count=1)
    main=historical(tracker,tracker.clock()-timedelta(days=1),index=99)
    with sqlite3.connect(tracker.db.db_path) as c:
        if corruption=='naive':c.execute("UPDATE keyword_admissions SET at='2026-10-10T00:00:00'")
        elif corruption=='future':c.execute('UPDATE keyword_admissions SET at=?',((tracker.clock()+timedelta(seconds=1)).isoformat(),))
        elif corruption=='origin':c.execute("UPDATE keyword_admissions SET youtube_id='other'")
        elif corruption=='missing_origin':c.execute('UPDATE keyword_admissions SET youtube_id=NULL')
        else:c.execute("UPDATE keyword_admissions SET result='UNKNOWN'")
    assert not usage(tracker)['verified']
    assert insert(tracker,selected,rows[0])=='ADMISSION_LEDGER_UNVERIFIED'
    tracker.clock.advance(hours=4)
    assert tracker.tick(verify_runtime=False)=='SEARCH'
    assert tracker.db.get_video_by_youtube_id('00000000001') is None
    assert tracker.db.get_video_by_youtube_id('00000000099') is not None


def test_old_schema_backfills_origin_without_rewriting_history(tracker):
    long_term(tracker)
    root=historical(tracker,tracker.clock()-timedelta(hours=1))
    ledger=tracker.db.keyword_admission_ledger()[0]
    with sqlite3.connect(tracker.db.db_path) as c:
        c.execute('ALTER TABLE keyword_admissions DROP COLUMN youtube_id')
    tracker.db=type(tracker.db)(tracker.db.db_path)
    tracker.db.topic_initialize()
    assert tracker.db.keyword_admission_ledger()[0]==ledger
    assert usage(tracker)['daily_used']==1


def test_short_rule_cannot_weaken_long_term_admission_floor(tracker,monkeypatch):
    selected,rows=candidates(tracker,monkeypatch,count=1,min_duration=60)
    # 真实官方适配器返回2分钟资料并重新搜索，非直接修改评分结果。
    tracker.adapter.items[0]['contentDetails']['duration']='PT2M'
    tracker.clock.advance(minutes=16)
    run(tracker,selected)
    rows=tracker.db.keyword_admission_candidates(tracker.clock())
    assert insert(tracker,selected,rows[0])=='DURATION_LIMIT'
    assert tracker.candidates()['candidates'][0]['collection']['state']=='RESTRICTED'
    assert not tracker.db.keyword_admission_ledger()


def test_renew_expired_changes_version_preserves_history_and_requires_new_hit(tracker,monkeypatch):
    selected,rows=candidates(tracker,monkeypatch,count=1,valid_days=1)
    tracker.clock.advance(days=2)
    expired=tracker.db.topic_get(selected['id'],tracker.clock())
    with pytest.raises(TopicError,match='明确'):
        tracker.db.topic_renew(selected['id'],expired['version'],7,False,'test',tracker.clock())
    renewed=tracker.db.topic_renew(selected['id'],expired['version'],7,True,'test',tracker.clock())
    assert renewed['status']=='ACTIVE' and renewed['auto_enabled']==1
    assert datetime.fromisoformat(renewed['expires_at'])==tracker.clock()+timedelta(days=7)
    assert renewed['version']==expired['version']+1 and tracker.candidates()['total']==1
    assert not tracker.db.keyword_admission_candidates(tracker.clock())
    assert tracker.db.topic_audit_records()[0]['action']=='RENEW_RESTORE'
    assert [call[0] for call in tracker.adapter.calls]==['search','details']


def test_renew_paused_stays_paused_busy_and_cas_reject(tracker):
    long_term(tracker)
    selected=enable(tracker)
    paused=tracker.db.topic_transition(selected['id'],selected['version'],'PAUSED','test',tracker.clock())
    renewed=tracker.db.topic_renew(selected['id'],paused['version'],7,False,'test',tracker.clock())
    assert renewed['status']=='PAUSED' and tracker.db.keyword_due(tracker.clock())==[]
    with pytest.raises(TopicError,match='变化'):
        tracker.db.topic_renew(selected['id'],paused['version'],7,False,'test',tracker.clock())
    active=tracker.db.topic_transition(selected['id'],renewed['version'],'ACTIVE','test',tracker.clock())
    tracker.db.topic_create_job(active['id'],active['version'],'busy-renew','test',tracker.clock())
    with pytest.raises(TopicError,match='作业结束'):
        tracker.db.topic_renew(active['id'],active['version'],7,False,'test',tracker.clock())


def test_admission_selection_score_then_newest_then_key(tracker,monkeypatch):
    long_term(tracker)
    selected=enable(tracker)
    tracker.adapter.items=[video(n) for n in [3,1,2,4]]
    for item in tracker.adapter.items:
        item['statistics']=dict(viewCount='3000',likeCount='150')
    tracker.adapter.items[0]['snippet']['publishedAt']='2026-10-11T01:00:00Z'
    tracker.adapter.items[3]['statistics']=dict(viewCount='100000',likeCount='10000')
    tracker.tick(verify_runtime=False)
    rows=tracker.db.keyword_admission_candidates(tracker.clock())
    assert [r['metadata']['youtube_id'] for r in rows][:2]==['00000000004','00000000003']
    assert [r['key'] for r in rows[2:]]==sorted(r['key'] for r in rows[2:])

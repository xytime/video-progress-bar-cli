"""v0.3.1：真实 SQLite 集合、互斥分类与 API 同源验收。"""
import time

from fastapi.testclient import TestClient
from video_processing.db.database import PipelineDB
from web import app as web_app


def seed(db, name, status, error='', parent=None, score=85, updated='2026-10-12 00:00:00'):
    db.add_video(name, name, 'UC-fixture', score=score)
    with db.get_connection() as conn:
        conn.execute('UPDATE processed_videos SET status=?,error_msg=?,parent_id=?,updated_at=? WHERE youtube_id=?',
                     (status,error,parent,updated,name))
        return conn.execute('SELECT id FROM processed_videos WHERE youtube_id=?',(name,)).fetchone()[0]


def test_cohort_intersections_and_exact_drilldown(tmp_path):
    db=PipelineDB(str(tmp_path/'cohort.db'))
    seed(db,'high','SUBMITTED_BOUND')
    seed(db,'low','PUBLISHED',score=20)
    seed(db,'waiting','PENDING')
    parent=seed(db,'parent','SEGMENTED')
    seed(db,'slice','PUBLISHED',parent=parent)
    seed(db,'ignored','IGNORED',score=20)
    seed(db,'archived','HISTORICAL_ARCHIVED',score=20)
    metrics=db.get_global_funnel_metrics(window='all')
    cohort=metrics['cohort']
    assert cohort['ingested']==6 and cohort['qualified']==3
    assert cohort['local_completed']==2 and cohort['qualified_local_completed']==1
    assert cohort['qualified_processed'] <= cohort['qualified']
    rows,total=db.get_paginated_videos(funnel_stage='published',created_window='all')
    assert total==2 and {r['youtube_id'] for r in rows}=={'high','low'}
    empty=db.get_channel_funnel_metrics('missing',window='all')['cohort']
    assert empty['qualified']==empty['qualified_local_completed']==0


def test_attention_families_disjoint_and_api_consistent(tmp_path,monkeypatch):
    db=PipelineDB(str(tmp_path/'attention.db'))
    expected={'delivery':{'bound','uncertain','unbound'},'blocked':{'login','deferred','login-family'},
              'execution':{'unknown','mixed','copy','technical-policy'},'policy':{'policy','pure'},'review':{'review'}}
    for name,status in [('bound','SUBMITTED_BOUND'),('uncertain','UNCERTAIN'),('unbound','SUBMITTED_UNBOUND'),
                        ('login','LOGIN_REQUIRED'),('deferred','WECHAT_DEFERRED'),('review','UNDER_REVIEW')]:
        seed(db,name,status)
    seed(db,'unknown','FAILED',updated='invalid')
    seed(db,'copy','FAILED','COPYWRITING quality gate')
    seed(db,'technical-policy','FAILED','Channel Policy network timeout')
    seed(db,'policy','FAILED','Channel Policy blocked')
    for name,errors in [('pure',['Channel Policy blocked','Censorship P0']),
                        ('mixed',['Channel Policy blocked','']),('login-family',['cookie expired','Channel Policy blocked'])]:
        parent=seed(db,name,'SEGMENTED','旧父记录错误')
        for i,error in enumerate(errors): seed(db,f'{name}-{i}','FAILED',error,parent)
        seed(db,name+'-normal','PUBLISHED','Channel Policy old',parent)
    seed(db,'archived','HISTORICAL_ARCHIVED','LOGIN_REQUIRED')
    monkeypatch.setattr(web_app,'db',db)
    client=TestClient(web_app.app)
    summary=client.get('/api/console/attention').json()
    for kind,names in expected.items():
        result=client.get('/api/videos',params=dict(attention_kind=kind,sort='updated_at_desc',created_window='all')).json()
        assert summary[kind]['count']==result['total_count']==len(names)
        assert {r['youtube_id'] for r in result['videos']}==names
    assert client.get('/api/videos?attention_kind=unknown').status_code==422
    assert client.get('/api/videos?attention_kind=delivery&funnel_stage=published').status_code==422


def test_attention_empty_and_representative_cost(tmp_path):
    db=PipelineDB(str(tmp_path/'cost.db'))
    assert all(r==dict(count=0,updated_at=None) for r in db.get_attention_summary().values())
    with db.get_connection() as conn:
        conn.executemany('INSERT INTO processed_videos (youtube_id,title,channel_id,status,updated_at) VALUES (?,?,?,?,?)',
                         [(f'cost-{i}','record','UC-fixture','FAILED' if i%5==0 else 'PUBLISHED','invalid') for i in range(5000)])
    start=time.monotonic(); summary=db.get_attention_summary(); elapsed=time.monotonic()-start
    assert summary['execution']==dict(count=1000,updated_at=None)
    assert elapsed<3, f'5000 records summary took {elapsed:.3f}s'
    print(f'Attention summary 5000 rows: {elapsed:.3f}s')

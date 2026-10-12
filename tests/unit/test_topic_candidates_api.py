"""A15–A17：实际 FastAPI 路由与本机安全边界，服务注入临时数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-11 | Codex | 真实会话/来源/CSRF/CAS/禁止准入测试 |
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from pathlib import Path
import re
import sqlite3
import pytest

from tests.topic_candidate_fixtures import tracker, topic, run, decision
from web.topic_candidates import create_topic_candidates_router
from video_processing.topic_tracker.service import TopicTracker

ORIGIN='http://127.0.0.1:9100'


@pytest.fixture
def topic_client(tracker):
    app=FastAPI()
    app.include_router(create_topic_candidates_router(lambda:tracker,port=9100))
    app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[2]/'src/web/static'))
    with TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50000)) as client:
        page=client.get('/topic-candidates')
        assert page.status_code==200
        csrf=re.search(r'name="topic-csrf" content="([a-f0-9]+)"',page.text).group(1)
        client.headers.update({'Origin':ORIGIN,'X-Topic-CSRF':csrf})
        yield client,tracker


def test_a01_real_api_create_edit_persist(topic_client):
    client,tracker=topic_client
    data=dict(name='鼠疫追踪',query='plague outbreak',category='健康科学',lookback_days=7,valid_days=7)
    response=client.post('/api/topic-candidates/topics',json=data)
    assert response.status_code==200
    row=response.json()
    assert client.get('/api/topic-candidates/state').json()['topics'][0]['query']=='plague outbreak'
    changed=client.put('/api/topic-candidates/topics/'+row['id'],json=dict(data,version=row['version'],name='健康追踪'))
    assert changed.status_code==200
    assert client.put('/api/topic-candidates/topics/'+row['id'],json=dict(data,version=row['version'])).status_code==409
    assert not tracker.adapter.calls


@pytest.mark.parametrize('headers', [{'Origin':'http://evil.invalid'},{'Origin':''},{'Host':'evil.invalid:9100'},{'X-Topic-CSRF':'invalid'},{'Cookie':'topic_local_session='+'a'*64}])
def test_a15_forged_write_no_mutation(topic_client,headers):
    client,tracker=topic_client
    before=tracker.db.topic_audit_records()
    response=client.post('/api/topic-candidates/topics',json=dict(name='x',query='x',category='科技产业'),headers=headers)
    assert response.status_code==403
    assert tracker.db.topic_audit_records()==before


def test_a15_missing_origin_cookie_and_real_lan_peer(topic_client):
    client,tracker=topic_client
    client.headers.pop('origin');response=client.post('/api/topic-candidates/topics',json=dict(name='x',query='x',category='科技产业'))
    assert response.status_code==403
    client.cookies.clear();assert client.get('/api/topic-candidates/state').status_code==403
    remote=TestClient(client.app,base_url=ORIGIN,client=('192.168.1.20',50000))
    assert remote.get('/topic-candidates',headers={'X-Forwarded-For':'127.0.0.1'}).status_code==403
    assert remote.get('/api/topic-candidates/state').status_code==403


def test_a15_expired_session_and_stale_decision(topic_client):
    client,tracker=topic_client
    run(tracker);row=tracker.candidates()['candidates'][0]
    path='/api/topic-candidates/videos/'+row['key']+'/decision'
    assert client.post(path,json=decision(row)).status_code==200
    assert client.post(path,json=decision(row,'REJECTED','其他')).status_code==409
    tracker.clock.advance(hours=9)
    assert client.get('/api/topic-candidates/state').status_code==403


@pytest.mark.parametrize('extra', [dict(score=100),dict(source='MANUAL'),dict(approved=True),dict(bypass_censorship=True)])
def test_a17_no_client_authority_or_publish_routes(topic_client,extra):
    client,tracker=topic_client
    assert client.post('/api/topic-candidates/topics',json=dict(name='test',query='test',category='科技产业',**extra)).status_code==422
    for suffix in ('admit','publish','retry','process'):
        assert client.post('/api/topic-candidates/'+suffix,json={}).status_code==404
    assert tracker.db.get_video_by_youtube_id('00000000001') is None


def test_a12_production_search_closed_even_mode_api(topic_client):
    client,tracker=topic_client
    tracker.config.topic_search_enabled=False
    version=tracker.db.topic_control()['version']
    assert client.put('/api/topic-candidates/mode',json=dict(version=version,mode='DISCOVERY_ONLY')).status_code==403
    t=topic(tracker)
    assert client.post('/api/topic-candidates/topics/'+t['id']+'/search',json=dict(version=t['version'],idempotency='closed-production-request')).status_code==403
    assert not tracker.adapter.calls


def test_a21_busy_topic_initialization_preserves_existing_routes(tracker, monkeypatch):
    app=FastAPI()
    @app.get('/existing-health')
    def existing_health():return {'ok':True}
    def factory():
        return TopicTracker(tracker.db,tracker.config,tracker.adapter,tracker.rules,clock=tracker.clock)
    app.include_router(create_topic_candidates_router(factory,port=9100))
    with sqlite3.connect(tracker.db.db_path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        with TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50000)) as client:
            assert client.get('/existing-health').json()=={'ok':True}
            response=client.get('/topic-candidates')
            assert response.status_code==503
            assert response.json()['detail']['code']=='DATABASE_BUSY'
        assert not tracker.adapter.calls
    runtime = app.state.topic_runtime
    observed = runtime.monotonic()
    monkeypatch.setattr(runtime, 'monotonic', lambda: observed + 61)
    with TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50000)) as client:
        assert client.get('/topic-candidates').status_code==200

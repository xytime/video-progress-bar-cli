"""真实 SQLite/API 覆盖旧错误不改写、具名 CAS 以及单次原子领取。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 人工门禁、一次领取、实片标题和微窄画面回归。 |
"""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from video_processing.db.database import PipelineDB
from video_processing.db.funnel_diagnosis import _fetch_subtitle_recoveries
from web.subtitle_review import create_subtitle_review_router


@pytest.fixture
def case(tmp_path):
    db=PipelineDB(str(tmp_path/'review.db'))
    db.add_video('legacy-review','legacy','channel',score=100,source='MANUAL')
    db.update_video_status('legacy-review','FAILED',error_msg='burned_caption_repair.py:501 源片比 9:16 更窄，需先人工规范化')
    app=FastAPI();app.include_router(create_subtitle_review_router(db))
    return db,TestClient(app),db.get_video_by_youtube_id('legacy-review')['id']


def authorize(client):
    info=client.get('/api/videos/legacy-review/subtitle-review').json()
    return dict(expected_review_token=info['review_token'],expected_receipt_sha=info['expected_receipt_sha'],
                actor='unit reviewer',reason='verified source and geometry')


def test_legacy_release_retains_evidence_and_is_consumed_once(case):
    db,client,vid=case
    before=db.get_video_by_youtube_id('legacy-review')
    with db.get_connection() as c:
        old=[dict(r) for r in c.execute('SELECT * FROM publishing_failure_events')]
    assert db.subtitle_recovery_blocker(vid)
    assert not db.claim_video_for_processing('legacy-review')
    body=authorize(client)
    assert client.post('/api/videos/legacy-review/subtitle-release',json=body).json()['allowed_claims']==1
    assert db.get_video_by_youtube_id('legacy-review')['error_msg']==before['error_msg']
    assert db.subtitle_recovery_blocker(vid) is None
    assert client.post('/api/videos/legacy-review/subtitle-release',json=body).status_code==409
    with db.get_connection() as c:
        facts=_fetch_subtitle_recoveries(c,[vid])[vid]
    assert facts['manual_gate_blocked'] is False and facts['state']=='RELEASED'
    assert db.claim_video_for_processing('legacy-review')
    db.update_video_status('legacy-review','PENDING',error_msg='ordinary rewrite')
    assert not db.claim_video_for_processing('legacy-review')
    assert not db.claim_video_for_publication('legacy-review',123)
    assert db.subtitle_recovery_blocker(vid)
    with db.get_connection() as c:
        assert [dict(r) for r in c.execute('SELECT * FROM publishing_failure_events')]==old
        events=[dict(r) for r in c.execute('SELECT * FROM subtitle_recovery_events')]
    assert [r['event_type'] for r in events]==['RELEASED','CLAIMED']
    details=json.loads(events[0]['details'])
    assert details['actor']==body['actor'] and details['reason']==body['reason']
    assert details['review_error']==before['error_msg'] and events[0]['created_at']>0


def test_stale_review_and_ignored_are_rejected(case):
    db,client,vid=case
    body=authorize(client)
    db.update_video_status('legacy-review','FAILED',error_msg='caption_frame_uncertain new evidence')
    assert client.post('/api/videos/legacy-review/subtitle-release',json=body).status_code==409
    body=authorize(client)
    assert client.post('/api/videos/legacy-review/subtitle-release',json=body,headers={'Origin':'https://other.test'}).status_code==403
    assert client.post('/api/videos/legacy-review/subtitle-release',json=body|{'actor':'  '}).status_code==422
    db.update_video_status('legacy-review','IGNORED')
    assert client.post('/api/videos/legacy-review/subtitle-release',json=body).status_code==409


def test_success_proof_unlocks_normal_next_stage_but_not_future_failure(case):
    db,client,vid=case
    assert client.post('/api/videos/legacy-review/subtitle-release',json=authorize(client)).status_code==200
    assert not db.resolve_subtitle_recovery(vid,'a'*64) # 未领取不能补造成功。
    assert db.claim_video_for_processing('legacy-review')
    assert db.resolve_subtitle_recovery(vid,'a'*64)
    db.update_video_status('legacy-review','PENDING')
    assert db.subtitle_recovery_blocker(vid) is None
    assert db.claim_video_for_processing('legacy-review')
    db.update_video_status('legacy-review','FAILED',error_msg='caption_frame_uncertain new failure')
    assert db.subtitle_recovery_blocker(vid)
    assert not db.claim_video_for_processing('legacy-review')


@pytest.mark.parametrize('endpoint,body',[('retry',None),('respec',{}),('reset-hard',None)])
def test_existing_mutations_reject_before_side_effects(case,monkeypatch,endpoint,body):
    from web import app as web_app
    db,_,vid=case
    monkeypatch.setattr(web_app,'db',db)
    client=TestClient(web_app.app)
    before=db.get_video_by_youtube_id('legacy-review')
    response=client.post('/api/videos/legacy-review/'+endpoint,json=body).json()
    assert response['success'] is False and '人工' in response['error']
    assert db.get_video_by_youtube_id('legacy-review')==before


def test_release_has_bounded_lifetime_and_cannot_be_reissued_for_same_evidence(case):
    db,client,vid=case
    body=authorize(client)
    assert client.post('/api/videos/legacy-review/subtitle-release',json=body).status_code==200
    with db.get_connection() as c:
        c.execute("UPDATE subtitle_recovery_events SET details=json_set(details,'$.expires_at',0) WHERE event_type='RELEASED'")
    assert db.subtitle_recovery_blocker(vid)
    assert not db.claim_video_for_processing('legacy-review')
    assert client.post('/api/videos/legacy-review/subtitle-release',json=body).status_code==409


def test_concurrent_claims_consume_only_one_authorization(case):
    from concurrent.futures import ThreadPoolExecutor
    db,client,vid=case
    assert client.post('/api/videos/legacy-review/subtitle-release',json=authorize(client)).status_code==200
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:db.claim_video_for_processing('legacy-review'),range(2)))
    assert sorted(results)==[False,True]
    with db.get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM subtitle_recovery_events WHERE event_type='CLAIMED'").fetchone()[0]==1

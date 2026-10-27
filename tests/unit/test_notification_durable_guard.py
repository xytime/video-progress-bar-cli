"""真实SQLite、合成通知和受控HTTP替身；不连接任何平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| notification-guard-v1 | 2026-10-26 | Codex | 未知不重放、跨连接并发、崩溃窗口、历史闭锁及持久退避。 |
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
import time
import pytest
from video_processing.db.database import PipelineDB
from video_processing import telegram_delivery as delivery

EVENT='pipeline.wechat_delivery_gap'
KEY='synthetic-incident'
FP=delivery._fingerprint(EVENT,KEY)

def send(db, **kw):
    return delivery.send_text(event_type=EVENT,priority='P1',text='Synthetic notification',
        dedupe_key=kw.pop('key',KEY),cooldown_seconds=kw.pop('cooldown',14400),
        token='synthetic-token',chat_id='synthetic-chat',db=db,**kw)

def accepted():
    return SimpleNamespace(ok=True,status_code=201,json=lambda:{'ok':True,'result':{'message_id':42}})

def test_unknown_is_not_retried_after_restart_or_cooldown_disabled(tmp_path,monkeypatch):
    path=tmp_path/'db.sqlite';db=PipelineDB(str(path));calls=[]
    def fail(*a,**kw):
        calls.append(1)
        raise delivery.requests.exceptions.SSLError('synthetic EOF')
    monkeypatch.setattr(delivery,'_post_with_connect_retry',fail)
    assert send(db).state=='UNKNOWN'
    again=send(PipelineDB(str(path)),cooldown=0)
    assert again.state=='UNKNOWN' and again.suppressed
    assert 'NOT_REPLAYED' in again.error_kind
    assert len(calls)==1
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM telegram_notification_receipts WHERE delivery_state='ACCEPTED'").fetchone()[0]==0
        assert c.execute("SELECT state FROM telegram_notification_attempts").fetchone()[0]=='UNKNOWN'

def test_legacy_unknowns_not_bulk_released_but_new_event_allowed(tmp_path,monkeypatch):
    db=PipelineDB(str(tmp_path/'db.sqlite'));calls=[]
    for key in ['old-a','old-b','old-c']:
        db.record_telegram_notification_receipt(event_type=EVENT,priority='P1',content_sha256=delivery._fingerprint(EVENT,key),delivery_state='UNKNOWN',error_kind='SSLError')
    monkeypatch.setattr(delivery,'_post_with_connect_retry',lambda *a,**kw:(calls.append(1),accepted())[1])
    for key in ['old-a','old-b','old-c']:
        assert send(db,key=key).state=='UNKNOWN'
    assert calls==[]
    assert send(db,key='new-incident').state=='ACCEPTED'
    assert len(calls)==1

def test_two_connections_cannot_send_same_event_concurrently(tmp_path,monkeypatch):
    path=tmp_path/'db.sqlite';one=PipelineDB(str(path));two=PipelineDB(str(path));started=Event();release=Event();calls=[]
    def post(*a,**kw):
        calls.append(1)
        if len(calls)==1:
            started.set();assert release.wait(5)
        return accepted()
    monkeypatch.setattr(delivery,'_post_with_connect_retry',post)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first=pool.submit(send,one)
        try:
            assert started.wait(5)
            second=send(two)
            assert second.state=='UNKNOWN' and second.suppressed
            assert len(calls)==1
        finally:release.set()
        assert first.result().state=='ACCEPTED'

def claim(db,now):
    return db.claim_notification_delivery(event_type=EVENT,fingerprint=FP,priority='P1',cooldown_seconds=14400,lease_seconds=10,now=now)

def test_expired_pre_intent_claim_can_be_replaced_but_stale_owner_cannot_send(tmp_path):
    db=PipelineDB(str(tmp_path/'db.sqlite'));now=time.time();old=claim(db,now);new=claim(db,now+11)
    assert old['allowed'] and new['allowed'] and old['token']!=new['token']
    assert not db.record_notification_send_intent(old['token'],now=now+11)
    assert db.record_notification_send_intent(new['token'],now=now+11)

def test_crash_after_intent_never_expires_into_replay(tmp_path,monkeypatch):
    path=tmp_path/'db.sqlite';db=PipelineDB(str(path));now=time.time();a=claim(db,now)
    assert db.record_notification_send_intent(a['token'],now=now+1)
    assert not claim(PipelineDB(str(path)),now+86400)['allowed']
    monkeypatch.setattr(delivery,'_post_with_connect_retry',lambda *a,**kw:pytest.fail('network must not be called'))
    assert send(db,cooldown=0).state=='UNKNOWN'

def test_result_persistence_failure_leaves_intent_closed(tmp_path,monkeypatch):
    db=PipelineDB(str(tmp_path/'db.sqlite'));calls=[]
    monkeypatch.setattr(delivery,'_post_with_connect_retry',lambda *a,**kw:(calls.append(1),accepted())[1])
    monkeypatch.setattr(db,'record_telegram_notification_receipt',lambda **kw:(_ for _ in ()).throw(OSError('synthetic disk full')))
    result=send(db)
    assert result.state=='ACCEPTED' and result.error_kind=='RECEIPT_PERSISTENCE_UNCONFIRMED'
    assert send(db).state=='UNKNOWN'
    assert len(calls)==1
    with db.get_connection() as c:
        assert c.execute('SELECT state FROM telegram_notification_attempts').fetchone()[0]=='SEND_INTENT'

def test_readonly_or_unavailable_state_fails_closed_without_http(tmp_path,monkeypatch):
    path=tmp_path/'db.sqlite';PipelineDB(str(path));ro=PipelineDB(str(path),read_only=True)
    monkeypatch.setattr(delivery,'_post_with_connect_retry',lambda *a,**kw:pytest.fail('network must not be called'))
    result=send(ro)
    assert result.state=='NOT_SENT' and result.error_kind=='DELIVERY_STATE_UNAVAILABLE'

def test_known_not_sent_failure_has_persistent_bounded_backoff(tmp_path,monkeypatch):
    db=PipelineDB(str(tmp_path/'db.sqlite'));calls=[]
    def fail(*a,**kw):
        calls.append(1);raise delivery.requests.ConnectTimeout()
    monkeypatch.setattr(delivery,'_post_with_connect_retry',fail)
    assert send(db).state=='NOT_SENT'
    result=send(db)
    assert result.state=='NOT_SENT' and result.suppressed and result.error_kind=='KNOWN_NOT_SENT_BACKOFF'
    assert len(calls)==1
    with db.get_connection() as c:
        row=c.execute('SELECT state,retry_after,finished_at FROM telegram_notification_attempts').fetchone()
        assert row['state']=='FAILED' and 240<=row['retry_after']-row['finished_at']<=300

def test_existing_success_cooldown_is_unchanged(tmp_path,monkeypatch):
    db=PipelineDB(str(tmp_path/'db.sqlite'));calls=[]
    monkeypatch.setattr(delivery,'_post_with_connect_retry',lambda *a,**kw:(calls.append(1),accepted())[1])
    assert send(db).state=='ACCEPTED'
    assert send(db).state=='SUPPRESSED'
    assert len(calls)==1
    assert claim(db,time.time()+14401)['allowed']


def test_durable_success_survives_receipt_retention_without_extending_cooldown(tmp_path,monkeypatch):
    db=PipelineDB(str(tmp_path/'db.sqlite'));calls=[]
    monkeypatch.setattr(delivery,'_post_with_connect_retry',lambda *a,**kw:(calls.append(1),accepted())[1])
    assert send(db).state=='ACCEPTED'
    with db.get_connection() as c:
        c.execute('DELETE FROM telegram_notification_receipts')
    assert send(db).state=='SUPPRESSED'
    assert len(calls)==1
    assert claim(db,time.time()+14401)['allowed']


def test_unknown_guard_does_not_mark_new_subtitle_outbox_as_accepted(tmp_path,monkeypatch):
    from tests.unit.test_subtitle_quality_notifications import envelope
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    db.add_video('syntheticvideo','测试视频','synthetic channel',score=80)
    queued=db.enqueue_subtitle_quality_notification('syntheticvideo',0,envelope())
    claimed=db.claim_subtitle_quality_notifications()[0]
    def fail(*a,**kw):raise delivery.requests.exceptions.SSLError('synthetic')
    monkeypatch.setattr(delivery,'_post_with_connect_retry',fail)
    first=send(db)
    assert first.state=='UNKNOWN'
    guarded=send(db)
    assert guarded.state=='UNKNOWN' and guarded.suppressed
    result=db.finish_subtitle_quality_notification(queued['id'],claimed['claim_token'],
        guarded.state,error_kind=guarded.error_kind)
    assert result['state']!='ACCEPTED'

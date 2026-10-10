"""双版本真实身份、恢复边界与指标归属的隔离验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-10 | Codex | 具名补队与人工身份恢复的原子边界和不重传验证。 |
| 1.0.0 | 2026-10-09 | Codex | 覆盖并发领取、A/B 顺序、未知提交及指标缺失 |
"""
from concurrent.futures import ThreadPoolExecutor
import time
import pytest
from video_processing.db.database import PipelineDB
from video_processing.db.wallstreet_experiment import CHANNEL_ID


@pytest.fixture
def db(tmp_path):
    result = PipelineDB(str(tmp_path/'pairs.db'))
    result.add_video('abcdefghijk','汽车贷款',CHANNEL_ID,score=80)
    return result


def ready(db):
    pair = db.enroll_wallstreet_video('abcdefghijk',b_only=True,inputs={'source':'test'})
    job = db.claim_wallstreet_render(now=100,lease_seconds=100)
    assert db.finish_wallstreet_render(pair['id'],job['lease_token'],package={'video':'B.mp4'},now=150)
    return pair


def test_named_recovery_keeps_submitted_a_and_reuses_b_identity(db):
    db.set_wallstreet_experiment(active=True)
    db.mark_video_ready_for_publication('abcdefghijk')
    db.record_wechat_submission_attempt('abcdefghijk',evidence_path='/tmp/receipt')
    db.record_wechat_publication_confirmation('abcdefghijk',state='SUBMITTED_BOUND',
        evidence_path='/tmp/receipt',platform_post_id='native-A')
    db.update_video_status('abcdefghijk','SUBMITTED_BOUND')
    before=db.get_wechat_publication('abcdefghijk')
    assert db.enroll_wallstreet_video('abcdefghijk') is None
    pair=db.recover_wallstreet_pair('abcdefghijk')
    assert pair['mode']=='PAIRED'
    assert db.recover_wallstreet_pair('abcdefghijk')['id']==pair['id']
    assert db.get_wechat_publication('abcdefghijk')==before
    assert db.get_video_by_youtube_id('abcdefghijk')['status']=='SUBMITTED_BOUND'
    assert len(db.get_wallstreet_publications())==4
    assert all(p['attempt_count']==0 for p in db.get_wallstreet_publications())
    a=next(p for p in db.get_wallstreet_publications() if p['variant']=='A' and p['platform']=='wechat')
    assert not db.sync_wallstreet_normal_a(a['id'])
    db.observe_wallstreet_publication(a['id'],state='PUBLISHED',platform_post_id='other-ID',evidence_path='/tmp/readback')
    assert not db.sync_wallstreet_normal_a(a['id'])
    assert db.get_wechat_publication('abcdefghijk')==before


def test_named_recovery_rejects_historical_unbound_and_review_held(db):
    db.set_wallstreet_experiment(active=True)
    db.mark_video_ready_for_publication('abcdefghijk')
    assert db.recover_wallstreet_pair('abcdefghijk') is None
    db.record_wechat_publication_confirmation('abcdefghijk',state='SUBMITTED_BOUND',
        evidence_path='/tmp/receipt',platform_post_id='native-A')
    db.set_publication_review_required('abcdefghijk',True)
    assert db.recover_wallstreet_pair('abcdefghijk') is None
    db.set_publication_review_required('abcdefghijk',False)
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET publication_ready_at='2026-01-01 00:00:00'")
    assert db.recover_wallstreet_pair('abcdefghijk') is None
    assert db.get_wallstreet_pairs()==[]


def test_operator_recovery_is_atomic_and_never_confirms_or_reuploads(db):
    db.set_wallstreet_experiment(active=True)
    db.mark_video_ready_for_publication('abcdefghijk')
    db.record_wechat_publication_confirmation('abcdefghijk',state='SUBMITTED_BOUND',
        evidence_path='/tmp/original-receipt',platform_post_id='old-A')
    db.recover_wallstreet_pair('abcdefghijk',accounts={'wechat':'default'})
    a=next(p for p in db.get_wallstreet_publications() if p['variant']=='A')
    b=next(p for p in db.get_wallstreet_publications() if p['variant']=='B')
    db.observe_wallstreet_publication(a['id'],state='UNCERTAIN',platform_post_id='old-A',evidence_path='/tmp/check')
    args=dict(previous_id='old-A',recovered_id='new-A',evidence_path='/tmp/operator-proof',
              operator_confirmation='用户核对完整原生预览确认同一普通版')
    with pytest.raises(ValueError):
        db.recover_wallstreet_normal_a_identity(b['id'],**args)
    with pytest.raises(ValueError):
        db.recover_wallstreet_normal_a_identity(a['id'],**{**args,'previous_id':'wrong'})
    assert db.get_wechat_publication('abcdefghijk')['platform_post_id']=='old-A'
    assert db.recover_wallstreet_normal_a_identity(a['id'],**args)
    normal=db.get_wechat_publication('abcdefghijk')
    assert normal['state']=='SUBMITTED_BOUND' and normal['platform_post_id']=='new-A'
    assert normal['evidence_path']=='/tmp/original-receipt'
    pubs=db.get_wallstreet_publications()
    assert all(p['attempt_count']==0 for p in pubs)
    assert next(p for p in pubs if p['variant']=='A')['state']=='UNCERTAIN'
    with db.get_connection() as conn:
        audit=dict(conn.execute('SELECT * FROM wallstreet_identity_recoveries').fetchone())
        assert (audit['previous_id'],audit['recovered_id'])==('old-A','new-A')
    with pytest.raises(ValueError):
        db.recover_wallstreet_normal_a_identity(a['id'],**args)


def test_inactive_and_non_target_do_not_enroll(db):
    assert db.enroll_wallstreet_video('abcdefghijk') is None
    db.set_wallstreet_experiment(active=True)
    db.add_video('other______','别的频道','other')
    assert db.enroll_wallstreet_video('other______',b_only=True) is None


def test_manual_render_retry_cannot_reset_active_or_completed_work(db):
    pair = db.enroll_wallstreet_video('abcdefghijk',b_only=True)
    assert not db.retry_wallstreet_render(pair['id'])
    job = db.claim_wallstreet_render(now=100)
    assert not db.retry_wallstreet_render(pair['id'])
    assert db.finish_wallstreet_render(pair['id'],job['lease_token'],error='temporary',now=101)
    assert db.claim_wallstreet_render(now=102) is None
    assert db.retry_wallstreet_render(pair['id'])
    retry = db.claim_wallstreet_render(now=102)
    assert retry['attempts']==2
    assert db.finish_wallstreet_render(pair['id'],retry['lease_token'],package={'video':'B.mp4'},now=103)
    assert not db.retry_wallstreet_render(pair['id'])


def test_manual_b_and_experiment_reuse_one_identity(db):
    pair = ready(db)
    assert db.enroll_wallstreet_video('abcdefghijk',b_only=True)['id'] == pair['id']
    assert db.enroll_wallstreet_video('abcdefghijk')['id'] == pair['id']
    assert {p['variant'] for p in db.get_wallstreet_publications()} == {'B'}
    assert db.get_video_by_youtube_id('abcdefghijk')['youtube_id'] == 'abcdefghijk'


def test_only_one_concurrent_render_claim_and_expired_owner_fenced(db):
    db.enroll_wallstreet_video('abcdefghijk',b_only=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _:db.claim_wallstreet_render(now=100,lease_seconds=10),range(2)))
    job = next(c for c in claimed if c)
    assert sum(c is not None for c in claimed) == 1
    resumed = db.claim_wallstreet_render(now=111)
    assert resumed['lease_token'] != job['lease_token']
    assert not db.finish_wallstreet_render(job['id'],job['lease_token'],package={},now=112)


def test_crash_after_submit_intent_never_reclaims(db):
    ready(db)
    pub = db.get_wallstreet_publications()[0]
    args = dict(package_sha256='a'*64,asset_sha256='b'*64,video_path='/tmp/B.mp4',evidence_path='/tmp/evidence')
    claim = db.claim_wallstreet_submission(pub['id'],**args)
    assert claim['state'] == 'SUBMITTING'
    assert db.claim_wallstreet_submission(pub['id'],now=time.time()+999999,**args) is None
    db.observe_wallstreet_publication(pub['id'],state='UNCERTAIN',evidence_path='/tmp/evidence',attempt_token=claim['attempt_token'])
    assert db.claim_wallstreet_submission(pub['id'],**args) is None
    with pytest.raises(ValueError,match='重置'):
        db.observe_wallstreet_publication(pub['id'],state='WAITING',evidence_path='/tmp/evidence')


def test_a_public_observation_then_six_hour_delay(db):
    db.set_wallstreet_experiment(active=True)
    with db.get_connection() as conn:
        conn.execute("UPDATE wallstreet_experiment SET activated_at=1")
    db.mark_video_ready_for_publication('abcdefghijk')
    pair = db.enroll_wallstreet_video('abcdefghijk')
    job = db.claim_wallstreet_render(now=100)
    db.finish_wallstreet_render(pair['id'],job['lease_token'],package={'video':'B.mp4'},now=101)
    pubs = db.get_wallstreet_publications()
    a = next(p for p in pubs if p['platform']=='wechat' and p['variant']=='A')
    b = next(p for p in pubs if p['platform']=='wechat' and p['variant']=='B')
    args = dict(package_sha256='a'*64,asset_sha256='b'*64,video_path='/tmp/B.mp4',evidence_path='/tmp/e')
    assert not db.claim_wallstreet_submission(b['id'],now=40000,**args)
    db.observe_wallstreet_publication(a['id'],state='PUBLISHED',platform_post_id='native-A',evidence_path='/tmp/A',public_at=1000)
    assert not db.claim_wallstreet_submission(b['id'],now=1000+21599,**args)
    assert db.claim_wallstreet_submission(b['id'],now=1000+21600,**args)


def test_native_id_cannot_cross_versions_and_missing_is_not_zero(db):
    ready(db)
    pub = db.get_wallstreet_publications()[0]
    db.observe_wallstreet_publication(pub['id'],state='PUBLISHED',platform_post_id='native-B',evidence_path='/tmp/B',public_at=100)
    with pytest.raises(ValueError,match='ID 不匹配'):
        db.observe_wallstreet_publication(pub['id'],state='PUBLISHED',platform_post_id='native-A',evidence_path='/tmp/A')
    with pytest.raises(ValueError,match='同一已公开'):
        db.record_wallstreet_metrics(pub['id'],platform_post_id='native-A',horizon_hours=24,captured_at=86500,values={},evidence_path='/tmp/m')
    db.record_wallstreet_metrics(pub['id'],platform_post_id='native-B',horizon_hours=24,captured_at=86500,
        values={'views':100,'likes':3,'comments':None,'shares':2},evidence_path='/tmp/m')
    row = next(r for r in db.get_wallstreet_metrics_report() if r['horizon_hours']==24)
    assert row['interaction_rate'] is None and row['values']['comments'] is None
    db.record_wallstreet_metrics(pub['id'],platform_post_id='native-B',horizon_hours=24,captured_at=86501,
        values={'views':100,'likes':3,'comments':5,'shares':2},evidence_path='/tmp/m2')
    row = next(r for r in db.get_wallstreet_metrics_report() if r['horizon_hours']==24)
    assert row['interaction_rate'] == .1
    assert len([r for r in db.get_wallstreet_metrics_report() if r['horizon_hours']==24]) == 1


def test_douyin_ticket_is_bound_to_b_and_single_use(db):
    ready(db)
    pub = next(p for p in db.get_wallstreet_publications() if p['platform']=='douyin')
    claim = db.claim_wallstreet_submission(pub['id'],package_sha256='a'*64,asset_sha256='b'*64,
        video_path='/tmp/B.mp4',evidence_path='/tmp/e')
    ticket, token = claim['_douyin_launch_ticket_id'], claim['_douyin_launch_token']
    assert not db.begin_douyin_browser_launch(ticket,token,video_path='/tmp/A.mp4',asset_sha256='b'*64,payload_sha256='a'*64,require_new_source=True)
    assert db.begin_douyin_browser_launch(ticket,token,video_path='/tmp/B.mp4',asset_sha256='b'*64,payload_sha256='a'*64,require_new_source=True)
    assert not db.begin_douyin_browser_launch(ticket,token,video_path='/tmp/B.mp4',asset_sha256='b'*64,payload_sha256='a'*64,require_new_source=True)


def test_source_pin_kept_until_b_submission_finishes(db):
    pair = db.enroll_wallstreet_video('abcdefghijk',b_only=True)
    assert 'abcdefghijk' in db.wallstreet_pinned_sources()
    job = db.claim_wallstreet_render(now=100)
    db.finish_wallstreet_render(pair['id'],job['lease_token'],error='network',now=101)
    assert 'abcdefghijk' in db.wallstreet_pinned_sources()
    job = db.claim_wallstreet_render(now=1002)
    db.finish_wallstreet_render(pair['id'],job['lease_token'],package={'video':'B.mp4'},now=1003)
    assert 'abcdefghijk' in db.wallstreet_pinned_sources()
    for pub in db.get_wallstreet_publications():
        db.observe_wallstreet_publication(pub['id'],state='PUBLISHED',platform_post_id=f"native-{pub['id']}",evidence_path='/tmp/public')
    assert not db.wallstreet_pinned_sources()


def test_ready_and_enrollment_committed_together(db):
    db.set_wallstreet_experiment(active=True)
    result = db.enroll_wallstreet_video('abcdefghijk',mark_ready=True)
    assert result and result['mode']=='PAIRED'
    assert db.get_video_by_youtube_id('abcdefghijk')['preparation_ready']==1
    assert len(db.get_wallstreet_publications())==4


def test_new_experiment_does_not_enroll_historical_ready_or_discovery(db):
    db.mark_video_ready_for_publication('abcdefghijk')
    db.set_wallstreet_experiment(active=True)
    assert db.enroll_wallstreet_video('abcdefghijk') is None
    db.add_video('discover___','仅浏览',CHANNEL_ID,source='DISCOVERY',score=90)
    assert db.enroll_wallstreet_video('discover___',mark_ready=True) is None


def test_lease_renewal_is_fenced(db):
    db.enroll_wallstreet_video('abcdefghijk',b_only=True)
    first = db.claim_wallstreet_render(now=100,lease_seconds=10)
    assert db.renew_wallstreet_render(first['id'],first['lease_token'],20,now=109)
    assert db.claim_wallstreet_render(now=120) is None
    resumed = db.claim_wallstreet_render(now=130)
    assert not db.renew_wallstreet_render(first['id'],first['lease_token'],20,now=131)
    assert db.renew_wallstreet_render(resumed['id'],resumed['lease_token'],20,now=131)


def test_old_launch_ticket_migration_preserves_tokens_and_indexes(db):
    with db.get_connection() as conn:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='douyin_browser_launch_tickets'").fetchone()[0]
        conn.execute('DROP TABLE douyin_browser_launch_tickets')
        conn.execute(sql.replace(", 'EDITORIAL'",''))
        conn.execute("""INSERT INTO douyin_browser_launch_tickets
            (ticket_id,source_type,source_ref,video_path,asset_sha256,payload_sha256,token_sha256,launch_started_at)
            VALUES ('old-ticket','GENERIC','old-source','A.mp4',?,?,?,'2026-10-01')""",('a'*64,'b'*64,'c'*64))
    migrated = PipelineDB(db.db_path)
    with migrated.get_connection() as conn:
        ticket = dict(conn.execute("SELECT * FROM douyin_browser_launch_tickets WHERE ticket_id='old-ticket'").fetchone())
        indexes = {r[1] for r in conn.execute('PRAGMA index_list(douyin_browser_launch_tickets)')}
    assert ticket['token_sha256']=='c'*64 and ticket['launch_started_at']=='2026-10-01'
    assert ticket['payload_sha256']=='b'*64 and ticket['source_ref']=='old-source'
    assert {'idx_douyin_browser_launch_tickets_pending','idx_douyin_browser_launch_tickets_prelaunch_recovery'} <= indexes


def test_normal_a_future_scope_respects_activation(db):
    assert not db.wallstreet_uses_normal_a('abcdefghijk')
    db.mark_video_ready_for_publication('abcdefghijk')
    db.set_wallstreet_experiment(active=True)
    assert not db.wallstreet_uses_normal_a('abcdefghijk')
    db.add_video('future_____','未来任务',CHANNEL_ID,score=80)
    assert db.wallstreet_uses_normal_a('future_____')
    db.set_wallstreet_experiment(active=False)
    assert not db.wallstreet_uses_normal_a('future_____')
    db.enroll_wallstreet_video('abcdefghijk',b_only=True)
    assert db.wallstreet_uses_normal_a('abcdefghijk')


def test_only_proven_unstarted_ticket_can_recover(db):
    ready(db)
    pub = next(p for p in db.get_wallstreet_publications() if p['platform']=='douyin')
    claim = db.claim_wallstreet_submission(pub['id'],package_sha256='a'*64,asset_sha256='b'*64,
        video_path='/tmp/B.mp4',evidence_path='/tmp/e')
    with db.get_connection() as conn:
        conn.execute("UPDATE douyin_browser_launch_tickets SET issued_at='2020-01-01'")
    assert db.recover_unstarted_wallstreet_douyin()==1
    assert not db.begin_douyin_browser_launch(claim['_douyin_launch_ticket_id'],claim['_douyin_launch_token'],
        video_path='/tmp/B.mp4',asset_sha256='b'*64,payload_sha256='a'*64,require_new_source=True)
    second = db.claim_wallstreet_submission(pub['id'],package_sha256='a'*64,asset_sha256='b'*64,
        video_path='/tmp/B.mp4',evidence_path='/tmp/e')
    assert db.begin_douyin_browser_launch(second['_douyin_launch_ticket_id'],second['_douyin_launch_token'],
        video_path='/tmp/B.mp4',asset_sha256='b'*64,payload_sha256='a'*64,require_new_source=True)
    with db.get_connection() as conn:
        conn.execute("UPDATE douyin_browser_launch_tickets SET issued_at='2020-01-01'")
    assert db.recover_unstarted_wallstreet_douyin()==0

"""发布恢复的真实 SQLite、原生 flock、固定身份和幂等操作验证。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 账户恢复、批次、低分人工许可、软避让与提交防重。 |
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import time
import uuid
from types import SimpleNamespace
import pytest
from config.settings import settings
from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
from video_processing.core.wechat_account_schedule import evaluate
from video_processing.core.wechat_session_lock import WeChatSessionLock
from video_processing.core.task_lease import TaskLease
from video_processing.db.database import PipelineDB
from video_processing.publishing_recovery import PublishingRecoveryService, time_window


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    out=tmp_path/'output';out.mkdir()
    monkeypatch.setattr(type(settings),'default_output_dir',property(lambda _:out))
    monkeypatch.setattr(settings,'wechat_scheduler_policy_path',out/'policy.json')
    monkeypatch.setattr(settings,'wechat_account_scheduler_enabled',True)
    monkeypatch.setattr(settings,'wechat_scheduler_priority_video','')
    monkeypatch.setattr(settings,'wechat_scheduler_daily_limit',20)
    monkeypatch.setattr(settings,'wechat_publishing_paused',False)
    db=PipelineDB(str(out/'pipeline.db'))
    return PublishingRecoveryService(db,tmp_path)


def add(service, key, *, state='FAILED', ready=False, score=70, index=0):
    service.db.add_video(key,key,'test-channel',score=score,slice_index=index)
    if ready:service.db.mark_video_ready_for_publication(key,slice_index=index)
    service.db.update_video_status(key,state,error_msg='technical failure',slice_index=index)
    return service.db.get_video_by_youtube_id(key,index)


def request(service, preview=None, ids=(), **options):
    return dict(operation_id=str(uuid.uuid4()), expected_version=preview['account_version'] if preview else service.status()['version'],
                preview_id=preview['preview_id'] if preview else None,selected_ids=list(ids),reset_quota=False,
                reset_cooldown=False,priority=False,reset_backoff=False,skip_avoidance=False,**{}) | options


def test_all_blockers_quota_rolls_to_twentieth_remaining_and_epoch_reset(recovery):
    guard=recovery.guard;now=time.time()
    row=guard.snapshot();row['schedule']={'sessions':[dict(at=now-10000+i,purpose='发布',task=f't{i}') for i in range(50)],'queue':[],'publications':{},'submit_intents':{'i1WsMclsgOs':{}}}
    row['blocked_until']=now+300;row['next_session_at']=now+100
    guard.path.write_text(json.dumps(row))
    info=guard.evaluate(account_only=True)
    assert {b['code'] for b in info['blockers']}=={'PLATFORM_BACKOFF','SESSION_INTERVAL','QUOTA_24H'}
    assert next(b['until'] for b in info['blockers'] if b['code']=='QUOTA_24H')==row['schedule']['sessions'][30]['at']+86400
    cmd=request(recovery,reset_quota=True)
    result=recovery.execute(cmd)
    assert result['state']=='COMPLETED'
    assert guard.evaluate(account_only=True)['sessions_24h_count']==0
    assert guard.evaluate(account_only=True)['actual_sessions_24h_count']==50
    assert guard.snapshot()['blocked_until']==row['blocked_until']
    assert guard.snapshot()['schedule']['submit_intents']==row['schedule']['submit_intents']
    same=recovery.execute(cmd);assert same['receipt']==result['receipt']
    with pytest.raises(WeChatRequestDeferred):guard.admission('发布','new')
    recovery.execute(request(recovery,reset_cooldown=True))
    guard.admission('发布','new');guard.start_session('发布')
    assert guard.evaluate(account_only=True)['sessions_24h_count']==1
    assert guard.evaluate(account_only=True)['daily_limit']==20
    assert 'SUBMISSION_PROTECTED' in {b['code'] for b in guard.evaluate(task='/output/i1WsMclsgOs_vertical.mp4')['blockers']}


def test_stale_version_new_limit_and_browser_lock_never_reset(recovery):
    cmd=request(recovery,reset_quota=True,reset_cooldown=True)
    recovery.guard.record_limited(endpoint='/post/post_list',code=429)
    result=recovery.execute(cmd)
    assert result['state']=='BLOCKED' and '已变化' in result['reason']
    assert recovery.guard.snapshot()['blocked_until']>time.time()
    with TaskLease(recovery.out/'.wechat_state.json.browser.lock',stage='actual-browser'):
        result=recovery.execute(request(recovery,reset_quota=True))
        assert result['state']=='BLOCKED' and '真实浏览器' in result['reason']
    assert recovery.guard.snapshot()['blocked_until']>time.time()


def test_fixed_thirty_select_six_new_failure_excluded_slices_and_replay(recovery):
    original=[add(recovery,f'video{i:06}',index=1 if i==0 else 0) for i in range(30)]
    preview=recovery.preview();assert preview['total']==30
    ids=[v['id'] for v in original[:6]]
    add(recovery,'later-video')
    cmd=request(recovery,preview,ids,priority=True)
    operation=recovery.execute(cmd)
    assert {i['video_id'] for i in operation['items']}==set(ids)
    assert operation['items'][0]['original']['slice_index']==1
    assert recovery.execute(cmd)['id']==operation['id']
    assert len(recovery.db.list_publishing_recovery_operations()['items'])==1
    other=request(recovery,preview,ids)
    assert all(i['state']=='SKIPPED' for i in recovery.execute(other)['items'])
    recovery.cancel(operation['id'])
    assert all(i['state']=='CANCELLED' for i in recovery.db.get_publishing_recovery_operation(operation['id'])['items'])


def test_changed_after_preview_skipped_deleted_and_partial_restart(recovery):
    a=add(recovery,'before');b=add(recovery,'deleted')
    preview=recovery.preview()
    recovery.db.update_video_status('before','UNCERTAIN')
    with recovery.db.get_connection() as c:c.execute('DELETE FROM processed_videos WHERE id=?',(b['id'],))
    cmd=request(recovery,preview,[a['id'],b['id']])
    op=recovery.execute(cmd)
    assert len(op['items'])==2 and all(i['state']=='SKIPPED' for i in op['items'])
    cmd=request(recovery,reset_quota=True)
    recovery.db.create_publishing_recovery_operation(cmd['operation_id'],cmd,[])
    receipt=recovery.guard.recover_local(operation_id=cmd['operation_id'],expected_version=cmd['expected_version'],reset_quota=True)
    fresh=PublishingRecoveryService(recovery.db,recovery.root)
    op=fresh.execute(cmd)
    assert op['receipt']==receipt and op['state']=='COMPLETED'


def test_protected_i1_login_approval_discovery_and_legacy_estimate(recovery):
    for key,state in [('i1WsMclsgOs','UNCERTAIN'),('underreview','UNDER_REVIEW'),('login','LOGIN_REQUIRED')]:
        add(recovery,key);recovery.db.update_video_status(key,state)
    review=add(recovery,'need-review');legacy=add(recovery,'legacy')
    with recovery.db.get_connection() as c:
        c.execute('UPDATE processed_videos SET publication_review_required=1 WHERE id=?',(review['id'],))
        c.execute('UPDATE processed_videos SET failed_at=NULL WHERE id=?',(legacy['id'],))
    items={i['youtube_id']:i for i in recovery.preview()['items']}
    assert items['i1WsMclsgOs']['category']=='protected'
    assert not items['login']['eligible'] and not items['need-review']['eligible']
    assert items['legacy']['estimated'] and items['legacy']['eligible']


def test_ready_low_score_uses_existing_submission_only_and_single_lease(recovery,monkeypatch):
    v=add(recovery,'ready-low',ready=True,score=60)
    preview=recovery.preview();op=recovery.execute(request(recovery,preview,[v['id']]))
    calls=[]
    def process(video,**kw):
        calls.append(kw)
        assert recovery.db.has_active_manual_publish_lease('ready-low')
        assert video['score']==60 and video['source']=='AUTO'
        recovery.db.update_video_status('ready-low','UNCERTAIN')
    monkeypatch.setattr(type(settings),'is_us_market_guard_window',lambda _:True)
    assert recovery.dispatch_once(SimpleNamespace(_process_single_video=process))
    assert calls==[dict(submission_only=True,claim=False)]
    op=recovery.db.get_publishing_recovery_operation(op['id'])
    assert op['items'][0]['state']=='SUBMITTED_UNVERIFIED'
    assert not recovery.dispatch_once(SimpleNamespace(_process_single_video=process))


def test_soft_avoidance_expiry_and_real_processing_lock(recovery,monkeypatch):
    v=add(recovery,'heavy');preview=recovery.preview()
    op=recovery.execute(request(recovery,preview,[v['id']],skip_avoidance=True))
    monkeypatch.setattr(type(settings),'is_us_market_guard_window',lambda _:True)
    calls=[];manager=SimpleNamespace(_process_single_video=lambda *a,**k:calls.append(k))
    with TaskLease(recovery.out/'pipeline.lock',stage='real-heavy-job'):
        assert not recovery.dispatch_once(manager)
    with recovery.db.get_connection() as c:c.execute('UPDATE publishing_recovery_items SET permit_expires=?',(time.time()-1,))
    assert not recovery.dispatch_once(manager)
    assert calls==[]
    assert '已到期' in recovery.db.get_publishing_recovery_operation(op['id'])['items'][0]['reason']


def test_today_beijing_boundary_and_failure_time_retained_on_retry(recovery):
    now=datetime(2026,10,23,16,30,tzinfo=timezone.utc)
    assert time_window('today',now=now)['start']=='2026-10-23 16:00:00.000000'
    assert time_window('24h',now=now)['start']=='2026-10-22 16:30:00.000000'
    with pytest.raises(ValueError):time_window('custom','2026-01-01T00:00+08:00','2026-10-23T00:00+08:00',now=now)
    a=add(recovery,'failuretime');first=a['failed_at']
    recovery.db.update_video_status('failuretime','PENDING')
    assert recovery.db.get_video_by_youtube_id('failuretime')['failed_at']==first
    with recovery.db.get_connection() as c:assert c.execute('SELECT count(*) FROM publishing_failure_events WHERE video_id=?',(a['id'],)).fetchone()[0]==1


def test_state_saved_then_audit_io_failure_resumes_same_operation(recovery,monkeypatch):
    cmd=request(recovery,reset_quota=True)
    save=recovery.guard._save
    def save_then_fail(row,event):
        save(row,event)
        raise OSError('audit device interrupted')
    monkeypatch.setattr(recovery.guard,'_save',save_then_fail)
    with pytest.raises(OSError):recovery.execute(cmd)
    assert recovery.db.get_publishing_recovery_operation(cmd['operation_id'])['state']=='PLANNED'
    epoch=recovery.guard.snapshot()['schedule']['quota_epoch']
    monkeypatch.setattr(recovery.guard,'_save',save)
    result=recovery.execute(cmd)
    assert result['state']=='COMPLETED'
    assert recovery.guard.snapshot()['schedule']['quota_epoch']==epoch==cmd['operation_id']


def test_final_claim_race_finishes_batch_and_soft_permit_is_not_renewed(recovery,monkeypatch):
    v=add(recovery,'claim-race');op=recovery.execute(request(recovery,recovery.preview(),[v['id']],skip_avoidance=True))
    item=op['items'][0]
    recovery.db.update_video_status('claim-race','UNCERTAIN')
    assert recovery.db.activate_publishing_recovery_item(item['id']) is None
    assert recovery.db.get_publishing_recovery_operation(op['id'])['state']=='COMPLETED'
    v=add(recovery,'permit-once');op=recovery.execute(request(recovery,recovery.preview(),[v['id']],skip_avoidance=True))
    monkeypatch.setattr(type(settings),'is_us_market_guard_window',lambda _:True)
    def deferred(video,**kw):recovery.db.update_video_status('permit-once','PENDING')
    assert recovery.dispatch_once(SimpleNamespace(_process_single_video=deferred))
    first=recovery.db.get_publishing_recovery_operation(op['id'])['items'][0]
    assert first['permit_used'] and first['permit_expires']==op['items'][0]['permit_expires']
    assert not recovery.dispatch_once(SimpleNamespace(_process_single_video=deferred))


@pytest.mark.parametrize('reason', [
    'Social Unrest Review: 平台题材风险：社会动荡 (骚乱)',
    "Channel Policy Reject: 频道策略限制 (matched: 'trump+senate' via en)",
    "Censorship P1 Suspend: 政策敏感拦截 (matched: 'vpn')",
    'CENSORSHIP_P0: policy review',
])
def test_legacy_content_gates_require_review_but_preserve_manual_approval(recovery, reason):
    video=add(recovery,'legacy-review')
    recovery.db.update_video_status('legacy-review','FAILED',error_msg=reason)
    assert not recovery.preview()['items'][0]['eligible']
    recovery.db.set_bypass_censorship('legacy-review',True)
    item=recovery.preview()['items'][0]
    assert item['eligible'] and '已人工放行' in item['approval']


def test_legacy_caption_gate_and_large_log_have_short_actionable_summary(recovery):
    add(recovery,'legacy-caption')
    text=('INFO translating segments\n'*1000)+'ValueError: 第 0 帧原字幕位置或文字不确定，停止出片：Trump Gawks\nAborted!'
    recovery.db.update_video_status('legacy-caption','FAILED',error_msg=text)
    recovery.db.set_bypass_censorship('legacy-caption',True)
    item=recovery.preview()['items'][0]
    assert not item['eligible'] and item['category']=='manual'
    assert '停止出片' in item['reason'] and len(item['reason'])<280
    assert recovery.db.get_video_by_youtube_id('legacy-caption')['error_msg']==text


def test_cancel_during_account_setup_does_not_leave_priority_reservation(recovery,monkeypatch):
    video=add(recovery,'cancel-race')
    cmd=request(recovery,recovery.preview(),[video['id']],priority=True)
    original=recovery.guard.recover_local
    def interrupted(**kwargs):
        recovery.cancel(cmd['operation_id'])
        return original(**kwargs)
    monkeypatch.setattr(recovery.guard,'recover_local',interrupted)
    operation=recovery.execute(cmd)
    assert operation['state']=='CANCELLED'
    assert operation['receipt']['priority_count']>0
    assert recovery.guard.snapshot()['schedule']['recovery_priority']==[]
    assert recovery.db.pending_publishing_recovery_items()==[]

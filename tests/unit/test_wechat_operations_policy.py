"""分用途紧急参数的离线反例：真实临时账本与进程竞争，无平台/网络。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| operations-v1 | 2026-10-24 | Codex | 验证独立预算、滚动边界、原子扣次、保守旧记录、重试和坏配置闭锁。 |
"""
import copy
import datetime as dt
import json
import multiprocessing
import time
from pathlib import Path
import pytest
from config.settings import settings
from video_processing.core.wechat_account_schedule import evaluate, admission
from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
from video_processing.utils.wechat_operations_policy import APPROVED, validate, load_policy, revision, operation_candidates

UTC = dt.timezone.utc

@pytest.fixture
def active(tmp_path, monkeypatch):
    policy = {'schema_version': 1, 'operations': copy.deepcopy(APPROVED),
              'retry_policies': {'write_actions': {'max_retries': 2, 'interval_seconds': 60}}}
    path = tmp_path/'policy.json';path.write_text(json.dumps(policy))
    monkeypatch.setattr(settings,'wechat_operations_enabled',True)
    monkeypatch.setattr(settings,'wechat_operations_policy_path',path)
    monkeypatch.setattr(type(settings),'default_output_dir',property(lambda _self: tmp_path))
    monkeypatch.setattr(settings,'wechat_account_scheduler_enabled',True)
    monkeypatch.setattr(settings,'wechat_scheduler_priority_video','')
    # 旧策略同步会改写单例；本测试必须完整归还这些内存字段，不能污染其他测试。
    for key in ('wechat_reply_min_interval_seconds','wechat_reply_hourly_quota','wechat_reply_max_per_video',
                'wechat_reply_window_start_shanghai','wechat_reply_window_end_shanghai','wechat_reply_approval_mode'):
        monkeypatch.setattr(settings,key,getattr(settings,key))
    return policy,path

def state(sessions=()):
    return {'version':1,'failure_streak':0,'blocked_until':0,'next_session_at':0,
            'schedule':{'sessions':list(sessions),'queue':[],'publications':{}}}

def event(at, operation, task='synthetic'):
    purpose={'publish':'发布','first_comment':'首评','reply':'回复','comment_scan':'评论扫描','post_match':'作品匹配','keepalive':'保活'}[operation]
    return {'at':at,'purpose':purpose,'operation':operation,'task':task}

def test_exact_approved_configuration_and_17_fields(active):
    policy,_=active
    assert load_policy()==policy
    assert len([v for o in policy['operations'].values() for k,v in o.items() if k!='retry_policy'])+2==17
    assert len(revision(policy))==64

@pytest.mark.parametrize('value',[False,1.0,0,-1,None,'20'])
def test_strict_limit_types(active,value):
    policy,_=active;policy['operations']['publish']['rolling_24h_limit']=value
    with pytest.raises(ValueError):validate(policy)

@pytest.mark.parametrize('field,value',[('rolling_24h_limit',1001),('min_interval_seconds',59)])
def test_approved_limits_cannot_be_silently_relaxed(active,field,value):
    policy,_=active;policy['operations']['reply'][field]=value
    with pytest.raises(ValueError):validate(policy)

@pytest.mark.parametrize('bad',['{"schema_version":1,"schema_version":1}','{"schema_version":NaN}','{}','[]'])
def test_bad_active_configuration_fails_closed(active,bad):
    _,path=active;path.write_text(bad)
    with pytest.raises(WeChatRequestDeferred):WeChatRequestGuard(path.parent/'state.json').check()

def test_missing_config_fails_closed(active):
    _,path=active;path.unlink()
    with pytest.raises(WeChatRequestDeferred):load_policy()

def test_independent_pools_and_old_epoch_not_free_quota(active):
    now=time.time();row=state([event(now-400-i,'publish') for i in range(20)])
    row['schedule']['quota_epoch']='new-epoch'
    row['schedule']['last_interaction_at']=now
    row['next_session_at']=now+900
    assert not evaluate(row,now,'发布','new')['allowed']
    for purpose in ['首评','回复','评论扫描','作品匹配','保活']:
        assert evaluate(row,now,purpose,'new')['allowed'], purpose

def test_legacy_ambiguous_interaction_reserves_possible_pools(active):
    now=time.time();old={'at':now-60,'purpose':'评论','task':'synthetic-old'}
    assert operation_candidates(old)=={'first_comment','comment_scan','post_match'}
    row=state([old]);before=json.dumps(row,sort_keys=True)
    assert evaluate(row,now,'首评','new')['sessions_24h_count']==1
    assert not evaluate(row,now,'评论扫描','new')['allowed']
    assert evaluate(row,now,'发布','new')['sessions_24h_count']==0
    assert json.dumps(row,sort_keys=True)==before

def test_rolling_boundaries_and_no_midnight_reset(active):
    now=dt.datetime(2026,10,24,16,0,1,tzinfo=UTC).timestamp()
    row=state([event(now-59-i,'reply') for i in range(50)])
    assert not evaluate(row,now,'回复','new')['allowed']
    assert evaluate(state([event(now-3600,'comment_scan')]),now,'评论扫描','new')['allowed']
    assert evaluate(state([event(now-86400-i,'publish') for i in range(20)]),now,'发布','new')['allowed']

def test_all_blockers_are_reported_and_eta_not_falsely_promised(active):
    now=time.time();row=state([event(now-1-i,'publish') for i in range(20)])
    row['blocked_until']=now+400
    result=evaluate(row,now,'发布','new')
    assert {b['code'] for b in result['blockers']}=={'PLATFORM_BACKOFF','OPERATION_ROLLING_24H_LIMIT','OPERATION_INTERVAL'}
    assert result['until']>now+86000

def test_wait_does_not_charge_or_push_timer_and_gate_can_tighten(active):
    policy,path=active;now=time.time();row=state([event(now-1,'first_comment')]);before=copy.deepcopy(row['schedule']['sessions'])
    assert admission(row,now,'首评','new')
    assert row['schedule']['sessions']==before
    assert evaluate(row,now+61,'首评','new')['allowed']
    policy['operations']['first_comment']['min_interval_seconds']=180;path.write_text(json.dumps(policy))
    assert not evaluate(row,now+61,'首评','new')['allowed']

def test_quota_blocked_queue_does_not_starve_other_purpose(active):
    now=time.time();row=state([event(now-400-i,'publish') for i in range(20)])
    row['schedule']['queue']=[{'at':now-10,'seen':now,'purpose':'发布','task':'queued','key':'key'}]
    assert evaluate(row,now,'首评','comment')['allowed']

def test_known_native_backoff_and_submission_protection_are_unbypassable(active):
    now=time.time();row=state();row['blocked_until']=now+600
    assert not evaluate(row,now,'首评','comment',bypass_cooldown=True)['allowed']
    row['blocked_until']=0;row['schedule']['submit_intents']={'video.mp4':now}
    assert not evaluate(row,now,'发布','video.mp4')['allowed']
    assert not evaluate(row,now,'状态核对','video')['allowed']

def _charge_one(directory,result):
    try:
        guard=WeChatRequestGuard(Path(directory)/'state.json');guard.admission('首评','same-synthetic-task');guard.start_session('首评');result.put('started')
    except WeChatRequestDeferred:result.put('blocked')

def test_two_processes_one_remaining_slot_and_restart_preserves_usage(active):
    policy,path=active;policy['operations']['first_comment'].update(rolling_24h_limit=1,rolling_1h_limit=1)
    path.write_text(json.dumps(policy))
    ctx=multiprocessing.get_context('fork');result=ctx.Queue();children=[ctx.Process(target=_charge_one,args=(str(path.parent),result)) for _ in range(2)]
    for child in children:child.start()
    for child in children:child.join(8);assert child.exitcode==0
    assert sorted(result.get(timeout=2) for _ in children)==['blocked','started']
    guard=WeChatRequestGuard(path.parent/'other-state.json');sessions=guard.snapshot()['schedule']['sessions']
    assert len(sessions)==1 and sessions[0]['operation']=='first_comment' and sessions[0]['attempt_id']
    assert not guard.evaluate('首评',account_only=True)['allowed']

def test_five_video_scan_batch_charges_once_with_empty_scan_skipped(active):
    from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplyBrowserAdapter
    from video_processing.core.wechat_session_lock import guard_wechat_context
    class Context:
        def on(self,*_args):pass
        def route(self,*_args):pass
    adapter=SecondaryReplyBrowserAdapter(state_path=active[1].parent/'state.json')
    with adapter.scan_workflow(['synthetic-'+str(i) for i in range(5)]):
        for _ in range(5):guard_wechat_context(Context())
    guard=WeChatRequestGuard(adapter.state_path)
    assert len(guard.snapshot()['schedule']['sessions'])==1
    assert guard.snapshot()['schedule']['sessions'][0]['operation']=='comment_scan'
    assert not guard.evaluate('评论扫描',account_only=True)['allowed']
    with pytest.raises(Exception):
        with adapter.scan_workflow([]):pass
    assert len(guard.snapshot()['schedule']['sessions'])==1

def _first_comment(db,tmp_path):
    db.add_video('synthetic-policy','synthetic','test',score=80)
    evidence=tmp_path/'synthetic.png';evidence.write_bytes(b'x')
    publication=db.record_wechat_publication_confirmation('synthetic-policy',evidence_path=str(evidence),state='PUBLISHED',platform_post_id='export/synthetic-policy')
    return db.queue_wechat_interaction(publication_id=publication['id'],platform_post_id=publication['platform_post_id'],interaction_type='POLL_STAND',provider='test',comment_text='合成测试')

def test_first_comment_two_technical_retries_each_60s_and_no_fourth(active,tmp_path):
    from video_processing.db.database import PipelineDB
    db=PipelineDB(str(tmp_path/'test.db'));entry=_first_comment(db,tmp_path)
    assert entry['max_attempts']==3
    now=dt.datetime.now(UTC)
    for attempt in range(1,4):
        claimed=db.claim_due_wechat_interaction(now=now,include_uncertain=False)
        assert claimed and claimed['attempt_count']==attempt
        result=db.finish_wechat_interaction_attempt(claimed['id'],claimed['lease_token'],result_status='FAILED',error_message='TargetClosedError: browser has been closed',now=now)
        if attempt<3:
            assert result['status']=='RETRY_WAIT'
            assert dt.datetime.fromisoformat(result['next_attempt_at'])==now+dt.timedelta(seconds=60)
        else:assert result['status']=='FAILED'
        now+=dt.timedelta(seconds=61)
    assert not db.claim_due_wechat_interaction(now=now,include_uncertain=False)

def test_uncertain_never_enters_automatic_first_comment_backfill(active,tmp_path):
    from video_processing.db.database import PipelineDB
    db=PipelineDB(str(tmp_path/'test.db'));_first_comment(db,tmp_path);now=dt.datetime.now(UTC)
    claimed=db.claim_due_wechat_interaction(now=now)
    assert db.mark_wechat_interaction_submit_intent(claimed['id'],claimed['lease_token'],now=now)
    result=db.finish_wechat_interaction_attempt(claimed['id'],claimed['lease_token'],result_status='FAILED',error_message='timeout',now=now)
    assert result['status']=='UNCERTAIN'
    assert db.claim_due_wechat_interaction(now=now+dt.timedelta(hours=1),include_uncertain=False) is None

def test_reply_retry_chain_frozen_and_due_time_persistent(active,tmp_path):
    from video_processing.db.database import PipelineDB
    from tests.unit.secondary_reply_support import approved_task
    db=PipelineDB(str(tmp_path/'test.db'))
    task=approved_task(db,platform_post_id='export/synthetic-reply',comment_id='root',chinese_reply='合成意见',english_reply='Synthetic reply.')
    now=dt.datetime.now(UTC)
    for attempt in range(3):
        claimed=db.claim_approved_reply_task(task_id=task,now_utc=now);assert claimed
        scheduled=db.retry_secondary_reply_before_intent(task,error_message='timeout before submitting',now_utc=now)
        assert scheduled is (attempt<2)
        if scheduled:
            assert not db.claim_approved_reply_task(task_id=task,now_utc=now+dt.timedelta(seconds=59))
        now+=dt.timedelta(seconds=61)
    assert not db.retry_secondary_reply_before_intent(task,error_message='unknown result',now_utc=now)

def test_reply_frequency_no_longer_shares_initial_comments(active,tmp_path,monkeypatch):
    from video_processing.db.database import PipelineDB
    db=PipelineDB(str(tmp_path/'test.db'));monkeypatch.setattr(settings,'wechat_reply_window_start_shanghai','00:00');monkeypatch.setattr(settings,'wechat_reply_window_end_shanghai','24:00')
    entry=_first_comment(db,tmp_path);now=dt.datetime.now(UTC);claimed=db.claim_due_wechat_interaction(now=now)
    assert db.mark_wechat_interaction_submit_intent(claimed['id'],claimed['lease_token'],now=now,enforce_shared_quota=True)
    assert db.check_wechat_reply_quota('export/other-synthetic',now_utc=now)[0]


def test_english_world_retry_uses_same_bounded_chain_and_never_reopens_uncertain(active,tmp_path):
    from tests.unit.test_english_world_delivery_reliability import _package
    from video_processing.utils.submission_progress import write_progress
    db,item=_package(tmp_path)
    db.approve_english_world_submission(item['id'],authorization='AUTO_POLICY')
    for index in range(3):
        evidence=tmp_path/('attempt-'+str(index));evidence.mkdir()
        claimed=db.claim_english_world_submission(item['id'],evidence_dir=str(evidence));assert claimed
        write_progress(evidence,item['mp4_path'])
        allowed=db.retry_english_world_proven_pre_submit(item['id'],attempt_id=claimed['_attempt_id'],evidence_dir=str(evidence),video_path=item['mp4_path'])
        assert allowed is (index<2)
        if allowed:
            assert db.claim_english_world_submission(item['id'],evidence_dir=str(tmp_path/'early')) is None
            with db.get_connection() as c:
                chain=c.execute("SELECT * FROM wechat_write_retry_chains WHERE kind='english_world' AND task_id=?",(item['id'],)).fetchone()
                assert chain['failure_count']==index+1
                due=dt.datetime.strptime(chain['next_attempt_at'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
                assert 58 < (due-dt.datetime.now(UTC)).total_seconds() <= 60
                c.execute("UPDATE wechat_write_retry_chains SET next_attempt_at=datetime('now','-1 minute') WHERE kind='english_world' AND task_id=?",(item['id'],))
    assert db.get_english_world_review_item(item['id'])['state']=='SUBMITTING'
    db.complete_english_world_submission(item['id'],state='UNCERTAIN',uploader_exit_code=3,evidence_dir=str(evidence),attempt_id=claimed['_attempt_id'])
    assert not db.retry_english_world_proven_pre_submit(item['id'],attempt_id=claimed['_attempt_id'],evidence_dir=str(evidence),video_path=item['mp4_path'])


def test_manual_login_does_not_consume_six_business_pools(active):
    now=time.time();row=state([{'at':now-1,'purpose':'登录','task':'manual-login'}])
    for purpose in ['发布','首评','回复','评论扫描','作品匹配','保活']:
        view=evaluate(row,now,purpose,'synthetic-new')
        assert view['allowed'] and view['sessions_24h_count']==0


def test_hot_policy_raise_cannot_renew_old_retry_chain(active,tmp_path):
    from video_processing.db.database import PipelineDB
    from tests.unit.secondary_reply_support import approved_task
    policy,path=active;policy['retry_policies']['write_actions']['max_retries']=1;path.write_text(json.dumps(policy))
    db=PipelineDB(str(tmp_path/'test.db'));task=approved_task(db,platform_post_id='export/synthetic-tight',comment_id='root',chinese_reply='合成意见',english_reply='Synthetic.')
    now=dt.datetime.now(UTC);assert db.claim_approved_reply_task(task_id=task,now_utc=now)
    assert db.retry_secondary_reply_before_intent(task,error_message='timeout',now_utc=now)
    policy['retry_policies']['write_actions']['max_retries']=2;path.write_text(json.dumps(policy))
    assert db.claim_approved_reply_task(task_id=task,now_utc=now+dt.timedelta(seconds=61))
    assert not db.retry_secondary_reply_before_intent(task,error_message='timeout',now_utc=now+dt.timedelta(seconds=61))


def test_legacy_queue_cannot_reserve_opportunity_without_new_worker_reaffirmation(active):
    now=time.time();row=state()
    row['schedule']['queue']=[{'at':now-30000,'seen':now,'purpose':'回复','task':'finished-old-target','key':'old'}]
    assert evaluate(row,now,'发布','new-ready')['allowed']
    assert admission(row,now,'首评','new-comment')==''
    assert len(row['schedule']['queue'])==2
    assert row['schedule']['queue'][-1]['policy_protocol']==1
    assert row['schedule']['queue'][-1]['operation']=='first_comment'
    assert not evaluate(row,now+1,'发布','new-ready')['allowed']
    assert admission(row,now+1,'首评','new-comment',consume=True)==''
    assert evaluate(row,now+2,'发布','new-ready')['allowed']
    assert len(row['schedule']['sessions'])==1


def test_explicit_login_failure_blocks_all_automatic_work_without_charge_and_new_authorization_clears(active):
    from video_processing.core.wechat_auth_state import record_wechat_keepalive_result,record_wechat_authorization
    state_file=active[1].parent/'wechat_state.json';state_file.write_text('{}')
    now=time.time();record_wechat_authorization(state_file,method='interactive',timestamp=now-10)
    record_wechat_keepalive_result(state_file,status='LOGIN_REQUIRED',timestamp=now-1)
    guard=WeChatRequestGuard(state_file)
    for purpose in ['发布','首评','回复','评论扫描','作品匹配','保活']:
        view=guard.evaluate(purpose,account_only=True)
        assert not view['allowed'] and any(b['code']=='AUTH_REQUIRED' for b in view['blockers'])
    with pytest.raises(WeChatRequestDeferred):guard.admission('首评','synthetic')
    assert guard.snapshot().get('schedule',{}).get('sessions',[])==[]
    token=guard.issue_manual_login();manual=WeChatRequestGuard(state_file);manual.consume_manual_login(token);manual.check()
    record_wechat_authorization(state_file,method='interactive',timestamp=now+1)
    assert guard.evaluate('首评',account_only=True)['allowed']
    assert guard.snapshot().get('schedule',{}).get('sessions',[])==[]


def test_manual_login_does_not_override_true_platform_backoff(active):
    from video_processing.core.wechat_auth_state import record_wechat_keepalive_result
    state_file=active[1].parent/'wechat_state.json';state_file.write_text('{}')
    record_wechat_keepalive_result(state_file,status='LOGIN_REQUIRED')
    guard=WeChatRequestGuard(state_file);token=guard.issue_manual_login();guard.consume_manual_login(token)
    row=guard.snapshot();row['blocked_until']=time.time()+300
    guard.path.write_text(json.dumps(row))
    with pytest.raises(WeChatRequestDeferred):guard.check()

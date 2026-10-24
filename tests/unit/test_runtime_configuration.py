"""配置中心合成数据验证：并发、坏配置、权限、回滚和有界等待；禁止平台副作用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | 真实临时文件/SQLite/FastAPI覆盖配置治理与执行入口。 |
"""
import copy
import datetime as dt
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from config.settings import settings
from config.runtime_policy import PolicyStore,ConfigurationError,ConfigurationConflict,atomic,ATTEMPT
from config.runtime_registry import SETTING_FIELDS,TASK_DEFAULTS,OBSERVABILITY_DEFAULTS
from video_processing.utils import runtime_configuration as runtime
from video_processing.utils.wechat_operations_policy import load_policy,OperationsPolicyError
from video_processing.core.wechat_account_schedule import admission
from video_processing.core.wechat_request_guard import WeChatRequestGuard
from video_processing.db.database import PipelineDB
from tests.unit.test_wechat_operations_policy import active,state,event
from tests.unit.test_wechat_interaction_state import _published_target
from web.runtime_configuration import create_runtime_configuration_router

ORIGIN='http://127.0.0.1:9100'


@pytest.fixture
def configured(active,tmp_path,monkeypatch):
    policy,_=active
    monkeypatch.setattr(settings,'runtime_configuration_enabled',False)
    monkeypatch.setattr(settings,'runtime_configuration_path',tmp_path/'runtime')
    monkeypatch.setattr(settings,'wechat_reply_window_start_shanghai','05:30')
    monkeypatch.setattr(settings,'wechat_reply_window_end_shanghai','21:00')
    monkeypatch.setattr(settings,'wechat_reply_approval_mode','hybrid_auto')
    values={name:getattr(settings,name) for name in SETTING_FIELDS}
    data={'wechat_operations':copy.deepcopy(policy),'runtime_settings':values,
          'interaction_controls':{'automatic_replies_enabled':False},
          'task_scheduling':dict(TASK_DEFAULTS),'observability':dict(OBSERVABILITY_DEFAULTS)}
    atomic(settings.runtime_configuration_path/'approved-baseline.json',data)
    initial=runtime.store().initialize(data,validate=runtime.validate_domains)
    monkeypatch.setattr(settings,'runtime_configuration_enabled',True)
    db=PipelineDB(str(tmp_path/'pipeline.db'));db.topic_initialize()
    return initial,db


def save(domains,expected,op='change_00000000000001'):
    return runtime.store().commit(domains,expected_revision=expected,actor='test-operator',reason='合成数据边界验证',
                                  operation_id=op,validate=runtime.approved_validation)


def test_atomic_domains_idempotency_cas_and_restart(configured):
    first,_=configured;data=first.domains();data['wechat_operations']['operations']['publish']['rolling_24h_limit']=19
    second=save(data,first.revision)
    assert load_policy()['operations']['publish']['rolling_24h_limit']==19
    assert save(data,first.revision).revision==second.revision
    assert PolicyStore(settings.runtime_configuration_path).read().revision==second.revision
    with pytest.raises(ConfigurationConflict):save(first.domains(),first.revision,'other_00000000000001')
    with pytest.raises(ConfigurationConflict):save(first.domains(),first.revision)


def test_concurrent_writers_one_success(configured):
    first,_=configured
    def run(n):
        data=first.domains();data['wechat_operations']['operations']['publish']['rolling_24h_limit']=n
        try:return save(data,first.revision,'concurrent_'+str(n)+'_00000000000000').revision
        except ConfigurationConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[18,19]))
    assert results.count('conflict')==1
    assert len(runtime.store().history())==2


@pytest.mark.parametrize('kind',['missing','duplicate','hash','nan'])
def test_invalid_active_fails_closed(configured,kind):
    first,_=configured;root=settings.runtime_configuration_path
    if kind=='missing':(root/'active.json').unlink()
    if kind=='duplicate':(root/'active.json').write_text('{"schema_version":1,"schema_version":1}')
    if kind=='hash':(root/'versions'/first.version/'observability.json').write_text('{}')
    if kind=='nan':(root/'active.json').write_text('{"schema_version":NaN}')
    with pytest.raises(OperationsPolicyError):load_policy()


@pytest.mark.parametrize('field,value',[('publish.rolling_24h_limit',21),('first_comment.min_interval_seconds',59),('reply.rolling_1h_limit',51)])
def test_no_ordinary_relaxation(configured,field,value):
    first,_=configured;data=first.domains();op,key=field.split('.');data['wechat_operations']['operations'][op][key]=value
    with pytest.raises(ValueError):save(data,first.revision)
    assert runtime.store().read().revision==first.revision


def test_non_wechat_frequency_cannot_silently_expand(configured):
    first,_=configured;data=first.domains();data['runtime_settings']['codex_subtitle_batch_size']+=1
    with pytest.raises(ValueError):save(data,first.revision)


def test_frozen_attempt_and_immediate_setting_getter(configured):
    first,_=configured;token=runtime.freeze_attempt(first)
    try:
        data=first.domains();data['runtime_settings']['copywriter_agy_timeout_seconds']=10
        second=save(data,first.revision)
        assert settings.copywriter_agy_timeout_seconds==first.domains()['runtime_settings']['copywriter_agy_timeout_seconds']
        assert runtime.snapshot(fresh=True).revision==second.revision
    finally:runtime.finish_attempt(token)
    assert settings.copywriter_agy_timeout_seconds==10


def test_reply_business_switch_persistent_overrides_process_flags_and_stops_new_claims(configured,tmp_path,monkeypatch):
    first,db=configured
    monkeypatch.setattr(settings,'enable_wechat_secondary_reply',True)
    monkeypatch.setattr(settings,'enable_wechat_secondary_reply_live_submission',True)
    assert settings.enable_wechat_secondary_reply is False  # 旧cron环境不能覆盖活动总开关。
    data=first.domains();data['interaction_controls']['automatic_replies_enabled']=True
    second=save(data,first.revision)
    assert settings.enable_wechat_secondary_reply and settings.enable_wechat_secondary_reply_live_submission
    token=runtime.freeze_attempt(second)
    try:
        save(first.domains(),second.revision,'turn_off_000000000001')
        assert settings.enable_wechat_secondary_reply is False  # 停止新领取不被在途快照掩盖。
        assert db.claim_approved_reply_task() is None
        assert runtime.snapshot().revision==second.revision  # 其他在途参数仍为旧快照。
    finally:runtime.finish_attempt(token)
    assert PolicyStore(settings.runtime_configuration_path).read().domains()['interaction_controls']['automatic_replies_enabled'] is False


def test_same_started_attempt_not_charged_twice_and_last_slot_atomic(configured):
    first,_=configured;data=first.domains();data['wechat_operations']['operations']['publish']['rolling_24h_limit']=1
    save(data,first.revision)
    guard=WeChatRequestGuard(settings.default_output_dir/'wechat_state.json');guard.admission('发布','synthetic-publish')
    guard.start_session('发布');guard.start_session('发布')
    assert len(guard.snapshot()['schedule']['sessions'])==1
    next_guard=WeChatRequestGuard(settings.default_output_dir/'wechat_state.json')
    from video_processing.utils.wechat_operations_policy import WeChatRequestDeferred
    with pytest.raises(WeChatRequestDeferred):next_guard.admission('发布','another-synthetic-publish')


def test_two_consumers_compete_for_last_slot_with_active_version(configured):
    first,_=configured;data=first.domains();data['wechat_operations']['operations']['publish']['rolling_24h_limit']=1
    save(data,first.revision)
    from video_processing.utils.wechat_operations_policy import WeChatRequestDeferred
    def consume(index):
        guard=WeChatRequestGuard(settings.default_output_dir/'wechat_state.json')
        try:
            guard.admission('发布','synthetic-'+str(index));guard.start_session('发布');return True
        except WeChatRequestDeferred:return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(consume,[1,2]))
    assert results.count(True)==1
    assert len(WeChatRequestGuard(settings.default_output_dir/'wechat_state.json').snapshot()['schedule']['sessions'])==1


def test_running_executor_acknowledges_new_revision_in_five_seconds(configured):
    first,_=configured;path=settings.default_output_dir/'runtime_config_workers/secondary-reply.json'
    with runtime.presence('secondary-reply'):
        deadline=time.monotonic()+2
        while not path.exists() and time.monotonic()<deadline:time.sleep(.01)
        data=first.domains();data['observability']['wait_notice_cooldown_seconds']=3601
        started=time.monotonic();second=save(data,first.revision)
        while time.monotonic()-started<5.5:
            if json.loads(path.read_text())['loaded_revision']==second.revision:break
            time.sleep(.02)
        assert json.loads(path.read_text())['loaded_revision']==second.revision
        assert time.monotonic()-started<5.5
    assert json.loads(path.read_text())['lifecycle']=='STOPPED'


def test_commit_and_rollback_preserve_nonempty_uncertain_fact(configured,tmp_path):
    first,db=configured;row=waiting(db,tmp_path)
    assert db.mark_wechat_interaction_submit_intent(row['id'],row['lease_token'])
    before=db.finish_wechat_interaction_attempt(row['id'],row['lease_token'],result_status='UNCERTAIN')
    data=first.domains();data['observability']['wait_notice_cooldown_seconds']=3601
    second=save(data,first.revision)
    assert runtime.recompute_waits(db,second)==0
    save(first.domains(),second.revision,'preserve_000000000001')
    after=db.get_wechat_interaction_by_post_id(row['platform_post_id'])
    assert after==before and after['status']=='UNCERTAIN' and after['submit_intent_at']


def test_duplicate_json_request_rejected(api_setup):
    client,_,first=api_setup
    body='{"expected_revision":"'+first.revision+'","reason":"一次","reason":"二次","domains":{}}'
    assert client.post('/api/runtime-configuration/preview',content=body).status_code==422


def test_rollback_does_not_refund_sessions(configured):
    first,_=configured;now=time.time();row=state([event(now-10,'publish')]);before=copy.deepcopy(row)
    data=first.domains();data['wechat_operations']['operations']['publish']['rolling_24h_limit']=1
    second=save(data,first.revision)
    assert '额度已满' in admission(row,now,'发布','next')
    assert row['schedule']['sessions']==before['schedule']['sessions']
    save(first.domains(),second.revision,'rollback_000000000001')
    assert row['schedule']['sessions']==before['schedule']['sessions']


def waiting(db,tmp_path):
    p=_published_target(db,tmp_path)
    db.queue_wechat_interaction(publication_id=p['id'],platform_post_id=p['platform_post_id'],interaction_type='POLL_STAND',provider='synthetic',comment_text='合成测试评论')
    return db.claim_due_wechat_interaction(platform_post_id=p['platform_post_id'])


def test_known_gate_not_fixed_300_seconds_and_no_attempt_charge(configured,tmp_path):
    first,db=configured;row=waiting(db,tmp_path);now=dt.datetime.now(dt.timezone.utc);until=now.timestamp()+61
    result=db.finish_wechat_interaction_attempt(row['id'],row['lease_token'],result_status='DEFERRED',now=now,
        error_message='first_comment 过去60分钟额度已满',admission={'until':until,'blockers':[{'code':'OPERATION_ROLLING_1H_LIMIT'}]})
    assert result['attempt_count']==0 and result['status']=='RETRY_WAIT'
    assert dt.datetime.fromisoformat(result['next_attempt_at']).timestamp()==pytest.approx(until,abs=.001)
    assert result['policy_wait_revision']==first.revision


def test_config_change_recomputes_only_safe_waits(configured,tmp_path):
    first,db=configured;row=waiting(db,tmp_path)
    db.finish_wechat_interaction_attempt(row['id'],row['lease_token'],result_status='DEFERRED',error_message='first_comment 操作间隔未到')
    data=first.domains();data['observability']['wait_notice_cooldown_seconds']=7200
    second=save(data,first.revision)
    assert runtime.recompute_waits(db,second)==1
    result=db.get_wechat_interaction_by_post_id(row['platform_post_id'])
    assert result['attempt_count']==0 and result['submit_intent_at'] is None
    assert result['policy_wait_revision']==second.revision
    assert runtime.recompute_waits(db,second)==0


def test_wait_notification_dedup_parameters_and_success_untouched(configured):
    from video_processing.interaction.notifier import InteractionNotifier
    notifier=InteractionNotifier(db=object())
    with patch('video_processing.interaction.notifier.send_text',return_value=SimpleNamespace(state='ACCEPTED')) as send:
        notifier.notify_interaction_result(video_title='合成',platform_post_id='synthetic',status='RETRY_WAIT',draft=None,error_message='same gate')
        assert send.call_args.kwargs['cooldown_seconds']==3600
        assert send.call_args.kwargs['dedupe_key']=='wait:synthetic:same gate'
        notifier.notify_interaction_result(video_title='合成',platform_post_id='synthetic',status='COMMENTED',draft=None)
        assert 'cooldown_seconds' not in send.call_args.kwargs


@pytest.fixture
def api_setup(configured):
    first,db=configured;app=FastAPI();app.include_router(create_runtime_configuration_router(db,port=9100))
    app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[2]/'src/web/static'))
    with TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50000)) as client:
        page=client.get('/runtime-configuration');assert page.status_code==200
        csrf=re.search(r'name="runtime-csrf" content="([a-f0-9]+)"',page.text).group(1)
        client.headers.update({'Origin':ORIGIN,'X-Runtime-CSRF':csrf})
        yield client,db,first


def test_api_real_edit_preview_apply_and_rollback(api_setup):
    client,db,first=api_setup
    data=client.get('/api/runtime-configuration/current').json();assert len(data['catalog']['groups'])==18
    candidate=data['domains'];candidate['wechat_operations']['operations']['publish']['rolling_24h_limit']=19
    report=client.post('/api/runtime-configuration/preview',json={'expected_revision':data['revision'],'domains':candidate,'reason':'合成调整验证'}).json()
    assert report['can_apply'] and report['changes'][0]['after']==19
    applied=client.post('/api/runtime-configuration/apply',json={'preview_id':report['preview_id'],'operation_id':'api_change_0000000001'});assert applied.status_code==200
    repeat=client.post('/api/runtime-configuration/apply',json={'preview_id':report['preview_id'],'operation_id':'api_change_0000000001'})
    assert repeat.json()['revision']==applied.json()['revision']
    rollback=client.post('/api/runtime-configuration/preview',json={'expected_revision':applied.json()['revision'],'rollback_version':first.version,'reason':'合成回滚验证'}).json()
    assert rollback['can_apply']
    assert client.post('/api/runtime-configuration/apply',json={'preview_id':rollback['preview_id'],'operation_id':'api_rollback_00000001'}).status_code==200
    assert load_policy()['operations']['publish']['rolling_24h_limit']==20
    assert len(client.get('/api/runtime-configuration/history').json()['versions'])==3


@pytest.mark.parametrize('headers',[{'Origin':'http://evil.invalid'},{'Origin':''},{'Host':'evil.invalid:9100'},{'X-Runtime-CSRF':'fake'},{'Cookie':'runtime_local_session='+'a'*64}])
def test_api_security_and_csrf(api_setup,headers):
    client,_,first=api_setup
    r=client.post('/api/runtime-configuration/preview',headers=headers,json={'expected_revision':first.revision,'domains':first.domains(),'reason':'伪造请求测试'})
    assert r.status_code==403
    assert runtime.store().read().revision==first.revision


def test_approval_not_forgeable_and_no_secrets_in_catalog(api_setup,monkeypatch):
    client,_,first=api_setup;monkeypatch.setattr(settings,'telegram_bot_token','SYNTHETIC_NEVER_EXPOSE')
    data=client.get('/api/runtime-configuration/current');assert 'SYNTHETIC_NEVER_EXPOSE' not in data.text
    candidate=first.domains();candidate['wechat_operations']['operations']['publish']['rolling_24h_limit']=21
    body={'expected_revision':first.revision,'domains':candidate,'reason':'非法放宽测试'}
    report=client.post('/api/runtime-configuration/preview',json=body).json();assert report['approval_required'] and not report['can_apply']
    assert client.post('/api/runtime-configuration/apply',json={'preview_id':report['preview_id'],'operation_id':'not_approved_00000001'}).status_code==422
    assert client.post('/api/runtime-configuration/preview',json={**body,'approved':True}).status_code==422

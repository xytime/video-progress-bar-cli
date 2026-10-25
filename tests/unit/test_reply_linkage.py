"""回复联动的配置、门禁容量和双入口事务验收；全部合成数据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 覆盖真实配置保存、冲突、执行者读取和三日滚动额度。 |
"""
import copy
import json
import re
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from config.settings import settings
from config.reply_linkage import calculate, DEFAULT_LINKAGE
from config.runtime_policy import atomic
from video_processing.utils import runtime_configuration as runtime
from video_processing.utils import reply_linked_policy as linked
from video_processing.utils.secondary_reply_policy import load_policy
from video_processing.core.wechat_account_schedule import _operation_blocks
from web.secondary_reply_settings import create_secondary_reply_settings_router
from web.runtime_configuration import create_runtime_configuration_router
from tests.unit.test_runtime_configuration import configured
from tests.unit.test_wechat_operations_policy import active, event

ORIGIN='http://127.0.0.1:9100'


def config(daily=1000):
    return {'schema_version':1,'window_start_shanghai':'00:00','window_end_shanghai':'24:00',
            'approval_mode':'hybrid_auto','max_per_video':18,'daily_quota':daily,
            'hourly_quota':50,'min_interval_seconds':60,'linkage':{**DEFAULT_LINKAGE,'initialized':True}}


@pytest.fixture
def linked_api(configured, monkeypatch):
    first,db=configured
    monkeypatch.setattr(linked,'verified_cadence',lambda:72)
    monkeypatch.setattr(settings,'wechat_reply_window_start_shanghai','00:00')
    monkeypatch.setattr(settings,'wechat_reply_window_end_shanghai','24:00')
    domains=first.domains();domains['interaction_controls']['reply_strategy']={k:config()[k] for k in ['window_start_shanghai','window_end_shanghai','approval_mode']}
    atomic(settings.runtime_configuration_path/'approved-baseline.json',domains)
    runtime.store().commit(domains,expected_revision=first.revision,actor='synthetic',reason='合成全天基线',operation_id='synthetic_all_day_0001',validate=runtime.approved_validation)
    app=FastAPI();app.include_router(create_runtime_configuration_router(db,port=9100))
    app.include_router(create_secondary_reply_settings_router(active=settings.wechat_reply_policy_path,access_db=db,history_lookup=lambda limit:[]))
    app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[2]/'src/web/static'))
    with TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50000)) as client:
        page=client.get('/runtime-configuration');assert page.status_code==200
        csrf=re.search(r'name="runtime-csrf" content="([a-f0-9]+)"',page.text).group(1)
        client.headers.update({'Origin':ORIGIN,'X-Runtime-CSRF':csrf})
        yield client,db


@pytest.mark.parametrize('daily,hourly,interval',[(1000,50,72),(800,40,72),(500,25,144),(200,10,360),(1,1,3600)])
def test_three_days_against_actual_rolling_guard(daily,hourly,interval):
    value,report=calculate(config(daily),72)
    assert (value['hourly_quota'],value['min_interval_seconds'])==(hourly,interval)
    assert report['opportunities']>=daily
    from config.wechat_operations_schema import APPROVED
    policy={'operations':copy.deepcopy(APPROVED)};policy['operations']['reply'].update(rolling_24h_limit=daily,rolling_1h_limit=hourly,min_interval_seconds=interval)
    sessions=[];days=[0,0,0]
    for now in range(0,3*86400,72):
        if not _operation_blocks(sessions,now,'reply',policy)[0]:
            sessions.append(event(now,'reply'));days[now//86400]+=1
    assert days==[daily]*3


def test_manual_override_restore_short_window_and_unknown_schedule():
    value=config(200);value['hourly_quota']=8;value['linkage']['hourly_quota']='manual'
    computed,report=calculate(value,72)
    assert computed['hourly_quota']==8 and report['insufficient']
    computed['daily_quota']=500
    assert calculate(computed,72)[0]['hourly_quota']==8
    computed['linkage']['hourly_quota']='auto'
    assert calculate(computed,72)[0]['hourly_quota']==25
    value=config();value.update(window_start_shanghai='23:00',window_end_shanghai='01:00')
    assert calculate(value,72)[1]['insufficient']
    with pytest.raises(ValueError,match='周期尚未核实'):calculate(config(),None)
    value=config();value['linkage']={'initialized':True,'hourly_quota':'manual','min_interval_seconds':'manual'}
    assert calculate(value,None)[1]['opportunities'] is None


def test_saved_modes_cross_entry_and_execution_consistency(linked_api):
    client,_=linked_api
    before=client.get('/api/secondary-reply-settings').json()
    assert before['config']['min_interval_seconds']==60  # 载入不改写已有值。
    proposal=client.post('/api/runtime-configuration/reply-recommend',json={'config':config(200)})
    assert proposal.status_code==200,proposal.text
    value=proposal.json()['config']
    saved=client.put('/api/secondary-reply-settings',json={'config':value,'expected_digest':before['digest'],'expected_revision':before['revision']})
    assert saved.status_code==200,saved.text
    domains=client.get('/api/runtime-configuration/current').json()['domains']
    reply=domains['wechat_operations']['operations']['reply']
    assert (reply['rolling_24h_limit'],reply['rolling_1h_limit'],reply['min_interval_seconds'])==(200,10,360)
    loaded=load_policy(settings.wechat_reply_policy_path)
    assert loaded['daily_quota']==200 and settings.wechat_reply_hourly_quota==10
    current=client.get('/api/secondary-reply-settings').json()
    value=current['config'];value['hourly_quota']=8;value['linkage']['hourly_quota']='manual'
    saved=client.put('/api/secondary-reply-settings',json={'config':value,'expected_digest':current['digest'],'expected_revision':current['revision']})
    assert saved.status_code==200,saved.text
    current=client.get('/api/runtime-configuration/current').json();domains=current['domains']
    assert domains['interaction_controls']['reply_linkage']['hourly_quota']=='manual'
    domains['wechat_operations']['operations']['reply']['rolling_24h_limit']=500
    preview=client.post('/api/runtime-configuration/preview',json={'domains':domains,'expected_revision':current['revision'],'reason':'合成跨入口联动'})
    assert preview.status_code==200,preview.text
    assert preview.json()['can_apply']
    assert preview.json()['reply_capacity']['insufficient']
    applied=client.post('/api/runtime-configuration/apply',json={'preview_id':preview.json()['preview_id'],'operation_id':'linked_cross_entry_0001'})
    assert applied.status_code==200,applied.text
    now=client.get('/api/secondary-reply-settings').json()
    assert now['config']['daily_quota']==500 and now['config']['hourly_quota']==8
    assert now['config']['linkage']['hourly_quota']=='manual'
    assert client.put('/api/secondary-reply-settings',json={'config':value,'expected_digest':before['digest'],'expected_revision':before['revision']}).status_code==409
    assert runtime.store().read().domains()['wechat_operations']['operations']['first_comment']==domains['wechat_operations']['operations']['first_comment']


def test_invalid_and_untrusted_linkage_fail_closed(linked_api,monkeypatch):
    client,_=linked_api
    first=runtime.store().read().revision
    for key,bad in [('daily_quota',True),('daily_quota',1001),('linkage',{'initialized':True}),('hourly_quota',51)]:
        value=config();value[key]=bad
        if key=='hourly_quota':value['linkage']['hourly_quota']='manual'
        response=client.post('/api/runtime-configuration/reply-recommend',json={'config':value})
        assert response.status_code==422,response.text
    monkeypatch.setattr(linked,'verified_cadence',lambda:None)
    assert client.post('/api/runtime-configuration/reply-recommend',json={'config':config()}).status_code==422
    assert runtime.store().read().revision==first


def test_cadence_comes_from_loaded_definition_and_fails_closed(tmp_path,monkeypatch):
    import plistlib
    from video_processing.core import reply_send_schedule as schedule
    label='com.videopipeline.secondary-reply-send'
    definition={'Label':label,'WorkingDirectory':str(settings.project_root),'StartInterval':72,
                'ProgramArguments':['python',str(settings.project_root/'scripts/wechat_secondary_reply.py'),'tick','--max-reconcile','0','--max-submit','1','--scan-posts','0','--max-drafts','0']}
    path=tmp_path/'synthetic.plist'
    class Host:
        loaded=True
        disabled_value=False
        def __init__(self,*args):pass
        def service(self,requested):
            assert requested==label
            return {'loaded':self.loaded,'path':str(path)}
        def disabled(self):return {label:self.disabled_value}
    monkeypatch.setattr(schedule,'Schedules',Host)
    path.write_bytes(plistlib.dumps(definition))
    assert schedule.verified_cadence()==72
    Host.disabled_value=True;assert schedule.verified_cadence() is None
    Host.disabled_value=False;Host.loaded=False;assert schedule.verified_cadence() is None
    Host.loaded=True
    for key,bad in [('StartInterval',True),('StartInterval',0),('KeepAlive',True),('WorkingDirectory','/wrong-root')]:
        path.write_bytes(plistlib.dumps({**definition,key:bad}));assert schedule.verified_cadence() is None
    definition['ProgramArguments'][-1]='1'
    path.write_bytes(plistlib.dumps(definition));assert schedule.verified_cadence() is None


def test_legacy_strategy_fallback_keeps_file_authority(configured,monkeypatch):
    first,_=configured
    from video_processing.utils.secondary_reply_policy import current_policy_from_settings,_runtime_policy
    legacy=current_policy_from_settings();legacy.update(window_start_shanghai='08:30',window_end_shanghai='23:00',approval_mode='manual')
    settings.wechat_reply_policy_path.write_text(json.dumps(legacy))
    monkeypatch.setattr(settings,'wechat_reply_window_start_shanghai','00:00')
    monkeypatch.setattr(settings,'wechat_reply_window_end_shanghai','24:00')
    domains=first.domains();domains['interaction_controls'].pop('reply_strategy',None)
    view=linked.editor_config(domains)
    assert view['window_start_shanghai']=='08:30' and view['approval_mode']=='manual'
    value=_runtime_policy(first)
    assert value['window_start_shanghai']=='08:30' and value['window_end_shanghai']=='23:00'


def test_long_manual_interval_uses_existing_operations_boundary(linked_api):
    client,_=linked_api
    current=client.get('/api/secondary-reply-settings').json()
    value=current['config'];value['min_interval_seconds']=604800
    value['linkage']={'initialized':True,'hourly_quota':'manual','min_interval_seconds':'manual'}
    saved=client.put('/api/secondary-reply-settings',json={'config':value,'expected_digest':current['digest'],'expected_revision':current['revision']})
    assert saved.status_code==200,saved.text
    now=client.get('/api/runtime-configuration/current')
    assert now.status_code==200 and now.json()['reply_capacity']['insufficient']
    assert load_policy(settings.wechat_reply_policy_path)['min_interval_seconds']==604800

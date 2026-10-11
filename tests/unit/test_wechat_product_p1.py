"""P1 历史、影响、资料与等待账本；不连接实际发布平台。"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from tests.unit.test_wechat_product_groups import api_setup, data
from video_processing.core.wechat_product_policy import parse_product_policy
from video_processing.utils.wechat_product_config import load_policy, save_policy
from video_processing.utils.wechat_product_lifecycle import impact, list_revisions, read_revision
from video_processing.utils.wechat_product_waits import ProductWaitStore
from video_processing.core.wechat_product_library import FIELDS


def record(**values):
    row = {k:'' for k in FIELDS}
    row.update(identity_status='UNVERIFIED', enabled=True, **values)
    return row


def test_history_restore_new_version_preserves_old_snapshot(api_setup):
    client, active, status, _ = api_setup
    old = load_policy(active)
    draft = json.loads(old.serialized)
    draft['profiles']['english_world']['candidates'] = ['finance']
    report = client.post('/api/product-settings/impact',json=dict(config=draft,expected_digest=old.digest)).json()
    assert report['changed'] and report['preview_only']
    assert load_policy(active).digest == old.digest and not status.exists()
    saved=client.put('/api/product-settings',json=dict(config=draft,expected_digest=old.digest)).json()
    new=load_policy(active)
    assert len(list_revisions(active))==2 and new.digest!=old.digest
    restored=client.post('/api/product-settings/history/restore-draft',json=dict(digest=old.digest,expected_digest=new.digest)).json()
    assert restored['draft_only'] and load_policy(active).digest==new.digest
    result=client.put('/api/product-settings',json=dict(config=restored['config'],expected_digest=new.digest))
    assert result.status_code==200
    latest=load_policy(active)
    assert latest.version not in {old.version,new.version}
    assert latest.decide(content_type='ENGLISH_WORLD_SHORT').candidates==old.decide(content_type='ENGLISH_WORLD_SHORT').candidates
    assert read_revision(active,old.digest).serialized==old.serialized
    assert len(list_revisions(active))==3


def test_history_corruption_and_stale_impact_fail_closed(api_setup):
    client,active,_,_=api_setup
    old=load_policy(active);draft=json.loads(old.serialized);draft['version']='second'
    save_policy(draft,active)
    assert client.post('/api/product-settings/impact',json=dict(config=draft,expected_digest=old.digest)).status_code==409
    snapshot=active.with_name(active.stem+'_history')/(old.digest+'.json');snapshot.write_text('{}')
    assert client.post('/api/product-settings/history/restore-draft',json=dict(digest=old.digest,expected_digest=load_policy(active).digest)).status_code==422
    assert list_revisions(active)[1]['error']


def test_impact_unknown_not_unchanged(api_setup):
    _,active,_,_=api_setup;p=load_policy(active)
    report=impact(active,json.loads(p.serialized),p.digest,[dict(youtube_id='../../bad',title='坏任务')],active.parent)
    assert len(report['unknown'])==1 and report['unchanged']==0


def test_pending_identity_cannot_enter_candidates(data):
    data['library']={'new':record(title='待核实新书',shop='快捷英语教辅图书',merchant_appid='wx490e65efa3751b8c')}
    assert parse_product_policy(data)
    data['default_candidates']=['new']
    with pytest.raises(ValueError):parse_product_policy(data)


def verified(data):
    row=record(product_id='700007',title='已核实的新书',account_id='publisher-account',verified_at='2026-01-01T00:00:00+08:00',verified_source='人工核对后台记录')
    row['identity_status']='VERIFIED'
    data['library']={'new':row}
    data['products']['new']={k:row[k] for k in ['product_id','title','enabled','verified_at','verified_source']}
    return row


def test_verified_identity_and_same_save_disable_reference(data, api_setup):
    row=verified(data);data['profiles']['english_world']['candidates']=['new']
    assert parse_product_policy(data).decide(content_type='ENGLISH_WORLD_SHORT').candidates[0].product_id=='700007'
    client,active,_,_=api_setup;digest=load_policy(active).digest
    row['enabled']=False;data['products']['new']['enabled']=False
    res=client.put('/api/product-settings',json=dict(config=data,expected_digest=digest))
    assert res.status_code==422 and '引用' in res.json()['detail']
    data['profiles']['english_world']['candidates']=['news']
    assert client.put('/api/product-settings',json=dict(config=data,expected_digest=digest)).status_code==200


@pytest.mark.parametrize('field,value',[('account_id',''),('verified_at','2026-01-01'),('verified_source',''),('product_id','wx490e65efa3751b8c')])
def test_verified_requires_exact_account_identity_evidence(data,field,value):
    row=verified(data);row[field]=value
    if field in data['products']['new']:data['products']['new'][field]=value
    with pytest.raises(ValueError):parse_product_policy(data)


def test_refresh_does_not_write_or_claim_connected(api_setup):
    client,active,status,_=api_setup;before=active.read_bytes()
    assert client.post('/api/product-settings/catalog/refresh').json()['refreshed'] is False
    waits=client.get('/api/product-settings/waits').json()
    assert waits['records']==[] and waits['scheduler_connected'] is False
    assert active.read_bytes()==before and not status.exists()


def store(tmp_path):
    now=[1000.0];return ProductWaitStore(tmp_path/'waits.json',clock=lambda:now[0]),now


def defer(s,key='generic:abc:0',**kw):
    args=dict(reason='PRODUCT_UNAVAILABLE',config_digest='v1',artifacts_digest='artifact1',submission_state='NOT_SUBMITTED')
    args.update(kw);return s.defer(key,**args)


def claim(s,key='generic:abc:0',**kw):
    args=dict(current_config_digest='v1',current_artifacts_digest='artifact1');args.update(kw)
    return s.claim_check(key,**args)


def test_wait_persists_backoff_and_excludes_concurrent_claims(tmp_path):
    s,now=store(tmp_path);defer(s)
    assert claim(s) is None
    now[0]=1300;lease=claim(s)
    assert lease['check_only'] and not lease['upload_authorized'] and claim(s) is None
    other=ProductWaitStore(s.path,clock=lambda:now[0]);assert claim(other) is None
    result=s.finish_check('generic:abc:0',lease['lease_token'],available=False,reason='QUOTA_EXHAUSTED')
    assert result['next_check_at']==1900 and result['state']=='WAITING'
    assert claim(s) is None


def test_wait_configuration_change_only_grants_check_not_publish(tmp_path):
    s,now=store(tmp_path);defer(s)
    lease=claim(s,current_config_digest='v2')
    row=s.finish_check('generic:abc:0',lease['lease_token'],available=True,reason='AVAILABLE')
    assert row['state']=='READY_FOR_EXISTING_GATES' and not row['upload_authorized']
    assert claim(s) is None


@pytest.mark.parametrize('submission',['SUBMITTED_BOUND','UNDER_REVIEW','UNKNOWN','PUBLISHED'])
def test_accepted_or_uncertain_submission_never_reuploads(tmp_path,submission):
    s,_=store(tmp_path);assert defer(s,submission_state=submission)['state']=='VERIFY_SUBMISSION'
    assert claim(s,current_config_digest='new') is None
    assert defer(s)['state']=='VERIFY_SUBMISSION'


def test_artifact_change_identity_conflict_and_limit_do_not_autorecover(tmp_path):
    s,now=store(tmp_path);defer(s)
    assert claim(s,current_artifacts_digest='changed') is None
    assert s.records()[0]['state']=='BLOCKED'
    defer(s,reason='PRODUCT_IDENTITY_CONFLICT');assert claim(s,current_config_digest='new') is None
    defer(s,wait_policy=dict(base_seconds=60,max_seconds=120,max_checks=1,lease_seconds=30))
    now[0]+=60;lease=claim(s)
    result=s.finish_check('generic:abc:0',lease['lease_token'],available=False,reason='PRODUCT_UNAVAILABLE')
    assert result['state']=='CHECK_LIMIT'
    now[0]+=10000;assert claim(s) is None
    assert claim(s,observation_generation='reliable-new-observation') is not None


def test_english_and_general_waits_independent_and_expired_result_refused(tmp_path):
    s,now=store(tmp_path);defer(s);defer(s,key='english:review1')
    now[0]+=300;a=claim(s);b=claim(s,key='english:review1');assert a and b
    now[0]+=121
    with pytest.raises(ValueError):s.finish_check('generic:abc:0',a['lease_token'],available=True,reason='AVAILABLE')
    assert claim(s) is None


def test_import_account_must_match_verified_library(api_setup):
    from tests.unit.test_wechat_catalog_import import document
    client,active,_,_=api_setup
    data=json.loads(load_policy(active).serialized);verified(data);save_policy(data,active)
    doc=document(list(data['products'].values()));doc['account_id']='different-publisher'
    response=client.post('/api/product-settings/catalog/preview',json=dict(content=json.dumps(doc),expected_catalog_digest=None,expected_policy_digest=load_policy(active).digest))
    assert response.status_code==422 and '账号' in response.json()['detail']

"""五类选品、上下文传递与控制台 API 的隔离验收。"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from video_processing.core.wechat_product_policy import parse_product_policy
from video_processing.utils.wechat_product_config import load_policy, save_policy, PolicyConflict
from video_processing.utils.wechat_product_context import video_product_context, product_context_arguments
from web.product_settings import create_product_settings_router

SEED = Path(__file__).resolve().parents[2]/'config/wechat_products.json'
WALL = 'UCTK_cv-y88CScoudcXnS1Ew'
TED = 'UCAuUUnT6oDeKwE6v1NGQxug'

@pytest.fixture
def data():
    return json.loads(SEED.read_text())

@pytest.mark.parametrize('context,group,alias', [
    ({'content_type':'ENGLISH_WORLD_SHORT','source_channel_id':WALL,'product_topic':'AI'},'english_world','default'),
    ({'source_channel_id':WALL,'product_topic':'AI'},'wallstreet','finance'),
    ({'source_channel_id':TED,'product_topic':'AI'},'ted','default'),
    ({'product_topic':'AI'},'ai_news','news'),
    ({'category':'科技'},'other','default'),
    ({'category':'财经'},'other','finance'),
    ({'category':'资讯'},'other','news'),
    ({},'other','default'),
])
def test_group_priority(data, context, group, alias):
    p=parse_product_policy(data); d=p.decide(**context)
    assert d.video_group==group and d.candidates[0]==p.products[alias].identity
    manual=p.decide(**context,product_alias='news')
    assert manual.video_group==group and manual.reason=='MANUAL'
    assert manual.candidates[0]==p.products['news'].identity


def test_configured_channels_and_fallback(data):
    data['profiles']['ai_news']['channel_ids']=[WALL,TED,'ai-channel']
    data['profiles']['ted']['channel_ids'].append(WALL)
    data['profiles']['english_world']['candidates']=['finance','news']
    p=parse_product_policy(data)
    assert p.decide(source_channel_id=WALL).video_group=='wallstreet'
    assert p.decide(source_channel_id=TED).video_group=='ted'
    assert p.decide(source_channel_id='ai-channel').video_group=='ai_news'
    d=p.decide(content_type='ENGLISH_WORLD_SHORT')
    assert [x.product_id for x in d.candidates]==[p.products[k].identity.product_id for k in ('finance','news','default')]
    data['max_attempts']=2
    with pytest.raises(ValueError,match='不可达'): parse_product_policy(data)


def test_context_and_arguments_share_sidecars(tmp_path):
    (tmp_path/'abc.info.json').write_text(json.dumps({'channel_id':TED,'product_topic':'AI'}))
    (tmp_path/'abc_s2_category.txt').write_text('财经')
    context=video_product_context(tmp_path,{'youtube_id':'abc','slice_index':2,'category':'新闻'})
    assert context=={'category':'财经','source_channel_id':TED,'product_topic':'AI','content_type':'GENERAL'}
    args=product_context_arguments(context)
    assert args[args.index('--product-category')+1]=='财经'
    assert args[args.index('--product-topic')+1]=='AI'
    assert video_product_context(tmp_path,{'content_type':'ENGLISH_WORLD_SHORT'})['content_type']=='ENGLISH_WORLD_SHORT'
    with pytest.raises(ValueError): video_product_context(tmp_path,{'youtube_id':'../../etc'})


@pytest.fixture
def api_setup(tmp_path, data):
    active=tmp_path/'policy.json';active.write_text(json.dumps(data))
    status=tmp_path/'runtime.json'; output=tmp_path/'output';output.mkdir()
    records=[{'preview_key':'video:1','youtube_id':'wall','channel_id':WALL,'title':'财经测试','slice_index':0,'category':'新闻','content_type':'GENERAL','state':'PENDING'},
             {'preview_key':'english:1','content_type':'ENGLISH_WORLD_SHORT','title':'英语世界测试','state':'READY_FOR_REVIEW'}]
    app=FastAPI();app.include_router(create_product_settings_router(active=active,status=status,output=output,videos=lambda:records))
    from fastapi.staticfiles import StaticFiles
    app.mount('/static',StaticFiles(directory=SEED.parent.parent/'src/web/static'))
    with TestClient(app) as client: yield client,active,status,records


def test_save_preview_conflict_and_snapshot(api_setup):
    client,active,status,_=api_setup
    old=load_policy(active); initial=client.get('/api/product-settings').json()
    draft=deepcopy(initial['config']);draft['profiles']['english_world']['candidates']=['finance']
    preview=client.post('/api/product-settings/preview',json={'config':draft,'video_key':'english:1'}).json()
    assert preview['video_group']=='english_world' and preview['candidates'][0]['product_id']==old.products['finance'].identity.product_id
    assert not status.exists() and load_policy(active).digest==old.digest
    saved=client.put('/api/product-settings',json={'config':draft,'expected_digest':old.digest})
    assert saved.status_code==200
    assert not saved.json()['status']['adopted_by_last_selection']
    assert old.decide(content_type='ENGLISH_WORLD_SHORT').candidates[0]==old.products['default'].identity
    assert load_policy(active).decide(content_type='ENGLISH_WORLD_SHORT').candidates[0]==old.products['finance'].identity
    assert client.put('/api/product-settings',json={'config':draft,'expected_digest':old.digest}).status_code==409
    with pytest.raises(PolicyConflict): save_policy(initial['config'],active,expected_digest=old.digest)
    assert client.post('/api/product-settings/preview',json={'config':draft,'video_key':'gone'}).status_code==404


def test_invalid_save_and_cross_origin_preserve_config(api_setup):
    client,active,status,_=api_setup
    old=load_policy(active);draft=json.loads(old.serialized);draft['default_candidates']=['missing']
    assert client.put('/api/product-settings',json={'config':draft,'expected_digest':old.digest}).status_code==422
    assert load_policy(active).digest==old.digest
    assert client.put('/api/product-settings',json={'config':json.loads(old.serialized),'expected_digest':old.digest},headers={'Origin':'https://evil.invalid'}).status_code==403
    status.write_text('invalid receipt')
    state=client.get('/api/product-settings').json()['status']
    assert state['runtime_error'] and not state['adopted_by_last_selection']


def test_dal_preview_list_is_bounded_and_read_only(tmp_path):
    from video_processing.db.database import PipelineDB
    db=PipelineDB(tmp_path/'preview.db')
    db.add_video('one','第一条',WALL,category='财经')
    db.add_video('two','第二条',TED)
    rows=db.get_product_preview_videos(limit=1)
    assert len(rows)==1 and rows[0]['preview_key'].startswith('video:')
    assert rows[0]['state']=='PENDING'


def test_concurrent_editors_only_one_can_save(api_setup):
    from concurrent.futures import ThreadPoolExecutor
    _,active,_,_=api_setup
    old=load_policy(active)
    def edit(version):
        candidate=json.loads(old.serialized);candidate['version']=version
        try:
            save_policy(candidate,active,expected_digest=old.digest)
            return 'saved'
        except PolicyConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit,['editor-one','editor-two']))==['conflict','saved']


def test_disk_failure_retains_file_and_is_not_reported_as_saved(api_setup,monkeypatch):
    from video_processing.utils import wechat_product_config
    client,active,status,_=api_setup
    old=load_policy(active)
    def fail_write(*args,**kwargs): raise OSError('fixture disk failure')
    monkeypatch.setattr(wechat_product_config,'atomic_json',fail_write)
    response=client.put('/api/product-settings',json={'config':json.loads(old.serialized),'expected_digest':old.digest})
    assert response.status_code==503 and load_policy(active).digest==old.digest
    assert not status.exists()


def test_malformed_runtime_shape_remains_unknown(api_setup):
    client,_,status,_=api_setup
    status.write_text('42')
    state=client.get('/api/product-settings').json()['status']
    assert state['runtime_error'] and not state['adopted_by_last_selection']


def test_removed_profile_channel_has_no_hidden_legacy_rule(data):
    data['profiles']['wallstreet']['channel_ids']=[]
    policy=parse_product_policy(data)
    decision=policy.decide(source_channel_id=WALL)
    assert decision.video_group=='other' and decision.reason=='DEFAULT'
    assert decision.candidates[0]==policy.products['default'].identity


def test_unconnected_publisher_never_claims_current_config_adopted(api_setup):
    client, active, status, records = api_setup
    policy = load_policy(active)
    status.write_text(json.dumps({'config_digest': policy.digest, 'config_version': policy.version}))
    response = client.get('/api/product-settings').json()['status']
    assert response['publisher_connected'] is False
    assert response['adopted_by_last_selection'] is False

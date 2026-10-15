"""片尾配置、独立复核与真实路由的隔离回归；不调用任何发布入口。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from video_processing.utils import vocabulary_outro_policy as policy
from video_processing.utils import vocabulary_recovery as recovery
from video_processing.processors import vocabulary_outro as vo
from tests.unit.test_vocabulary_outro import subtitle
from web.vocabulary_outro_settings import create_vocabulary_outro_settings_router


@pytest.fixture
def config():
    return json.loads((Path(__file__).resolve().parents[2]/'config/vocabulary_outro.json').read_text())


@pytest.fixture
def api_setup(tmp_path, config):
    active=tmp_path/'policy.json';active.write_text(json.dumps(config))
    output=tmp_path/'output';output.mkdir()
    videos=[dict(preview_key='video:1',youtube_id='sample',slice_index=0,title='示例任务',
                 channel_id=config['profiles']['wallstreet']['channel_ids'][0])]
    app=FastAPI()
    app.include_router(create_vocabulary_outro_settings_router(active=active,output=output,videos=lambda:videos))
    app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[2]/'src/web/static'))
    with TestClient(app) as client:
        yield client,active,output,videos


def test_classification_and_independent_switches(config):
    channel=config['profiles']['wallstreet']['channel_ids'][0]
    config['profiles']['wallstreet']['enabled']=False
    assert policy.decide(config,dict(source_channel_id=channel))['enabled'] is False
    assert policy.decide(config,dict(source_channel_id=channel,content_type='ENGLISH_WORLD_SHORT'))['group']=='english_world'
    assert policy.decide(config,dict(product_topic='AI'))['group']=='ai_news'
    assert policy.decide(config,dict(category='科技'))['group']=='other'
    assert policy.decide(config,{})['enabled'] is True
    config['enabled']=False
    assert not any(policy.decide(config,dict(content_type=kind))['enabled'] for kind in ('GENERAL','ENGLISH_WORLD_SHORT'))


@pytest.mark.parametrize('mutation', ['boolean','missing','extra','duplicate','invalid_channel'])
def test_strict_validation(config,mutation):
    if mutation=='boolean':config['enabled']='false'
    if mutation=='missing':del config['profiles']['ted']
    if mutation=='extra':config['unknown']=True
    if mutation=='duplicate':config['profiles']['ai_news']['channel_ids']=config['profiles']['wallstreet']['channel_ids']
    if mutation=='invalid_channel':config['profiles']['ted']['channel_ids']=['https://youtube.com/@TED']
    with pytest.raises(ValueError):policy.parse_policy(config)


def test_freeze_persistence_and_conflict(api_setup, config):
    client,active,output,_=api_setup
    first=policy.freeze(output,'one',active,{})
    current=client.get('/api/vocabulary-outro-settings').json()
    config['enabled']=False
    body=dict(config=config,expected_digest=current['digest'])
    assert client.put('/api/vocabulary-outro-settings',json=body).status_code==200
    assert client.put('/api/vocabulary-outro-settings',json=body).status_code==409
    assert policy.freeze(output,'one',active,{})==first
    assert policy.freeze(output,'two',active,{})['status']=='DISABLED'
    assert policy.load_policy(active)['enabled'] is False
    assert not list(output.glob('*.mp4'))


def test_preview_and_records_are_read_only_and_draft_based(api_setup, config):
    client,active,output,_=api_setup
    policy.freeze(output,'sample',active,dict(source_channel_id=config['profiles']['wallstreet']['channel_ids'][0]))
    original=active.read_bytes()
    config['profiles']['wallstreet']['enabled']=False
    value=client.post('/api/vocabulary-outro-settings/preview',json=dict(config=config,video_key='video:1')).json()
    assert value['decision']['enabled'] is False and value['frozen']['enabled'] is True
    assert active.read_bytes()==original
    assert len(client.get('/api/vocabulary-outro-settings/records').json()['records'])==1
    (output/'bad.outro-policy.json').write_text('{}')
    assert client.get('/api/vocabulary-outro-settings/records').json()['unreadable']==1
    body=dict(config=config,expected_digest=policy.digest(config))
    assert client.put('/api/vocabulary-outro-settings',json=body,headers={'origin':'https://evil.invalid'}).status_code==403
    assert client.post('/api/vocabulary-outro-settings/preview',json=dict(config=config,video_key='../bad')).status_code==404


def test_recovery_binds_same_segment_and_chinese_text(tmp_path):
    ass=subtitle(tmp_path/'one.ass',('cosmic',))
    rows=recovery.subtitle_rows(ass,2)
    raw=dict(status='FOUND',reason='原字幕术语',items=[dict(id=0,word='cosmic',meaning_zh='宇宙')])
    assert recovery.validate_recovery(raw,rows)['items'][0]['excerpt']=='This is cosmic sound'
    for bad in (dict(id=1,word='cosmic',meaning_zh='宇宙'),dict(id=0,word='sound',meaning_zh='宏观'),dict(id=0,word='cos',meaning_zh='宇宙')):
        with pytest.raises(recovery.CodexTextError):recovery.validate_recovery(dict(raw,items=[bad]),rows)
    with pytest.raises(recovery.CodexTextError):recovery.validate_recovery(dict(raw,items=[]),rows)


def test_empty_recovery_is_explicit_and_bound_to_current_media(tmp_path,monkeypatch):
    source=tmp_path/'a.mp4';source.write_bytes(b'base');ass=subtitle(tmp_path/'a.ass',())
    output=tmp_path/'a_vocab.mp4'
    monkeypatch.setattr(vo,'probe',lambda _:dict(format=dict(duration='2')))
    monkeypatch.setattr(recovery,'recover_items',lambda *args:[])
    assert vo.build(source,ass,output,'title',recover_empty=True)==source
    assert vo.valid_empty_receipt(source,ass,output)
    source.write_bytes(b'changed')
    assert not vo.valid_empty_receipt(source,ass,output)


def test_recovery_failure_blocks_pipeline_and_disabled_task_ignores_cache(api_setup,monkeypatch):
    from config.settings import settings
    from video_processing.pipeline_manager import PipelineManager
    client,active,output,_=api_setup
    manager=PipelineManager.__new__(PipelineManager);manager._OUT_DIR=output
    source=output/'a_vertical.mp4';source.write_bytes(b'base');ass=subtitle(output/'a.ass')
    monkeypatch.setattr(settings,'vocabulary_outro_policy_path',active)
    monkeypatch.setattr(manager,'_get_base_video_path',lambda *args:source)
    def failed(*args,**kwargs):raise recovery.CodexTextError('quota')
    monkeypatch.setattr(manager,'_run_tracked',failed)
    with pytest.raises(recovery.CodexTextError):manager._process_vocabulary_outro('a','a','title')
    assert policy.read_record(output,'a')['status']=='FAILED'
    derived=output/'a_vocab.mp4';derived.write_bytes(b'old')
    vo.receipt_path(derived).write_text(json.dumps(dict(inputs=vo.fingerprint(source,ass,'title'),status='rendered',output_sha256=vo.sha256(derived))))
    with pytest.raises(RuntimeError):manager._get_published_video_path('a')
    record=policy.read_record(output,'a');record['enabled']=False;record['status']='DISABLED'
    policy.atomic_json(policy.record_path(output,'a'),record)
    assert manager._get_published_video_path('a')==source


def test_recovery_uses_bounded_existing_provider(tmp_path,monkeypatch):
    ass=subtitle(tmp_path/'a.ass')
    calls=[]
    def provider(prompt,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(payload=kwargs['validate'](dict(status='FOUND',reason='术语',items=[dict(id=0,word='cosmic',meaning_zh='宇宙')])))
    monkeypatch.setattr(recovery,'run_codex_structured',provider)
    assert recovery.recover_items(ass,2)[0]['meaning_zh']=='宇宙'
    assert calls[0]['timeout_sec']<=120

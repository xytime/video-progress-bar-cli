"""华尔街独立 B 在真实 DAL 中消费商品意图、可选挂接与停止重传契约。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-11 | Codex | 验证缺商品或停用后清空放行，并保留同次原生 ID 与禁止重传。 |
"""
import importlib.util
import json
from pathlib import Path
import pytest
from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.db.wallstreet_experiment import CHANNEL_ID
from video_processing.core.wechat_product_policy import ProductLookup
from video_processing.utils.wechat_product_task import read_product_task_decision, freeze_task_product_decision
from video_processing.utils.wechat_product_execution import execute_product_task, product_artifacts_digest, product_observation_generation


@pytest.fixture
def setup(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('wallstreet_product_contract',Path('scripts/run_wallstreet_ab.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    active=tmp_path/'wechat_products.json'
    active.write_text((Path(__file__).parents[1]/'fixtures/wechat_products_v2.json').read_text())
    active.with_name('wechat_product_catalog.json').write_text(json.dumps(dict(
        schema_version=2,captured_at='2026-10-11T00:00:00+08:00',source='测试账号可靠后台导出',
        account_id='test-publisher',total_pages=1,total_items=1,
        pages=[dict(page=1,items=[dict(product_id='700007',title='完整指定商品',shop='测试',price='20',stock=12)])])))
    monkeypatch.setattr(type(settings),'default_output_dir',property(lambda _:tmp_path))
    monkeypatch.setattr(settings,'wechat_product_policy_path',active)
    monkeypatch.setattr(settings,'wechat_publishing_paused',False)
    monkeypatch.setattr(settings,'enable_douyin_browser_publishing',False)
    monkeypatch.setattr(type(settings),'is_public_publish_window',lambda _:True)
    # 素材门禁另有实际回归；这里只替代媒体/内容依赖，不替代领取、决策或等待。
    monkeypatch.setattr(module,'validate_package',lambda _:None)
    return module,PipelineDB(str(tmp_path/'db.sqlite')),active


def ready(module,db,tmp_path,*,yid='abcdefghijk',likes=1000,intent='AUTO',slice_index=2,accounts=None):
    identity=dict(product_id='700007',product_title='完整指定商品') if intent=='PRODUCT' else {}
    assert db.add_video(yid,'B源',CHANNEL_ID,score=80,view_count=10000,like_count=likes,
        product_intent=intent,slice_index=slice_index,**identity)
    pair=db.enroll_wallstreet_video(yid,slice_index=slice_index,b_only=True,accounts=accounts or {'wechat':'default'})
    job=db.claim_wallstreet_render()
    folder=tmp_path/yid;folder.mkdir()
    package={}
    for key in ('video','copy','title','cover','horizontal_cover','cover_provenance','category'):
        path=folder/(key+'.txt');path.write_text(key+' actual bytes');package[key]=str(path)
    package['payload_sha256']=module.payload_hash(package)
    assert db.finish_wallstreet_render(pair['id'],job['lease_token'],package=package)
    # A 的普通记录已发布；独立 B 仍合法可提交，不能把这个状态传给 B 决策。
    db.update_video_status(yid,'PUBLISHED',slice_index=slice_index)
    pub=next(p for p in db.get_wallstreet_publications() if p['pair_id']==pair['id'] and p['platform']=='wechat')
    return pub,package


def accepted_receipt(decision):
    product=decision['product_decision']['candidates'][0] if decision['require_product'] else None
    return dict(platform_post_id='native-B-'+decision['task_id'].split(':')[-1],
        product_task_id=decision['task_id'],product_config_digest=decision['config_digest'],
        product_config_version=decision['config_version'],product_attachment_reason=decision['reason'],
        product_binding_confirmed=bool(product),product_unbound_confirmed=not bool(product),
        product_id=product['product_id'] if product else None,product_title=product['title'] if product else None)


@pytest.mark.parametrize('likes,intent,required,reason',[
    (999,'AUTO',False,'SKIP_BELOW_THRESHOLD'),(1000,'AUTO',True,'ATTACH_THRESHOLD'),
    (None,'AUTO',False,'SKIP_METRICS_UNKNOWN'),(9000,'NONE',False,'SKIP_MANUAL_NONE'),
    (1,'PRODUCT',True,'ATTACH_MANUAL')])
def test_real_b_command_consumes_source_slice_and_explicit_intent(setup,tmp_path,monkeypatch,likes,intent,required,reason):
    module,db,active=setup
    pub,package=ready(module,db,tmp_path,likes=likes,intent=intent)
    calls=[]
    def uploader(args,evidence):
        calls.append(args)
        assert '--require-product' not in args and '--product-task-decision' in args
        decision=read_product_task_decision(Path(args[args.index('--product-task-decision')+1]))
        assert decision['task_id']==f"wallstreet:wechat:B:{pub['id']}"
        assert decision['context']['status']=='WAITING' and decision['context']['slice_index']==2
        assert decision['metrics']['view_count']==10000 and decision['metrics']['like_count']==likes
        assert decision['require_product'] is required and decision['reason']==reason
        assert decision['context']['source_channel_id']==CHANNEL_ID
        if intent=='PRODUCT':
            assert decision['product_decision']['candidates']==[dict(product_id='700007',title='完整指定商品')]
        assert (evidence/'attempt_claim.json').exists()
        module.write_json(evidence/'submission_receipt.json',accepted_receipt(decision))
        return 6
    monkeypatch.setattr(module,'run_command',uploader)
    module.submit_ready(db)
    row=next(p for p in db.get_wallstreet_publications() if p['id']==pub['id'])
    assert len(calls)==1 and row['state']=='UNDER_REVIEW' and row['attempt_count']==1
    assert db.get_video_by_youtube_id(pub['youtube_id'],slice_index=2)['status']=='PUBLISHED'
    module.submit_ready(db)
    assert len(calls)==1


class UnavailablePicker:
    def read_binding(self,**kwargs):return None
    def find(self,*args,**kwargs):return ProductLookup.UNAVAILABLE
    def cancel_and_clear(self,**kwargs):return True
    def ready_to_submit(self,**kwargs):return True


def test_product_unavailable_submits_b_without_product_and_never_reuploads(setup,tmp_path,monkeypatch):
    module,db,active=setup
    first,package=ready(module,db,tmp_path,intent='PRODUCT')
    second,_=ready(module,db,tmp_path,yid='other______',intent='NONE',likes=9000)
    calls=[]
    def uploader(args,evidence):
        from scripts.wechat_uploader import _write_submission_receipt
        decision=read_product_task_decision(Path(args[args.index('--product-task-decision')+1]));calls.append(decision)
        assert execute_product_task(decision,UnavailablePicker(),evidence,tmp_path/'product-status.json',
            wait_output=tmp_path,artifacts_digest=product_artifacts_digest(Path(package['video']),Path(package['copy']),Path(package['cover'])))
        _write_submission_receipt(evidence,accepted_receipt(decision))
        actual=json.loads((evidence/'submission_receipt.json').read_text())
        assert actual['product_unbound_confirmed'] and not actual['product_id']
        return 6
    monkeypatch.setattr(module,'run_command',uploader)
    module.submit_ready(db)
    rows={p['id']:p for p in db.get_wallstreet_publications()}
    assert rows[first['id']]['state']=='UNDER_REVIEW' and rows[first['id']]['attempt_count']==1
    assert rows[first['id']]['attempt_token']  # 受理身份仍关联同次已领取的提交尝试。
    assert rows[second['id']]['state']=='UNDER_REVIEW' and len(calls)==2
    original=rows[first['id']]
    module.submit_ready(db)
    assert len(calls)==2 and db.get_wallstreet_publications()[0]==original
    assert not (tmp_path/'wechat_product_waits.json').exists()
    assert len(list((Path(package['video']).parent/'submissions'/f"wechat-{first['id']}").glob('attempt-*/attempt_claim.json')))==1


@pytest.mark.parametrize('fault',[
    'accepted','management','uncertain','native','attempt','package','asset','artifacts',
    'config','task','unknown_submission','bound','unbound','not_required','wrong_exit','evidence'])
def test_dal_never_restores_missing_or_conflicting_submission_proof(setup,tmp_path,fault):
    module,db,active=setup
    pub,package=ready(module,db,tmp_path,intent='PRODUCT')
    task=f"wallstreet:wechat:B:{pub['id']}"
    decision=freeze_task_product_decision(db,task,dict(youtube_id=pub['youtube_id'],product_intent='PRODUCT',
        product_id='700007',product_title='完整指定商品'),active)
    evidence=tmp_path/'attempt';evidence.mkdir()
    package_hash=module.payload_hash(package);asset_hash=module.sha256(Path(package['video']))
    digest=product_artifacts_digest(Path(package['video']),Path(package['copy']),Path(package['cover']))
    claim=db.claim_wallstreet_submission(pub['id'],package_sha256=package_hash,asset_sha256=asset_hash,
        video_path=package['video'],evidence_path=str(evidence))
    receipt=dict(required=True,binding_confirmed=False,unbound_confirmed=False,state='BLOCKED',task_id=task,config_digest=decision['config_digest'])
    wait=dict(task_key=task,not_submitted=True,submission_state='NOT_SUBMITTED',artifacts_digest=digest,
        config_digest=decision['config_digest'],reason='PRODUCT_UNAVAILABLE')
    kwargs=dict(attempt_token=claim['attempt_token'],uploader_exit_code=14,evidence_dir=str(evidence),
        receipt=receipt,wait_evidence=wait,package_sha256=package_hash,asset_sha256=asset_hash,artifacts_digest=digest)
    if fault=='accepted':(evidence/'submission_receipt.json').write_text('{}')
    if fault=='management':(evidence/'management_readback.json').write_text('{}')
    if fault in {'uncertain','native'}:
        db.observe_wallstreet_publication(pub['id'],state='UNCERTAIN' if fault=='uncertain' else 'UNDER_REVIEW',
            platform_post_id='accepted-B' if fault=='native' else None,evidence_path=str(evidence),attempt_token=claim['attempt_token'])
    if fault=='attempt':kwargs['attempt_token']='stale'
    if fault=='package':kwargs['package_sha256']='a'*64
    if fault=='asset':kwargs['asset_sha256']='a'*64
    if fault=='artifacts':kwargs['artifacts_digest']='a'*64
    if fault=='config':receipt['config_digest']='a'*64
    if fault=='task':receipt['task_id']='pipeline:other:0'
    if fault=='unknown_submission':wait['submission_state']='UNCERTAIN'
    if fault=='bound':receipt['binding_confirmed']=True
    if fault=='unbound':receipt['unbound_confirmed']=True
    if fault=='not_required':receipt['required']=False
    if fault=='wrong_exit':kwargs['uploader_exit_code']=1
    if fault=='evidence':kwargs['evidence_dir']=str(tmp_path/'other-attempt')
    before=db.get_wallstreet_publications()[0]
    assert not db.defer_wallstreet_wechat_product_wait(pub['id'],**kwargs)
    assert db.get_wallstreet_publications()[0]==before


def test_accepted_missing_product_identity_is_uncertain_and_never_reuploaded(setup,tmp_path,monkeypatch):
    module,db,active=setup
    pub,package=ready(module,db,tmp_path,intent='PRODUCT')
    calls=[]
    def uploader(args,evidence):
        calls.append(args);module.write_json(evidence/'submission_receipt.json',{'platform_post_id':'native-B'})
        return 14
    monkeypatch.setattr(module,'run_command',uploader)
    module.submit_ready(db)
    row=db.get_wallstreet_publications()[0]
    assert row['state']=='UNCERTAIN' and row['platform_post_id']=='native-B'
    module.submit_ready(db)
    assert len(calls)==1 and row==db.get_wallstreet_publications()[0]


def test_fourteen_without_not_submitted_proof_stops_retransmission(setup,tmp_path,monkeypatch):
    module,db,active=setup
    ready(module,db,tmp_path,intent='PRODUCT')
    calls=[]
    monkeypatch.setattr(module,'run_command',lambda args,evidence:calls.append(args) or 14)
    module.submit_ready(db)
    assert db.get_wallstreet_publications()[0]['state']=='UNCERTAIN'
    module.submit_ready(db)
    assert len(calls)==1


def test_disabled_manual_product_is_cleared_and_b_continues(setup,tmp_path,monkeypatch):
    module,db,active=setup
    first,_=ready(module,db,tmp_path,intent='PRODUCT')
    second,_=ready(module,db,tmp_path,yid='other______',intent='NONE')
    # 目录导入生成的完整商品身份仍保留；运营停用在可靠 library 中显式维护。
    from video_processing.core.wechat_product_library import FIELDS
    config=json.loads(active.read_text())
    record=dict.fromkeys(FIELDS,'')
    record.update(product_id='700007',title='完整指定商品',shop='测试',
        enabled=False,identity_status='VERIFIED',account_id='test-publisher',verified_at='2026-10-11T00:00:00+08:00',
        verified_source='测试发布账号后台导出')
    config['library']={'product_700007':record}
    config['products']['product_700007']={key:record[key] for key in ('product_id','title','enabled','verified_at','verified_source')}
    active.write_text(json.dumps(config))
    calls=[]
    def uploader(args,evidence):
        from scripts.wechat_uploader import _write_submission_receipt
        decision=read_product_task_decision(Path(args[args.index('--product-task-decision')+1]));calls.append(decision)
        assert execute_product_task(decision,UnavailablePicker(),evidence,tmp_path/'product-status.json')
        _write_submission_receipt(evidence,accepted_receipt(decision))
        return 6
    monkeypatch.setattr(module,'run_command',uploader)
    module.submit_ready(db)
    rows={p['id']:p for p in db.get_wallstreet_publications()}
    assert rows[first['id']]['state']=='UNDER_REVIEW' and rows[first['id']]['attempt_count']==1
    assert rows[second['id']]['state']=='UNDER_REVIEW' and len(calls)==2
    frozen=db.get_product_task_decision(f"wallstreet:wechat:B:{first['id']}")
    assert frozen['selection_block_reason']=='MANUAL_PRODUCT_DISABLED'
    assert not (tmp_path/'wechat_product_waits.json').exists()


def test_verify_and_douyin_commands_keep_existing_contract(setup,tmp_path):
    module,db,active=setup
    pub,package=ready(module,db,tmp_path,accounts={'wechat':'default','douyin':'default'})
    args=module.command(pub,package,tmp_path/'verify',verify=True)
    assert '--verify-only' in args and '--video' not in args and '--product-task-decision' not in args
    with pytest.raises(ValueError,match='冻结'):
        module.command(pub,package,tmp_path/'unsafe')
    douyin=next(p for p in db.get_wallstreet_publications() if p['platform']=='douyin')
    claim=db.claim_wallstreet_submission(douyin['id'],package_sha256=module.payload_hash(package),
        asset_sha256=module.sha256(Path(package['video'])),video_path=package['video'],evidence_path=str(tmp_path/'douyin'))
    args=module.command(douyin,package,tmp_path/'douyin',ticket=claim)
    assert '--douyin-launch-ticket' in args and '--publish' in args and '--product-task-decision' not in args

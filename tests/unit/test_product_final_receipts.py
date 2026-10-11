"""最终表单回执与异常队列公平性的隔离回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-12 | Codex | 双 ID 挂载核验；旧回执补充凭据必须精确绑定哈希、作品 nonce 与原生商品记录。 |
| 1.1.0 | 2026-10-12 | Codex | 覆盖实际选中行与未变化表单证据的同作品商品精确核对。 |
"""
import json
from pathlib import Path
import pytest
from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.core.wechat_product_policy import ProductIdentity, ProductLookup
from video_processing.utils.wechat_product_task import freeze_task_product_decision
from video_processing.utils.wechat_product_execution import execute_product_task, finalize_product_before_submit, blocked_product_task_keys
from video_processing.utils.wechat_product_waits import ProductWaitStore


def policy_fixture(tmp_path):
    active=tmp_path/'wechat_products.json'
    active.write_text((Path(__file__).parents[1]/'fixtures/wechat_products_v2.json').read_text())
    catalog=dict(schema_version=2,captured_at='2026-10-11T00:00:00+08:00',source='isolated fixture',
        account_id='publisher-fixture',total_pages=1,total_items=1,
        pages=[dict(page=1,items=[dict(product_id='700007',title='完整指定商品',shop='测试',price='20',stock=12)])])
    active.with_name('wechat_product_catalog.json').write_text(json.dumps(catalog))
    return active


class Picker:
    def __init__(self, available=True, clear=True):
        self.binding=None;self.available=available;self.clear=clear
    def read_binding(self, **kwargs): return self.binding
    def ready_to_submit(self, **kwargs): return True
    def find(self, *args, **kwargs): return ProductLookup.AVAILABLE if self.available else ProductLookup.UNAVAILABLE
    def select(self, product, **kwargs): self.binding=product
    def cancel_and_clear(self, **kwargs):
        if self.clear: self.binding=None
        return self.clear


@pytest.mark.parametrize('initially_bound', [True,False])
def test_final_binding_transition_cannot_leave_stale_accepted_product_receipt(tmp_path, initially_bound):
    from scripts.wechat_uploader import _write_submission_receipt
    from scripts.run_wallstreet_ab import product_submission_matches
    from scripts.submit_english_world_review import _product_receipt_is_confirmed
    active=policy_fixture(tmp_path)
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    task=freeze_task_product_decision(db,'review:transition',dict(product_intent='PRODUCT',
        product_id='700007',product_title='完整指定商品'),active)
    picker=Picker(available=initially_bound)
    evidence=tmp_path/'evidence'
    assert execute_product_task(task,picker,evidence,tmp_path/'status.json')
    picker.binding=None if initially_bound else ProductIdentity('700007','完整指定商品')
    assert not finalize_product_before_submit(task,picker,evidence)
    assert not (evidence/'product_pre_submit_readback.json').exists()
    assert not (evidence/'submission_receipt.json').exists()


def test_uncleared_high_priority_task_does_not_starve_ready_following_video(tmp_path,monkeypatch):
    from scripts import run_ready_publications as worker
    active=policy_fixture(tmp_path);out=tmp_path/'output';out.mkdir()
    db=PipelineDB(str(out/'db.sqlite'))
    task=freeze_task_product_decision(db,'pipeline:bad-form-01:0',dict(product_intent='PRODUCT',
        product_id='700007',product_title='完整指定商品'),active)
    for yid,score,intent in [('bad-form-01',100,'PRODUCT'),('ready-none2',80,'NONE')]:
        identity=dict(product_id='700007',product_title='完整指定商品') if intent=='PRODUCT' else {}
        db.add_video(yid,yid,'channel',score=score,product_intent=intent,**identity)
        db.mark_video_ready_for_publication(yid)
    calls=[]
    class Manager:
        def __init__(self): self.db=db
        def _process_single_video(self,row,**kwargs):
            calls.append(row['youtube_id'])
            if row['youtube_id']=='bad-form-01':
                allowed=execute_product_task(task,Picker(available=False,clear=False),
                    tmp_path/f'attempt-{len(calls)}',tmp_path/'status.json',
                    wait_output=out,artifacts_digest='unchanged-media')
                assert not allowed
                db.defer_ready_publication(row['youtube_id'],'商品清理失败，未点击发表')
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    monkeypatch.setattr(settings,'wechat_product_policy_path',active)
    monkeypatch.setattr(settings,'wechat_publishing_paused',False)
    manager=Manager()
    assert worker.dispatch_once(manager)==1
    wait=ProductWaitStore(out/'wechat_product_waits.json').records()[0]
    assert wait['state']=='BLOCKED' and wait['reason']=='CANNOT_CONFIRM_CLEARED'
    assert worker.dispatch_once(manager)==1
    assert calls==['bad-form-01','ready-none2'], dict(calls=calls,blocked=blocked_product_task_keys(out,active),wait=wait)


@pytest.mark.parametrize('intent,available', [('PRODUCT', True), ('PRODUCT', False), ('NONE', False)])
def test_stable_final_form_is_only_source_of_submission_product_receipt(tmp_path, intent, available):
    from scripts.wechat_uploader import _write_submission_receipt
    from scripts.run_wallstreet_ab import product_submission_matches
    from scripts.submit_english_world_review import _product_receipt_is_confirmed
    active=policy_fixture(tmp_path);db=PipelineDB(str(tmp_path/'db.sqlite'))
    context=dict(product_intent=intent, product_id='700007', product_title='完整指定商品') if intent=='PRODUCT' else dict(product_intent='NONE')
    task=freeze_task_product_decision(db,'task:stable',context,active)
    picker=Picker(available=available);evidence=tmp_path/'evidence'
    assert execute_product_task(task,picker,evidence,tmp_path/'status')
    assert finalize_product_before_submit(task,picker,evidence)
    # 后续选品文件被改写，也不能覆盖提交前实际回读。
    (evidence/'product_selection_receipt.json').write_text('{}')
    _write_submission_receipt(evidence,dict(platform_post_id='native-id'))
    receipt=json.loads((evidence/'submission_receipt.json').read_text())
    assert receipt['product_identity_source']=='FINAL_FORM_READBACK'
    actual=(picker.binding.product_id,picker.binding.title) if picker.binding else (None,None)
    assert (receipt['product_id'],receipt['product_title'])==actual
    assert receipt['product_unbound_confirmed'] is (picker.binding is None)
    assert product_submission_matches(receipt,task)
    # English validator reads the selection receipt; restore the original final snapshot.
    (evidence/'product_selection_receipt.json').write_text((evidence/'product_pre_submit_readback.json').read_text())
    assert _product_receipt_is_confirmed(evidence,task)


@pytest.mark.parametrize('mutation', ['missing','task_id','config_digest','config_version','required','wrong_id','wrong_title','unstable','not_ready','unknown'])
def test_invalid_final_evidence_stops_submission(tmp_path,mutation):
    active=policy_fixture(tmp_path);db=PipelineDB(str(tmp_path/'db.sqlite'))
    task=freeze_task_product_decision(db,'task:invalid',dict(product_intent='PRODUCT',product_id='700007',product_title='完整指定商品'),active)
    picker=Picker();evidence=tmp_path/'evidence'
    assert execute_product_task(task,picker,evidence,tmp_path/'status')
    path=evidence/'product_selection_receipt.json'
    receipt=json.loads(path.read_text())
    if mutation=='missing':path.unlink()
    elif mutation in {'task_id','config_digest','config_version','required'}:
        receipt[mutation]='stale';path.write_text(json.dumps(receipt))
    elif mutation=='wrong_id':picker.binding=ProductIdentity('wrong','完整指定商品')
    elif mutation=='wrong_title':picker.binding=ProductIdentity('700007','错误版本')
    elif mutation=='not_ready':picker.ready_to_submit=lambda **kw:False
    elif mutation=='unstable':
        reads=iter([picker.binding,None]);picker.read_binding=lambda **kw:next(reads)
    elif mutation=='unknown':
        def unknown(**kw):raise ValueError('identity unavailable')
        picker.read_binding=unknown
    # 删除旧证据，避免复用上次成功。
    (evidence/'product_pre_submit_readback.json').write_text('{"final_verified":true}')
    assert not finalize_product_before_submit(task,picker,evidence)
    assert not (evidence/'product_pre_submit_readback.json').exists()


def test_unverified_selection_never_claims_product_in_native_receipt(tmp_path):
    from scripts.wechat_uploader import _write_submission_receipt
    evidence=tmp_path/'e';evidence.mkdir()
    (evidence/'product_selection_receipt.json').write_text(json.dumps(dict(binding_confirmed=True,actual_product_id='wrong')))
    _write_submission_receipt(evidence,dict(platform_post_id='accepted-native-id'))
    receipt=json.loads((evidence/'submission_receipt.json').read_text())
    assert receipt['platform_post_id']=='accepted-native-id'
    assert 'product_id' not in receipt and 'product_binding_confirmed' not in receipt


def test_form_failure_retries_have_backoff_and_hard_limit(tmp_path):
    from video_processing.utils.wechat_product_execution import product_wait_ready, product_observation_generation
    from types import SimpleNamespace
    from video_processing.utils.wechat_product_execution import _record_product_wait
    active=policy_fixture(tmp_path);db=PipelineDB(str(tmp_path/'db.sqlite'))
    task=freeze_task_product_decision(db,'task:bounded',dict(product_intent='PRODUCT',product_id='700007',product_title='完整指定商品'),active)
    generation=product_observation_generation(active)
    store=ProductWaitStore(tmp_path/'wechat_product_waits.json')
    for n in range(1,9):
        _record_product_wait(task,SimpleNamespace(reason='FORM_NOT_READY',attempt_records=()),tmp_path/'e',tmp_path,'media',generation)
        row=store.records()[0]
        assert row['checks']==n
        assert not product_wait_ready(task,tmp_path,'media',observation_generation=generation)
        with store._locked() as data:data['tasks'][task['task_id']]['next_check_at']=0
        assert product_wait_ready(task,tmp_path,'media',observation_generation=generation) is (n<8)
        assert (task['task_id'] in blocked_product_task_keys(tmp_path,active)) is (n==8)
    assert store.records()[0]['state']=='CHECK_LIMIT'


def test_management_observation_preserves_identity_without_guessing_unbound():
    from scripts.wechat_uploader import _management_product_observation
    record=dict(objectId='native-id',sessionToken='do-not-save',desc=dict(goodsList=[dict(productId='700007',productName='完整指定商品')]))
    observation=_management_product_observation(record)
    assert observation['native_record_shape']['desc']['goodsList'][0]==dict(productId='700007',productName='完整指定商品')
    assert 'do-not-save' not in json.dumps(observation)
    assert _management_product_observation(dict(desc={}))['state']=='UNVERIFIED'


@pytest.mark.parametrize('product,state', [({},'UNBOUND'),({'productId':'700007','title':'完整指定商品'},'BOUND'),({'productId':'','title':''},'UNVERIFIED'),(None,'UNVERIFIED'),([], 'UNVERIFIED')])
def test_native_product_readback_requires_explicit_platform_fields(product,state):
    from scripts.wechat_uploader import _management_product_observation
    result=_management_product_observation({'desc':{'product':product}})
    assert result['state']==state
    if state=='BOUND':assert (result['actual_product_id'],result['actual_title'])==('700007','完整指定商品')


@pytest.mark.parametrize('identity_source', ['FINAL_FORM_READBACK','DOM_SELECTION_AND_UNCHANGED_FORM'])
@pytest.mark.parametrize('bound', [True,False])
@pytest.mark.parametrize('mutation', ['match','wrong_id','wrong_title','wrong_state','wrong_post','missing_source','missing_receipt','unknown_actual'])
def test_platform_product_comparison_uses_exact_work_and_final_receipt(tmp_path,bound,mutation,identity_source):
    from scripts.wechat_uploader import _management_product_observation,_compare_management_product_receipt
    actual=_management_product_observation(dict(desc=dict(product=dict(productId='700007',title='完整指定商品') if bound else {})))
    record=dict(platform_post_id='native-current',product_observation=actual)
    expected=dict(platform_post_id='native-current',product_identity_source=identity_source,product_binding_confirmed=bound,
        product_unbound_confirmed=not bound,product_id='700007' if bound else None,product_title='完整指定商品' if bound else None)
    if mutation=='wrong_id':expected['product_id']='other'
    if mutation=='wrong_title':expected['product_title']='不同版本'
    if mutation=='wrong_state':expected['product_binding_confirmed']=not bound
    if mutation=='wrong_post':expected['platform_post_id']='native-other'
    if mutation=='missing_source':expected.pop('product_identity_source')
    if mutation=='unknown_actual':record['product_observation']={'state':'UNVERIFIED'}
    path=tmp_path/'receipt.json'
    if mutation!='missing_receipt':path.write_text(json.dumps(expected))
    result=_compare_management_product_receipt(record,path)
    wanted='MATCH' if mutation=='match' else ('UNVERIFIED' if mutation in {'wrong_post','missing_source','missing_receipt','unknown_actual'} else 'MISMATCH')
    assert result['state']==wanted


def complete_detail_fixture():
    return dict(errCode=0,data=dict(object=dict(objectId='native-current',objectNonce='12345',desc=dict(
        media=[dict(videoPlayLen=32)],description='完整视频描述',shortTitle=[dict(shortTitle='完整标题')],
        extReading={},modFeedInfo=dict(history=[])))))


@pytest.mark.parametrize('mutation', ['none','error','missing_error','bool_error','missing_data','wrong_post','wrong_nonce','missing_nonce',
    'missing_desc','missing_media','empty_media','missing_description','missing_title','missing_modify_info','other_component',
    'other_link','malformed_product','explicit_empty','bound'])
def test_only_successful_exact_complete_detail_proves_omitted_product(mutation):
    from scripts.wechat_uploader import _management_detail_product_observation
    payload=complete_detail_fixture();post=payload['data']['object'];desc=post['desc']
    if mutation=='error':payload['errCode']=1
    elif mutation=='missing_error':payload.pop('errCode')
    elif mutation=='bool_error':payload['errCode']=False
    elif mutation=='missing_data':payload.pop('data')
    elif mutation=='wrong_post':post['objectId']='other'
    elif mutation=='wrong_nonce':post['objectNonce']='67890'
    elif mutation=='missing_nonce':post.pop('objectNonce')
    elif mutation=='missing_desc':post.pop('desc')
    elif mutation.startswith('missing_'):
        desc.pop({'missing_media':'media','missing_description':'description','missing_title':'shortTitle','missing_modify_info':'modFeedInfo'}[mutation])
    elif mutation=='empty_media':desc['media']=[]
    elif mutation=='other_component':desc['component']={'type':1}
    elif mutation=='other_link':desc['extReading']={'url':'https://example.test'}
    elif mutation=='malformed_product':desc['product']=None
    elif mutation=='explicit_empty':desc['product']={}
    elif mutation=='bound':desc['product']=dict(productId='700007',title='完整指定商品')
    result=_management_detail_product_observation(payload,'native-current','12345')
    assert result['state']==('BOUND' if mutation=='bound' else 'UNBOUND' if mutation in {'none','explicit_empty'} else 'UNVERIFIED')
    assert _management_detail_product_observation(payload,'native-current','')['state']=='UNVERIFIED'


def test_readback_preserves_management_evidence_before_detail_navigation_and_compares_receipt(tmp_path,monkeypatch):
    from scripts import wechat_uploader as uploader
    receipt=tmp_path/'receipt.json'
    receipt.write_text(json.dumps(dict(platform_post_id='native-current',platform_object_nonce='12345',
        product_identity_source='FINAL_FORM_READBACK',product_binding_confirmed=False,product_unbound_confirmed=True,
        product_id=None,product_title=None)))
    record=dict(platform_post_id='native-current',platform_object_nonce='12345',identity_source='post_list_api',
        status_text='已发布',product_observation=dict(state='UNVERIFIED'))
    events=[]
    def load(page,**kwargs):
        assert not kwargs, '不得在原生身份已在当前页时执行标题过滤'
        return {'native-current':record},True
    def detail(*args):
        events.append('detail-navigation')
        return uploader._management_detail_product_observation(complete_detail_fixture(),'native-current','12345')
    monkeypatch.setattr(uploader,'_load_management_cards',load)
    monkeypatch.setattr(uploader,'_capture_wechat_evidence',lambda page,root,name:events.append(name))
    monkeypatch.setattr(uploader,'_read_management_product_detail',detail)
    state,_=uploader.verify_management_publication_by_id(object(),tmp_path/'proof','native-current',
        expected_title='完整标题',identity_receipt=receipt)
    assert state=='PUBLISHED'
    assert events==['management_published','detail-navigation']
    proof=json.loads((tmp_path/'proof/management_readback.json').read_text())
    assert proof['product_verification']['state']=='MATCH'
    assert proof['product_observation']['identity_source']=='POST_INFO_EXACT_WORK'


@pytest.mark.parametrize('mutation', ['match','wrong_id','wrong_title','missing_source','wrong_nonce','non_string_id'])
def test_selected_platform_id_requires_exact_identity_and_source(tmp_path,mutation):
    from scripts.wechat_uploader import _compare_management_product_receipt
    receipt=tmp_path/'submission_receipt.json'
    expected=dict(platform_post_id='native-work',platform_object_nonce='777',product_identity_source='DOM_SELECTION_AND_UNCHANGED_FORM',
        product_id='123',product_platform_id='888',product_platform_id_source='SELECTED_PUBLIC_ROW',product_title='完整图书版本',
        product_binding_confirmed=True,product_unbound_confirmed=False)
    record=dict(platform_post_id='native-work',platform_object_nonce='777',product_observation=dict(state='BOUND',actual_product_id='888',actual_title='完整图书版本'))
    if mutation=='wrong_id':expected['product_platform_id']='999'
    elif mutation=='wrong_title':record['product_observation']['actual_title']='另一版本'
    elif mutation=='missing_source':expected.pop('product_platform_id_source')
    elif mutation=='wrong_nonce':record['platform_object_nonce']='666'
    elif mutation=='non_string_id':expected['product_platform_id']=888
    receipt.write_text(json.dumps(expected))
    wanted='MATCH' if mutation=='match' else 'MISMATCH' if mutation in {'wrong_id','wrong_title'} else 'UNVERIFIED'
    assert _compare_management_product_receipt(record,receipt)['state']==wanted


@pytest.mark.parametrize('mutation', ['match','missing_mapping','wrong_shop_id','wrong_platform_id','wrong_title','wrong_post','wrong_nonce',
    'changed_receipt','wrong_hash','missing_hash','wrong_source','wrong_path','malformed_mapping'])
def test_legacy_mapping_never_uses_title_only_or_another_receipt(tmp_path,mutation):
    import hashlib
    from scripts.wechat_uploader import _compare_management_product_receipt
    receipt=tmp_path/'submission_receipt.json'
    expected=dict(platform_post_id='native-work',platform_object_nonce='777',product_identity_source='DOM_SELECTION_AND_UNCHANGED_FORM',
        product_id='123',product_title='完整图书版本',product_binding_confirmed=True,product_unbound_confirmed=False)
    receipt.write_text(json.dumps(expected));original_bytes=receipt.read_bytes()
    record=dict(platform_post_id='native-work',platform_object_nonce='777',product_observation=dict(state='BOUND',actual_product_id='888',actual_title='完整图书版本'))
    mapping=dict(schema_version=1,source='PLATFORM_CATALOG_READBACK',platform_post_id='native-work',platform_object_nonce='777',
        catalog_response_path='/shop-faas/mmecfinderassistantnode/live/cgi/search_products',
        submission_receipt_sha256=hashlib.sha256(original_bytes).hexdigest(),native_product=dict(productId='888',outProductId='123',title='完整图书版本'))
    if mutation=='wrong_shop_id':mapping['native_product']['outProductId']='999'
    elif mutation=='wrong_platform_id':mapping['native_product']['productId']='999'
    elif mutation=='wrong_title':mapping['native_product']['title']='另一版本'
    elif mutation=='wrong_post':mapping['platform_post_id']='other-work'
    elif mutation=='wrong_nonce':mapping['platform_object_nonce']='666'
    elif mutation=='changed_receipt':receipt.write_text(json.dumps(dict(expected,product_id='999')))
    elif mutation=='wrong_hash':mapping['submission_receipt_sha256']='wrong'
    elif mutation=='missing_hash':mapping.pop('submission_receipt_sha256')
    elif mutation=='wrong_source':mapping['source']='LOCAL_CATALOG'
    elif mutation=='wrong_path':mapping['catalog_response_path']='/other_endpoint'
    if mutation!='missing_mapping':(tmp_path/'product_identity_mapping.json').write_text('[]' if mutation=='malformed_mapping' else json.dumps(mapping))
    result=_compare_management_product_receipt(record,receipt)
    wanted='MATCH' if mutation=='match' else 'MISMATCH' if mutation in {'missing_mapping','wrong_platform_id'} else 'UNVERIFIED'
    assert result['state']==wanted
    if mutation!='changed_receipt':assert receipt.read_bytes()==original_bytes

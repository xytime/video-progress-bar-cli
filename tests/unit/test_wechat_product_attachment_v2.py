"""商品意图冻结与发布入口的隔离回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-11 | Codex | 缺商品可继续，覆盖旧等待释放、身份清理、两入口回执及已提交保护。 |
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pytest
from video_processing.core.wechat_product_attachment import attachment_decision
from video_processing.db.database import PipelineDB
from video_processing.utils.wechat_product_task import freeze_task_product_decision, read_product_task_decision, write_product_task_arguments, manual_product_options, validate_manual_product
from video_processing.utils.wechat_product_execution import execute_product_task

@pytest.mark.parametrize('likes,expected,reason', [(999,False,'SKIP_BELOW_THRESHOLD'),(1000,True,'ATTACH_THRESHOLD'),(1001,True,'ATTACH_THRESHOLD'),(None,False,'SKIP_METRICS_UNKNOWN'),(-1,False,'SKIP_METRICS_INVALID'),(10001,False,'SKIP_METRICS_INVALID'),('bad',False,'SKIP_METRICS_INVALID')])
def test_threshold_exact(likes, expected, reason):
    value=attachment_decision(dict(youtube_id='youtube1234',view_count=10000,like_count=likes))
    assert value['require_product'] is expected and value['reason']==reason

@pytest.mark.parametrize('views', [0,-1,None,float('nan'),float('inf'),True])
def test_invalid_denominator(views):
    assert attachment_decision(dict(youtube_id='youtube1234',view_count=views,like_count=2))['require_product'] is False


def test_daily_atomic_scope_retry_and_cross_day(tmp_path):
    database=PipelineDB(str(tmp_path/'db.sqlite'))
    now=datetime(2026,10,11,15,59,tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows=list(pool.map(lambda n:database.register_product_production(f'task:{n}',now=now), range(8)))
    assert sum(r['is_first'] for r in rows)==1
    first=next(r for r in rows if r['is_first'])
    assert database.register_product_production(first['task_id'],now=now+timedelta(days=1))==first
    assert database.register_product_production('next',now=now+timedelta(minutes=2))['is_first']
    assert database.register_product_production('account2',account_id='local-profile:other',now=now)['is_first']
    low=dict(content_type='ENGLISH_WORLD_SHORT',youtube_id='youtube1234',view_count=100,like_count=1)
    assert attachment_decision(low,first)['require_product']
    second=next(r for r in rows if not r['is_first'])
    assert not attachment_decision(dict(low,like_count=99),second)['require_product']
    assert not attachment_decision(dict(low,product_intent='NONE'))['require_product']
    assert attachment_decision(dict(low,product_intent='PRODUCT',product_id='123',product_title='指定商品'))['reason']=='ATTACH_MANUAL'


def test_migration_auto_and_new_manual_none_slices(tmp_path):
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    db.add_video('oldyoutube1','old','channel',source='MANUAL')
    db.add_video('newyoutube1','new','channel',source='MANUAL',product_intent='NONE')
    assert db.get_video_by_youtube_id('oldyoutube1')['product_intent']=='AUTO'
    assert db.get_video_by_youtube_id('newyoutube1')['product_intent']=='NONE'
    assert db.batch_add_videos([dict(youtube_id='newyoutube1',slice_index=1,title='slice',channel_id='channel',product_intent='NONE',view_count=100,like_count=90)])
    row=db.get_video_by_youtube_id('newyoutube1',slice_index=1)
    assert row['product_intent']=='NONE' and row['like_count']==90


def test_none_freezes_without_catalog_dependency_and_stops_submitted(tmp_path):
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    context=dict(product_intent='NONE',content_type='ENGLISH_WORLD_SHORT',youtube_id='youtube1234',view_count=100,like_count=99)
    value=freeze_task_product_decision(db,'manual:1',context,tmp_path/'missing.json')
    args=write_product_task_arguments(value,tmp_path/'evidence')
    assert read_product_task_decision(Path(args[1]))==value
    assert freeze_task_product_decision(db,'manual:1',dict(context,product_intent='AUTO'),tmp_path/'missing.json')==value
    assert db.get_product_production('manual:1') is None
    with pytest.raises(ValueError,match='禁止'):
        freeze_task_product_decision(db,'submitted',dict(context,status='UNDER_REVIEW'),tmp_path/'missing.json')
    with pytest.raises(ValueError,match='制作登记'):
        freeze_task_product_decision(db,'english:old',dict(context,product_intent='AUTO'),tmp_path/'missing.json')

class EmptyPicker:
    def __init__(self, binding=None): self.binding=binding;self.clears=0
    def read_binding(self,**kwargs): return self.binding
    def cancel_and_clear(self,**kwargs): self.clears+=1;self.binding=None;return True
    def ready_to_submit(self,**kwargs):return True
    def find(self,*args,**kwargs):raise AssertionError('skip cannot select product')


def test_skip_clears_and_never_calls_selector(tmp_path):
    from video_processing.core.wechat_product_policy import ProductIdentity
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    task=freeze_task_product_decision(db,'task',dict(product_intent='NONE'),tmp_path/'missing')
    picker=EmptyPicker(ProductIdentity('123','旧商品'))
    assert execute_product_task(task,picker,tmp_path/'e',tmp_path/'status.json')
    assert picker.clears==1
    receipt=json.loads((tmp_path/'e/product_selection_receipt.json').read_text())
    assert receipt['unbound_confirmed'] and not receipt['binding_confirmed']
    class Unknown(EmptyPicker):
        def read_binding(self,**kwargs): raise ValueError('unknown')
    assert not execute_product_task(task,Unknown(),tmp_path/'bad',tmp_path/'status.json')

def product_fixture(tmp_path):
    config=json.loads((Path(__file__).parents[1]/'fixtures/wechat_products_v2.json').read_text())
    active=tmp_path/'wechat_products.json';active.write_text(json.dumps(config))
    catalog=dict(schema_version=2,captured_at='2026-10-01T00:00:00+08:00',source='核实的发布账号后台导出',account_id='publisher-verified',total_pages=1,total_items=1,
                 pages=[dict(page=1,items=[dict(product_id='700007',title='未被类型配置引用的真实完整测试书',shop='测试店铺',price='20',stock=12)])])
    active.with_name('wechat_product_catalog.json').write_text(json.dumps(catalog))
    return active


def test_unbound_receipt_satisfies_english_submission_and_final_form_gate(tmp_path):
    from scripts.submit_english_world_review import _product_receipt_is_confirmed
    from video_processing.core.wechat_product_policy import ProductLookup, ProductIdentity
    from video_processing.utils.wechat_product_execution import verify_product_before_submit
    active=product_fixture(tmp_path)
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    selected=validate_manual_product(active,'product_700007')
    task=freeze_task_product_decision(db,'english:optional',dict(product_intent='PRODUCT',
        product_id=selected['product_id'],product_title=selected['title']),active)
    class Unavailable(EmptyPicker):
        def find(self,*args,**kwargs):return ProductLookup.UNAVAILABLE
    picker=Unavailable()
    evidence=tmp_path/'evidence'
    assert execute_product_task(task,picker,evidence,tmp_path/'status')
    assert verify_product_before_submit(task,picker)
    assert _product_receipt_is_confirmed(evidence,task)
    picker.binding=ProductIdentity('wrong','残留商品')
    assert not verify_product_before_submit(task,picker)
    path=evidence/'product_selection_receipt.json'
    receipt=json.loads(path.read_text())
    receipt['unbound_confirmed']=False;path.write_text(json.dumps(receipt))
    assert not _product_receipt_is_confirmed(evidence,task)
    receipt['unbound_confirmed']=True;receipt['task_id']='different';path.write_text(json.dumps(receipt))
    assert not _product_receipt_is_confirmed(evidence,task)


def test_full_catalog_exact_manual_no_fallback_and_frozen_versions(tmp_path):
    from video_processing.core.wechat_product_policy import ProductLookup, ProductIdentity
    active=product_fixture(tmp_path)
    options=manual_product_options(active)
    selected=validate_manual_product(active,'product_700007')
    assert selected['selectable'] and selected['product_id']=='700007'
    assert len(options['products'])==4
    # 旧无账号资料仍显示，但不能把清单中另一件的账号冒充其已核实账号。
    assert not next(r for r in options['products'] if r['alias']=='finance')['selectable']
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    context=dict(product_intent='PRODUCT',product_id=selected['product_id'],product_title=selected['title'],
                 youtube_id='youtube1234',content_type='ENGLISH_WORLD_SHORT',view_count=100,like_count=1)
    task=freeze_task_product_decision(db,'manual',context,active)
    assert task['reason']=='ATTACH_MANUAL' and len(task['product_decision']['candidates'])==1
    assert db.get_product_production('manual') is None
    class ExactPicker(EmptyPicker):
        def find(self,product,**kwargs):
            assert product==ProductIdentity('700007',selected['title'])
            return ProductLookup.AVAILABLE
        def select(self,product,**kwargs):self.binding=product
    assert execute_product_task(task,ExactPicker(),tmp_path/'evidence',tmp_path/'status.json')
    config=json.loads(active.read_text());config['version']='changed-later';active.write_text(json.dumps(config))
    assert freeze_task_product_decision(db,'manual',context,active)==task
    assert task['config_version']!='changed-later'
    class Missing(ExactPicker):
        def find(self,product,**kwargs):
            assert product.product_id=='700007'
            return ProductLookup.UNAVAILABLE
    assert execute_product_task(task,Missing(),tmp_path/'missing-evidence',tmp_path/'status.json')
    missing_receipt=json.loads((tmp_path/'missing-evidence/product_selection_receipt.json').read_text())
    assert missing_receipt['unbound_confirmed'] and missing_receipt['actual_product_id'] is None
    class Wrong(ExactPicker):
        def select(self,product,**kwargs):self.binding=ProductIdentity('700008',selected['title'])
    wrong=Wrong()
    assert execute_product_task(task,wrong,tmp_path/'wrong-evidence',tmp_path/'status.json')
    assert wrong.binding is None  # 错 ID 必须清空，不能伪报挂载成功。


def test_manual_api_saves_atomically_duplicate_preserves_and_invalid_no_fetch(tmp_path,monkeypatch):
    from fastapi import BackgroundTasks
    from web import app as web_app
    active=product_fixture(tmp_path)
    database=PipelineDB(str(tmp_path/'db.sqlite'))
    monkeypatch.setattr(web_app,'db',database)
    monkeypatch.setattr(web_app.settings,'wechat_product_policy_path',active)
    from types import SimpleNamespace
    fetched=[]
    def fetch(*args,**kwargs):
        fetched.append(args)
        return SimpleNamespace(stdout='youtube1234|||标题|||channel|||频道|||60|||100|||99|||20261001',stderr='')
    monkeypatch.setattr(web_app.subprocess,'run',fetch)
    request=web_app.AddVideoRequest(url='https://youtube.com/watch?v=youtube1234',product_intent='PRODUCT',product_alias='missing')
    assert not web_app.add_video_manual(request,BackgroundTasks())['success'] and not fetched
    request=web_app.AddVideoRequest(url='https://youtube.com/watch?v=youtube1234',product_intent='PRODUCT',product_alias='product_700007',trim_start='1',trim_end='50')
    value=web_app.add_video_manual(request,BackgroundTasks())
    assert value['success'] and value['product_id']=='700007'
    row=database.get_video_by_youtube_id('youtube1234')
    assert row['product_intent']=='PRODUCT' and row['trim_start']=='1' and row['product_title']==value['product_title']
    again=web_app.add_video_manual(web_app.AddVideoRequest(url=request.url),BackgroundTasks())
    assert not again['success'] and again['already_exists']
    assert database.get_video_by_youtube_id('youtube1234')['product_intent']=='PRODUCT'
    active.unlink()
    def fetch_next(*args,**kwargs):
        return SimpleNamespace(stdout='youtube5678|||另一标题|||channel|||频道|||60|||100|||99|||20261001',stderr='')
    monkeypatch.setattr(web_app.subprocess,'run',fetch_next)
    value=web_app.add_video_manual(web_app.AddVideoRequest(url='https://youtu.be/youtube5678',content_type='ENGLISH_WORLD_SHORT'),BackgroundTasks())
    assert value['success']
    assert database.get_video_by_youtube_id('youtube5678')['product_intent']=='NONE'


def test_unknown_account_full_catalog_explicit_reason(tmp_path):
    active=product_fixture(tmp_path)
    path=active.with_name('wechat_product_catalog.json')
    data=json.loads(path.read_text())
    old=dict(schema_version=1,captured_at=data['captured_at'],source=data['source'],source_sha256='a'*64,completeness='unverified',items=data['pages'][0]['items'])
    path.write_text(json.dumps(old))
    options=manual_product_options(active)
    assert len(options['products'])==4 and options['account_id'] is None
    assert next(r for r in options['products'] if r['product_id']=='700007')['selectable']
    assert next(r for r in options['products'] if r['product_id']=='700007')['identity_status']=='HISTORICAL_PENDING_SESSION_CHECK'
    assert not next(r for r in options['products'] if r['alias']=='finance')['selectable']

@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_metrics_freeze_transport_and_readback(tmp_path,value):
    import subprocess
    import sys
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    task=freeze_task_product_decision(db,'invalid',dict(youtube_id='youtube1234',view_count=value,like_count=value),tmp_path/'missing')
    assert task['reason']=='SKIP_METRICS_INVALID' and task['require_product'] is False
    assert task['context']['view_count']==repr(value) and task['context']['view_count_raw_type']=='nonfinite_float'
    args=write_product_task_arguments(task,tmp_path/'input')
    assert read_product_task_decision(Path(args[1]))==task
    assert json.loads(Path(args[1]).read_text())['metrics']['status']=='INVALID'
    code="import sys,json;sys.path.insert(0,sys.argv[1]);from video_processing.utils.wechat_product_task import read_product_task_decision;print(json.dumps(read_product_task_decision(__import__('pathlib').Path(sys.argv[2])),allow_nan=False))"
    child=subprocess.run([sys.executable,'-c',code,str(Path(__file__).parents[2]/'src'),args[1]],check=True,capture_output=True,text=True,timeout=10)
    assert json.loads(child.stdout)==task


def test_profile_scope_uses_actual_session_path_without_reading_state(tmp_path):
    from video_processing.utils.wechat_product_task import product_profile_scope
    a=product_profile_scope(tmp_path/'one.json')
    assert a==product_profile_scope(tmp_path/'child/../one.json')
    assert a!=product_profile_scope(tmp_path/'two.json') and a.startswith('local-profile:')
    assert not (tmp_path/'one.json').exists()


def test_product_wait_no_longer_blocks_unsubmitted_task_but_preserves_artifacts(tmp_path):
    from video_processing.core.wechat_product_policy import ProductLookup
    from video_processing.utils.wechat_product_execution import product_wait_ready, product_observation_generation, blocked_product_task_keys
    from video_processing.utils.wechat_product_waits import ProductWaitStore
    active=product_fixture(tmp_path);db=PipelineDB(str(tmp_path/'db.sqlite'))
    chosen=validate_manual_product(active,'product_700007')
    task=freeze_task_product_decision(db,'pipeline:youtube1234:0',dict(product_intent='PRODUCT',product_id=chosen['product_id'],product_title=chosen['title']),active)
    task['_observation_generation']=product_observation_generation(active)
    class Missing(EmptyPicker):
        def find(self,product,**kwargs):return ProductLookup.UNAVAILABLE
    assert execute_product_task(task,Missing(),tmp_path/'failed',tmp_path/'status',wait_output=tmp_path,artifacts_digest='media')
    store=ProductWaitStore(tmp_path/'wechat_product_waits.json')
    assert not store.records()  # 无商品放行不再制造等待。
    store.defer(task['task_id'],reason='PRODUCT_UNAVAILABLE',config_digest=task['config_digest'],
                artifacts_digest='media',submission_state='NOT_SUBMITTED')
    assert product_wait_ready(task,tmp_path,'media',observation_generation=task['_observation_generation'])
    class Available(EmptyPicker):
        def find(self,product,**kwargs):return ProductLookup.AVAILABLE
        def select(self,product,**kwargs):self.binding=product
    picker=Available()
    assert execute_product_task(task,picker,tmp_path/'recovery',tmp_path/'status',wait_output=tmp_path,artifacts_digest='media')
    assert picker.binding.product_id==chosen['product_id']
    assert task['task_id'] not in blocked_product_task_keys(tmp_path,active)
    assert not product_wait_ready(task,tmp_path,'changed-media',observation_generation=task['_observation_generation'])
    with store._locked() as data:data['tasks'][task['task_id']]['submission_state']='UNCERTAIN'
    assert not product_wait_ready(task,tmp_path,'media')
    assert task['task_id'] in blocked_product_task_keys(tmp_path,active)


def test_sql_wait_filter_before_limit_no_queue_starvation(tmp_path,monkeypatch):
    from scripts import run_ready_publications as worker
    from video_processing.utils.wechat_product_execution import product_observation_generation
    from video_processing.utils.wechat_product_waits import ProductWaitStore
    active=product_fixture(tmp_path);out=tmp_path/'output';out.mkdir()
    db=PipelineDB(str(out/'db.sqlite'))
    # More than any fixed small scan limit: filtering must occur before LIMIT.
    for n in range(35):
        yid=f'blocked{n:03d}'
        db.add_video(yid,yid,'channel',score=100,product_intent='AUTO')
        db.mark_video_ready_for_publication(yid)
        ProductWaitStore(out/'wechat_product_waits.json').defer(f'pipeline:{yid}:0',reason='PRODUCT_UNAVAILABLE',
            config_digest='policy',artifacts_digest='media',submission_state='NOT_SUBMITTED',
            observation_generation=product_observation_generation(active))
    db.add_video('available','NONE','channel',score=80,product_intent='NONE')
    db.mark_video_ready_for_publication('available')
    class Manager:
        def __init__(self):self.db=db;self.called=[]
        def _process_single_video(self,row,**kwargs):self.called.append(row['youtube_id'])
    manager=Manager();monkeypatch.setattr(worker,'ROOT',tmp_path)
    monkeypatch.setattr(worker.settings,'wechat_product_policy_path',active)
    assert worker.dispatch_once(manager)==1 and manager.called==['blocked000']
    store=ProductWaitStore(out/'wechat_product_waits.json')
    with store._locked() as rows:rows['tasks']['pipeline:blocked000:0']['next_check_at']=0
    assert worker.dispatch_once(manager)==1 and manager.called[-1]=='blocked000'
    with store._locked() as rows:rows['tasks']['pipeline:blocked000:0']['state']='BLOCKED'
    assert worker.dispatch_once(manager)==1 and manager.called[-1]=='blocked000'
    with store._locked() as rows:
        for row in rows['tasks'].values():row['submission_state']='UNCERTAIN'
    assert worker.dispatch_once(manager)==1 and manager.called[-1]=='available'


@pytest.mark.parametrize('stock,disabled', [(0, False), (12, True)])
def test_queued_manual_stock_wait_and_disabled_block_preserve_original(tmp_path, stock, disabled):
    from video_processing.utils.wechat_product_execution import product_task_preflight, blocked_product_task_keys
    from video_processing.utils.wechat_product_waits import ProductWaitStore
    active=product_fixture(tmp_path);db=PipelineDB(str(tmp_path/'db.sqlite'))
    selected=validate_manual_product(active,'product_700007')
    db.add_video('manualbook','original','channel',product_intent='PRODUCT',product_id=selected['product_id'],product_title=selected['title'])
    catalog=active.with_name('wechat_product_catalog.json');data=json.loads(catalog.read_text())
    data['pages'][0]['items'][0]['stock']=stock;catalog.write_text(json.dumps(data))
    if disabled:
        config=json.loads(active.read_text())
        config['products']['product_700007']=dict(product_id=selected['product_id'],title=selected['title'],enabled=False,
                                                verified_at='2026-10-01',verified_source='isolated account export')
        active.write_text(json.dumps(config))
    with pytest.raises(ValueError):validate_manual_product(active,'product_700007')
    row=db.get_video_by_youtube_id('manualbook')
    task=freeze_task_product_decision(db,'pipeline:manualbook:0',row,active)
    assert task['product_decision']['candidates']==[dict(product_id=selected['product_id'],title=selected['title'])]
    if disabled:
        assert task['selection_block_reason']=='MANUAL_PRODUCT_DISABLED'
        assert product_task_preflight(task,tmp_path,'media')
        assert task['task_id'] not in blocked_product_task_keys(tmp_path,active)
        assert execute_product_task(task,EmptyPicker(),tmp_path/'evidence',tmp_path/'status',wait_output=tmp_path,artifacts_digest='media')
        receipt=json.loads((tmp_path/'evidence/product_selection_receipt.json').read_text())
        assert receipt['unbound_confirmed'] and receipt['fallback_reason']=='MANUAL_PRODUCT_DISABLED'
    else:
        assert 'selection_block_reason' not in task
        assert product_task_preflight(task,tmp_path,'media')  # 平台当前库存核验决定，不拿历史0代替实时结果。


def test_english_ready_wait_filter_entire_queue_before_limit(tmp_path,monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from scripts import run_ready_publications as worker
    from video_processing.utils.wechat_product_execution import product_observation_generation
    from video_processing.utils.wechat_product_waits import ProductWaitStore
    active=product_fixture(tmp_path);out=tmp_path/'output';out.mkdir()
    db=PipelineDB(str(out/'db.sqlite'));store=ProductWaitStore(out/'wechat_product_waits.json')
    selected=validate_manual_product(active,'product_700007');identities=[]
    for n in range(36):
        item=db.create_english_world_review_item(artifact_sha256=hashlib.sha256(str(n).encode()).hexdigest(),title=str(n),
            mp4_path=str(tmp_path/f'{n}.mp4'),manifest_path=str(tmp_path/f'{n}.json'),title_path=str(tmp_path/f'{n}.title'),
            copy_path=str(tmp_path/f'{n}.copy'),cover_path=str(tmp_path/f'{n}.png'),cover_provenance_path=str(tmp_path/f'{n}.provenance'))
        db.approve_english_world_submission(item['id'],authorization='AUTO_POLICY')
        with db.get_connection() as conn:
            conn.execute('UPDATE english_world_review_items SET approved_at=? WHERE id=?',(f'2026-10-11 00:00:{n:02d}',item['id']));conn.commit()
        key=f'english:{n}';identities.append((item['id'],key))
        context=dict(review_id=item['id'],product_intent='PRODUCT' if n<35 else 'NONE',content_type='ENGLISH_WORLD_SHORT')
        if n<35:context.update(product_id=selected['product_id'],product_title=selected['title'])
        freeze_task_product_decision(db,key,context,active)
        if n<35:store.defer(key,reason='PRODUCT_UNAVAILABLE',config_digest='frozen',artifacts_digest='media',
            submission_state='NOT_SUBMITTED',observation_generation=product_observation_generation(active))
    called=[]
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    monkeypatch.setattr(worker,'settings',SimpleNamespace(enable_english_world_auto_publish=True,wechat_publishing_paused=False,wechat_product_policy_path=active))
    monkeypatch.setattr(worker.subprocess,'run',lambda args,**kw:(called.append(args) or SimpleNamespace(returncode=10)))
    manager=SimpleNamespace(db=db,_report_runtime_stage=lambda *a,**kw:None)
    assert worker.dispatch_english_world_once(manager)==1 and called[-1][-1]==identities[0][0]
    with store._locked() as rows:rows['tasks'][identities[0][1]]['next_check_at']=0
    assert worker.dispatch_english_world_once(manager)==1 and called[-1][-1]==identities[0][0]
    with store._locked() as rows:rows['tasks'][identities[0][1]]['state']='BLOCKED'
    assert worker.dispatch_english_world_once(manager)==1 and called[-1][-1]==identities[0][0]
    with store._locked() as rows:
        for row in rows['tasks'].values():row['submission_state']='UNCERTAIN'
    assert worker.dispatch_english_world_once(manager)==1 and called[-1][-1]==identities[-1][0]


def test_runtime_diagnostics_readonly_and_adoption_requires_current_terminal_proof(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web.product_settings import create_product_settings_router
    from video_processing.utils.wechat_product_config import load_policy
    from video_processing.utils.wechat_product_task import PUBLISHER_CAPABILITY
    active=product_fixture(tmp_path);status=tmp_path/'status.json';policy=load_policy(active)
    app=FastAPI();app.include_router(create_product_settings_router(active=active,status=status,output=tmp_path,videos=lambda:[],publisher_connected=True))
    client=TestClient(app)
    baseline={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    diag=client.get('/api/product-settings/runtime').json()
    assert diag['publisher_capability']==PUBLISHER_CAPABILITY and diag['config_digest']==policy.digest
    assert not diag['actual_task_adoption'] and not diag['scope_is_platform_account']
    assert baseline=={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    for receipt,verified,bound in [
        (dict(phase='STARTED',publisher_capability=PUBLISHER_CAPABILITY,config_digest=policy.digest),False,False),
        (dict(phase='BOUND',binding_confirmed=True,config_digest=policy.digest),False,False),
        (dict(phase='BOUND',binding_confirmed=True,publisher_capability=PUBLISHER_CAPABILITY,config_digest='old'),False,False),
        (dict(phase='BOUND',binding_confirmed=True,publisher_capability=PUBLISHER_CAPABILITY,config_digest=policy.digest),True,True),
        (dict(phase='SKIPPED',unbound_confirmed=True,publisher_capability=PUBLISHER_CAPABILITY,config_digest=policy.digest),True,False),
        (dict(phase='UNBOUND',unbound_confirmed=True,binding_confirmed=False,publisher_capability=PUBLISHER_CAPABILITY,config_digest=policy.digest),True,False)]:
        status.write_text(json.dumps(receipt))
        value=client.get('/api/product-settings').json()['status']
        assert value['runtime_adoption_verified'] is verified and value['actual_binding_verified'] is bound


def test_final_binding_failure_wait_only_before_submit_and_clears_adoption(tmp_path):
    from video_processing.utils.wechat_product_execution import record_pre_submit_product_block
    from video_processing.utils.wechat_product_waits import ProductWaitStore
    active=product_fixture(tmp_path);db=PipelineDB(str(tmp_path/'db.sqlite'))
    selected=validate_manual_product(active,'product_700007')
    task=freeze_task_product_decision(db,'manual',dict(product_intent='PRODUCT',product_id=selected['product_id'],product_title=selected['title']),active)
    evidence=tmp_path/'evidence';evidence.mkdir()
    record_pre_submit_product_block(task,evidence,tmp_path/'status.json',tmp_path,'media','BINDING_CHANGED_BEFORE_SUBMIT')
    assert ProductWaitStore(tmp_path/'wechat_product_waits.json').records()[0]['state']=='BLOCKED'
    receipt=json.loads((evidence/'product_selection_receipt.json').read_text())
    assert receipt['state']=='BLOCKED' and not receipt['binding_confirmed']
    assert json.loads((evidence/'product_wait.json').read_text())['not_submitted']
    (evidence/'submission_receipt.json').write_text('{"platform_post_id":"accepted"}')
    before=(tmp_path/'wechat_product_waits.json').read_bytes()
    with pytest.raises(ValueError,match='原作品'):
        record_pre_submit_product_block(task,evidence,tmp_path/'status.json',tmp_path,'media','BINDING_CHANGED_BEFORE_SUBMIT')
    assert (tmp_path/'wechat_product_waits.json').read_bytes()==before


def test_legacy_cutover_once_concurrent_restart_hash_bound_and_no_daily_slot(tmp_path):
    path=tmp_path/'db.sqlite';db=PipelineDB(str(path))
    def item(n):
        return db.create_english_world_review_item(artifact_sha256=str(n)*64,manifest_sha256='a'*64,
            title_sha256='b'*64,copy_sha256='c'*64,cover_sha256='d'*64,cover_provenance_sha256='e'*64,title=f'package{n}',
            mp4_path=str(tmp_path/f'{n}.mp4'),manifest_path=str(tmp_path/f'{n}.json'),title_path=str(tmp_path/f'{n}.title'),
            copy_path=str(tmp_path/f'{n}.copy'),cover_path=str(tmp_path/f'{n}.png'),cover_provenance_path=str(tmp_path/f'{n}.provenance'))
    old=item(1)
    # 仅隔离迁移 fixture 模拟上线前没有哨兵的旧数据库，不改生产。
    with db.get_connection() as conn:
        conn.execute("DELETE FROM product_contract_meta WHERE key='legacy-review-cutover-v2'");conn.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        restarted=list(pool.map(lambda _:PipelineDB(str(path)),range(4)))
    assert all(instance.is_legacy_product_review(old['id'],'a'*64) for instance in restarted)
    assert db.get_english_world_review_item(old['id'])['state']==old['state']
    assert not db.is_legacy_product_review(old['id'],'f'*64)
    new=item(2)
    again=PipelineDB(str(path))
    assert not again.is_legacy_product_review(new['id'],'a'*64)
    context=dict(content_type='ENGLISH_WORLD_SHORT',legacy_pre_cutover=True,legacy_review_id=old['id'],legacy_manifest_sha256='a'*64)
    decision=freeze_task_product_decision(again,'legacy-review:'+old['id'],context,tmp_path/'missing')
    assert decision['reason']=='SKIP_LEGACY_PRE_CUTOVER' and not decision['require_product']
    assert again.get_product_production(decision['task_id']) is None
    with pytest.raises(ValueError,match='首次迁移'):
        freeze_task_product_decision(again,'legacy-review:'+new['id'],dict(context,legacy_review_id=new['id']),tmp_path/'missing')


def test_concurrent_freeze_one_snapshot_survives_restart(tmp_path):
    path=tmp_path/'db.sqlite';db=PipelineDB(str(path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions=list(pool.map(lambda n:freeze_task_product_decision(db,'same',dict(product_intent='NONE',youtube_id='youtube1234',view_count=100,like_count=n),tmp_path/'missing'),range(8)))
    assert all(decision==decisions[0] for decision in decisions)
    assert PipelineDB(str(path)).get_product_task_decision('same')==decisions[0]

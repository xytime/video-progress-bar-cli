"""当前商品池与内容匹配合同的边界验收；全部使用临时文件和合成身份。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | TTL、CAS、人工禁用、特定主题、旧重放、英语分片及独立预算反例。 |
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from config.settings import settings
from config.wechat_operations_schema import APPROVED
from tests.unit.test_wechat_product_attachment_v2 import product_fixture, EmptyPicker
from video_processing.core.wechat_account_schedule import _evaluate_operations
from video_processing.core.wechat_product_matching import MATCH_VERSION, digest, rank_products, validate_matching_config
from video_processing.db.database import PipelineDB
from video_processing.utils.wechat_product_catalog import catalog_digest
from video_processing.utils.wechat_product_config import load_policy, PolicyConflict
from video_processing.utils.wechat_product_content_task import content_evidence, dialogue_text
from video_processing.utils.wechat_product_execution import execute_product_task, finalize_product_before_submit
from video_processing.utils.wechat_product_pool import (COLLECTOR_VERSION, attestation_path, load_live_pool,
                                                       promote_live_catalog)
from video_processing.utils.wechat_product_task import (freeze_task_product_decision, read_product_task_decision,
                                                       write_product_task_arguments)


def observation(document, states=None):
    return dict(schema_version=1, collector_version=COLLECTOR_VERSION, account_id=document['account_id'],
        captured_at=document['captured_at'], read_only=True, mutating_actions=[],
        account_evidence=dict(kind='PUBLIC_DOM_STABLE_ID', value=document['account_id'],
                              selector='[data-publisher-finder-username]', attribute='data-publisher-finder-username'),
        page_urls=['https://channels.weixin.qq.com/platform/post/create'],
        observations=[dict(product_id=i['product_id'], title=i['title'], stock=i['stock'], page=p['page'],
                           sale_state=(states or {}).get(i['product_id'], 'AVAILABLE'))
                      for p in document['pages'] for i in p['items']])


@pytest.fixture
def live(tmp_path):
    directory = tmp_path/'config'; directory.mkdir()
    active = product_fixture(directory)
    policy = load_policy(active)
    products = json.loads(policy.serialized)['products']
    items = [dict(product_id=p['product_id'], title=p['title'], stock=5, price='20', shop='合成店铺')
             for p in products.values()]
    now = datetime.now(timezone.utc)
    doc = dict(schema_version=2, captured_at=now.isoformat(), source=COLLECTOR_VERSION,
               account_id='publisher-verified', total_pages=1, total_items=len(items), pages=[dict(page=1, items=items)])
    path = active.with_name('wechat_product_catalog.json')
    promote_live_catalog(doc, observation(doc), active, expected_catalog_digest=catalog_digest(path),
                         expected_policy_digest=policy.digest)
    config = dict(schema_version=1, enabled=True, min_score=4,
                  themes={products['finance']['product_id']: dict(title=products['finance']['title'],
                           phrases=['stock market', '股票'], categories=['财经'])})
    active.with_name('wechat_product_matching.json').write_text(json.dumps(config))
    return active, doc, config, now


def test_ttl_boundary_and_manual_import_cannot_self_attest(live):
    active, doc, config, now = live
    assert load_live_pool(active, now=now+timedelta(days=7))['ready']
    stale = load_live_pool(active, now=now+timedelta(days=7, seconds=1))
    assert stale['reason']=='CATALOG_STALE' and not stale['eligible']
    proof = attestation_path(active); saved = json.loads(proof.read_text())
    saved['catalog_digest']='wrong'; proof.write_text(json.dumps(saved))
    assert load_live_pool(active, now=now)['reason']=='CATALOG_UNVERIFIED'
    proof.unlink()
    assert not load_live_pool(active, now=now)['ready']


@pytest.mark.parametrize('fault', ['account','title','stock','sale','mutating','origin','page'])
def test_invalid_observations_never_promote_or_refresh(live, fault):
    active, doc, _, _ = live
    path=active.with_name('wechat_product_catalog.json'); before=path.read_bytes()
    proof_before=attestation_path(active).read_bytes(); proof=observation(doc)
    if fault=='account': proof['account_evidence']['value']='other'
    if fault=='title': proof['observations'][0]['title']='另一个版本'
    if fault=='stock': proof['observations'][0]['stock']=99
    if fault=='sale': proof['observations'][0]['sale_state']='GUESS'
    if fault=='mutating': proof['mutating_actions']=['upload']
    if fault=='origin': proof['page_urls']=['https://other.invalid/']
    if fault=='page': proof['observations'][0]['page']=2
    with pytest.raises(ValueError):
        promote_live_catalog(doc, proof, active, expected_catalog_digest=catalog_digest(path),
                             expected_policy_digest=load_policy(active).digest)
    assert path.read_bytes()==before and attestation_path(active).read_bytes()==proof_before


def test_cas_archive_and_new_items_without_strategy_rewrite(live):
    active, doc, _, now=live; before=active.read_bytes()
    path=active.with_name('wechat_product_catalog.json'); old=path.read_bytes(); old_digest=catalog_digest(path)
    doc=deepcopy(doc); doc['captured_at']=(now+timedelta(seconds=1)).isoformat()
    doc['pages'][0]['items'].append(dict(product_id='888', title='系统反馈回路', stock=None, price='20', shop='合成店铺'))
    doc['total_items']+=1
    with pytest.raises(PolicyConflict):
        promote_live_catalog(doc, observation(doc), active, expected_catalog_digest='wrong', expected_policy_digest=load_policy(active).digest)
    promote_live_catalog(doc, observation(doc), active, expected_catalog_digest=old_digest, expected_policy_digest=load_policy(active).digest)
    pool=load_live_pool(active, now=now+timedelta(seconds=2))
    assert any(p['product_id']=='888' for p in pool['eligible'])
    assert active.read_bytes()==before
    archived=json.loads((path.with_name('wechat_product_catalog_history')/(old_digest+'.json')).read_text())
    assert archived['original_digest']==hashlib.sha256(old).hexdigest()


@pytest.mark.parametrize('fault,expected', [('disabled','DISABLED'),('zero','OUT_OF_STOCK'),
    ('unknown','SALE_UNVERIFIED_OR_UNAVAILABLE'),('down','SALE_UNVERIFIED_OR_UNAVAILABLE')])
def test_current_eligibility_filters(live, fault, expected):
    active, doc, _, _=live; pid=doc['pages'][0]['items'][1]['product_id']
    if fault=='disabled':
        policy=json.loads(active.read_text())
        alias=next(k for k,p in policy['products'].items() if p['product_id']==pid)
        policy['products'][alias]['enabled']=False
        # 旧策略要求引用链可达；合法人工停用同时解除原规则引用。
        fallback=policy['default_candidates'][0]
        for rule in [*policy['rules'], *policy.get('profiles',{}).values()]:
            rule['candidates']=[fallback if a==alias else a for a in rule['candidates']]
        active.write_text(json.dumps(policy))
    else:
        path=active.with_name('wechat_product_catalog.json')
        if fault=='zero': doc['pages'][0]['items'][1]['stock']=0
        states={pid:'UNKNOWN' if fault=='unknown' else 'UNAVAILABLE' if fault=='down' else 'AVAILABLE'}
        promote_live_catalog(doc, observation(doc, states), active, expected_catalog_digest=catalog_digest(path), expected_policy_digest=load_policy(active).digest)
    pool=load_live_pool(active)
    assert {'product_id':pid,'reason':expected} in pool['excluded']


@pytest.mark.parametrize('content,qualified', [({'title':'stock market outlook'},True),
    ({'subtitle':'stock market '*100},False), ({'subtitle':'stock market','tags':['stock market']},True),
    ({'title':'news education AI','category':'财经'},False), ({'title':'livestock market'},False)])
def test_specific_theme_score_and_no_repetition_inflation(live, content, qualified):
    active, _, config, _=live
    ranked=rank_products(content, load_live_pool(active), config, max_attempts=3)
    assert bool(ranked['candidates']) is qualified
    if not qualified: assert ranked['reason']=='MATCH_EMPTY'
    if content.get('subtitle','').startswith('stock market '*2):
        assert next(r for r in ranked['scores'] if r['specific_theme_hit'])['score']==2


def test_deterministic_ties_and_attempt_ceiling():
    pool={'ready':True,'eligible':[dict(product_id=str(i),title='系统反馈回路') for i in [4,2,3,1]]}
    config=dict(schema_version=1,enabled=True,min_score=4,themes={})
    ranked=rank_products({'title':'系统反馈回路'},pool,config,max_attempts=3)
    assert [p['product_id'] for p in ranked['candidates']]==['1','2','3']
    with pytest.raises(ValueError): validate_matching_config(dict(config,min_score=3))
    config['themes']['1']=dict(title='系统反馈回路',phrases=['AI'],categories=[])
    with pytest.raises(ValueError): validate_matching_config(config)


@pytest.mark.parametrize('likes', [0,1,None,-1])
def test_new_auto_ignores_like_gate_and_frozen_replay(live, tmp_path, likes):
    active, _, _, now=live; db=PipelineDB(str(tmp_path/'test.sqlite'))
    context=dict(product_intent='AUTO',video_title='stock market outlook',view_count=100,like_count=likes)
    task=freeze_task_product_decision(db,'new:auto',context,active,now=now)
    assert task['attachment_version']==MATCH_VERSION and task['require_product']
    assert task['threshold_percent'] is None and task['reason']=='MATCH_L1'
    args=write_product_task_arguments(task,tmp_path/'evidence')
    assert read_product_task_decision(Path(args[1]))==task
    active.with_name('wechat_product_catalog.json').unlink()
    active.with_name('wechat_product_matching.json').unlink()
    assert freeze_task_product_decision(db,'new:auto',{'video_title':'unrelated'},active)==task
    assert read_product_task_decision(Path(args[1]))==task
    task['matching_snapshot']['algorithm_version']='changed'
    task['matching_digest']=digest(task['matching_snapshot'])
    Path(args[1]).write_text(json.dumps(task))
    with pytest.raises(ValueError): read_product_task_decision(Path(args[1]))


def test_none_legacy_and_match_empty_do_not_fallback(live,tmp_path):
    active,_,_,_=live; db=PipelineDB(str(tmp_path/'test.sqlite'))
    none=freeze_task_product_decision(db,'manual:none',{'product_intent':'NONE'},active)
    assert none['attachment_version']!=MATCH_VERSION and not none['require_product']
    empty=freeze_task_product_decision(db,'new:empty',{'video_title':'unrelated giraffe'},active)
    assert empty['reason']=='MATCH_EMPTY' and empty['product_decision']['candidates']==[]
    assert execute_product_task(empty,EmptyPicker(),tmp_path/'empty',tmp_path/'status')
    assert finalize_product_before_submit(empty,EmptyPicker(),tmp_path/'empty')
    assert not finalize_product_before_submit(empty,EmptyPicker(),tmp_path/'empty',require_bound=True)
    active.with_name('wechat_product_matching.json').unlink()
    old=freeze_task_product_decision(db,'old',dict(youtube_id='youtube1234',view_count=100,like_count=1),active)
    assert old['reason']=='SKIP_BELOW_THRESHOLD'
    active.with_name('wechat_product_matching.json').write_text(json.dumps(dict(schema_version=1,enabled=True,min_score=4,themes={})))
    assert freeze_task_product_decision(db,'old',{'video_title':'stock market'},active)==old


def test_english_priority_requires_same_current_eligible_pool(live):
    active,_,config,_=live; pool=load_live_pool(active)
    ranked=rank_products({},pool,config,max_attempts=3,english=True)
    assert ranked['candidates'][0]['product_id']=='10000006971274'
    pool['eligible']=[p for p in pool['eligible'] if p['product_id']!='10000006971274']
    assert rank_products({},pool,config,max_attempts=3,english=True)['reason']=='MATCH_EMPTY'
    pool['ready']=False; pool['reason']='CATALOG_STALE'
    assert not rank_products({},pool,config,max_attempts=3,english=True)['candidates']


def test_slice_ass_excludes_glossary_and_parent_text(live,tmp_path):
    active,_,_,_=live; out=tmp_path/'output';out.mkdir()
    (out/'abc.ass').write_text('Dialogue: 0,0,1,Default,,0,0,0,,parent stock market')
    (out/'abc_s2.ass').write_text('Dialogue: 0,0,1,English,,0,0,0,,{\\c&HFFF&}slice\\Ndialogue\nDialogue: 0,0,1,Glossary,,0,0,0,,stock market\nDialogue: 0,0,1,Default,,0,0,0,,{\\p1}m 0 0')
    content=content_evidence(active,'pipeline:abc:2',{'youtube_id':'abc','slice_index':0})
    assert content['subtitle']=='slice dialogue' and len(content['sources'])==1
    english=content_evidence(active,'english:abc',{'youtube_id':'abc','content_type':'ENGLISH_WORLD_SHORT'})
    assert not english['subtitle'] and not english['sources']


def test_english_bound_segment_not_parent(live,tmp_path):
    active,_,_,_=live; directory=tmp_path/'segment';directory.mkdir()
    timeline=directory/'timeline.json';timeline.write_text(json.dumps({'headline_zh':'分片标题','english_text':'segment stock market','translation_zh':'分片股票'}))
    plan={'timeline_sha256':hashlib.sha256(timeline.read_bytes()).hexdigest()}
    (directory/'display_plan.json').write_text(json.dumps(plan))
    manifest=directory/'manifest.json';manifest.write_text(json.dumps({'timeline':str(timeline),'display_plan_sha256':digest(plan)}))
    context={'content_type':'ENGLISH_WORLD_SHORT','matching_manifest':{'path':str(manifest),'sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}}
    content=content_evidence(active,'english:1',context)
    assert content['title']=='分片标题' and 'segment stock market' in content['subtitle']
    timeline.write_text('{}')
    assert not content_evidence(active,'english:1',context)['subtitle']


def test_live_negative_veto_does_not_replace_frozen_candidate(live,tmp_path,monkeypatch):
    from video_processing.utils import wechat_product_collector
    active,_,_,_=live;db=PipelineDB(str(tmp_path/'test.sqlite'))
    task=freeze_task_product_decision(db,'auto',{'video_title':'stock market'},active)
    monkeypatch.setattr(settings,'wechat_product_policy_path',active)
    monkeypatch.setattr(wechat_product_collector,'read_public_account',lambda p: {'value':'different-account'})
    picker=EmptyPicker();picker.page=object()
    assert execute_product_task(task,picker,tmp_path/'e',tmp_path/'status')
    receipt=json.loads((tmp_path/'e/product_selection_receipt.json').read_text())
    assert receipt['state']=='UNBOUND' and receipt['attempts']==0
    assert receipt['catalog_digest']==task['matching_snapshot']['pool']['catalog_digest']
    assert receipt['matching_version']==MATCH_VERSION


def test_catalog_budget_independent_and_same_account_backoff(monkeypatch):
    monkeypatch.setattr(settings,'wechat_scheduler_priority_video','')
    now=200000.0; policy=dict(schema_version=1,operations=deepcopy(APPROVED),retry_policies={})
    row={'blocked_until':0,'schedule':{'sessions':[
        {'at':now-10-i,'purpose':'保活','operation':'keepalive','task':'old'} for i in range(16)]}}
    evaluate=lambda purpose: _evaluate_operations(row,now,purpose,'new',policy,compare_queue=False)
    assert evaluate('商品同步')['allowed'] and evaluate('商品同步')['daily_limit']==2
    row['schedule']['sessions'].append({'at':now-100,'purpose':'商品同步','operation':'catalog_sync','task':'sync'})
    assert 'OPERATION_INTERVAL' in {r['code'] for r in evaluate('商品同步')['blockers']}
    assert evaluate('发布')['allowed']
    row['schedule']['sessions']=[{'at':now-age,'purpose':'商品同步','operation':'catalog_sync','task':'sync'} for age in (22000,44000)]
    assert 'OPERATION_ROLLING_24H_LIMIT' in {r['code'] for r in evaluate('商品同步')['blockers']}
    row['blocked_until']=now+10
    assert 'PLATFORM_BACKOFF' in {r['code'] for r in evaluate('商品同步')['blockers']}
    assert len(policy['operations'])==6


def test_stale_freeze_refreshes_once_before_browser_and_never_renews_on_failure(live,tmp_path,monkeypatch):
    from video_processing.utils import wechat_product_sync
    from video_processing.core import wechat_session_lock
    active,doc,_,now=live
    path=active.with_name('wechat_product_catalog.json')
    doc['captured_at']=(now-timedelta(days=8)).isoformat();path.write_text(json.dumps(doc));before=path.read_bytes()
    calls=[]
    monkeypatch.setattr(settings,'wechat_product_policy_path',active)
    monkeypatch.setattr(wechat_product_sync,'run_catalog_sync',lambda p: calls.append(p) or {'reason':'BUDGET_DEFERRED'})
    monkeypatch.setattr(wechat_session_lock,'current_wechat_session',lambda: None)
    db=PipelineDB(str(tmp_path/'test.sqlite'))
    task=freeze_task_product_decision(db,'new',{'video_title':'stock market'},active)
    assert len(calls)==1 and task['reason']=='CATALOG_STALE' and not task['require_product']
    assert freeze_task_product_decision(db,'new',{},active)==task and len(calls)==1
    monkeypatch.setattr(wechat_session_lock,'current_wechat_session',lambda: object())
    deferred=freeze_task_product_decision(db,'other',{},active)
    assert deferred['matching_snapshot']['sync_result']['reason']=='SYNC_IN_PUBLISH_SESSION_DEFERRED'
    assert len(calls)==1 and path.read_bytes()==before


def test_sync_disabled_records_attempt_without_touching_catalog(live,tmp_path,monkeypatch):
    from video_processing.utils.wechat_product_sync import run_catalog_sync
    active,_,_,_=live; path=active.with_name('wechat_product_catalog.json');before=path.read_bytes()
    monkeypatch.setattr(settings,'wechat_operations_enabled',False)
    monkeypatch.setattr(type(settings),'default_output_dir',property(lambda _: tmp_path/'attempts'))
    result=run_catalog_sync(active)
    assert result['reason']=='CATALOG_OPERATIONS_DISABLED' and not result['live_verified']
    assert result['diagnostics']['browser']['launched'] is False
    assert result['diagnostics']['url_path'] is None and result['diagnostics']['observed_items']==0
    assert Path(result['receipt_path']).is_file()
    assert path.read_bytes()==before and len(list((tmp_path/'attempts').glob('wechat_catalog_sync/*/receipt.json')))==1

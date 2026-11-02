"""合成官方 URL 页面中的真实 Chromium 只读分页验收；无真实平台请求。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-11-02 | Codex | 初次延迟至少2秒、明确空态、未知结构等满预算；失败诊断脱敏与零业务写动作。 |
| 1.0.0 | 2026-11-02 | Codex | 分页完整性、库存/可售、账号/总数缺失、异步和预算；禁止选中/上传/发表。 |
"""
import pytest
import json
from time import monotonic
from pathlib import Path
from tests.browser_fixtures import chromium
from video_processing.utils.wechat_product_collector import collect_catalog, CatalogSyncError
from video_processing.utils.wechat_product_pool import validate_observation
from video_processing.utils.wechat_product_catalog import decode_catalog
from video_processing.utils.wechat_product_catalog import catalog_digest
from video_processing.utils.wechat_product_config import load_policy
from video_processing.utils.wechat_product_pool import promote_live_catalog, load_live_pool
from tests.unit.test_wechat_product_attachment_v2 import product_fixture


def html(*, account=True, total='共 3 件', bad_second=False, changing_account=False, slow=False):
    account_node='<div data-publisher-finder-username="publisher-verified">合成发布账号</div>' if account else ''
    return account_node+'''<div class="choosen-link-wrap">商品</div>
    <div class="post-component-choose-wrap"><div class="choose-content">选择需要添加的商品</div></div>
    <div role="dialog">从橱窗添加商品<table><thead><tr><th>商品</th><th>库存</th><th>价格</th><th>店铺</th><th>操作</th></tr></thead><tbody id="rows"></tbody></table>
    <span class="ant-pagination-total-text">'''+total+'''</span><span class="ant-pagination-item-active">1</span>
    <button title="下一页" onclick="nextPage()">下一页</button><button onclick="mutations++">添加</button></div>
    <input type="file" onchange="mutations++"><button onclick="mutations++">发表</button>
    <script>let mutations=0, flips=0;
    function row(id,title,stock,status,disabled=''){return `<tr><td><div class="id-wrap">${id}</div><div class="title" title="${title}">${title}</div></td><td>${stock}</td><td>20</td><td>合成店铺</td><td>${status}<input type="radio" ${disabled} onclick="mutations++"></td></tr>`;}
    document.querySelector('#rows').innerHTML=row('123','系统反馈回路','1,234','')+row('456','股票市场研究','0','已售罄','disabled');
    function nextPage(){flips++;'''+('document.querySelector("[data-publisher-finder-username]").setAttribute("data-publisher-finder-username","different");' if changing_account else '')+'''
       setTimeout(()=>{ document.querySelector('#rows').innerHTML=row('''+repr('123' if bad_second else '789')+''','英语阅读理解','--','可售卖');
       document.querySelector('.ant-pagination-item-active').innerText='2';
       document.querySelector('[title="下一页"]').setAttribute('disabled',''); },'''+('2000' if slow else '80')+'''); }
    </script>'''


@pytest.fixture
def page(chromium):
    context=chromium.new_context()
    page=context.new_page()
    yield page
    context.close()


def load(page, content, suffix=''):
    page.route('**/*', lambda route: route.fulfill(status=200,content_type='text/html; charset=utf-8',body=content))
    page.goto('https://channels.weixin.qq.com/platform/post/create' + suffix)


def test_read_only_complete_pagination_and_sale_states(page,tmp_path):
    load(page,html())
    document,proof=collect_catalog(page,timeout_seconds=8,max_pages=20)
    assert document['total_pages']==2 and document['total_items']==3
    _,catalog=decode_catalog(json.dumps(document).encode())
    states=validate_observation(dict(catalog,pages=document['pages']),proof)
    assert states['123']['stock']==1234 and states['123']['sale_state']=='AVAILABLE'
    assert states['456']['stock']==0 and states['456']['sale_state']=='UNAVAILABLE'
    assert states['789']['stock'] is None and states['789']['sale_state']=='AVAILABLE'
    assert page.evaluate('mutations')==0 and page.evaluate('flips')==1
    assert proof['read_only'] and proof['mutating_actions']==[]
    active=product_fixture(tmp_path);before=active.read_bytes()
    path=active.with_name('wechat_product_catalog.json');old_digest=catalog_digest(path)
    promote_live_catalog(document,proof,active,expected_catalog_digest=old_digest,expected_policy_digest=load_policy(active).digest)
    pool=load_live_pool(active)
    assert pool['live_verified'] and {p['product_id'] for p in pool['eligible']}=={'123','789'}
    assert pool['exclusion_counts']=={'OUT_OF_STOCK':1}
    assert active.read_bytes()==before
    assert (tmp_path/'wechat_product_catalog_history'/(old_digest+'.json')).exists()


@pytest.mark.parametrize('options,reason', [({'account':False},'CATALOG_ACCOUNT_UNVERIFIED'),
    ({'total':''},'CATALOG_TOTAL_UNVERIFIED'),({'total':'共 4 件'},'CATALOG_COUNT_MISMATCH'),
    ({'bad_second':True},'CATALOG_DUPLICATE_OR_MISSING_ID'),({'changing_account':True},'CATALOG_ACCOUNT_UNVERIFIED')])
def test_partial_cannot_claim_complete(page,options,reason):
    load(page,html(**options))
    with pytest.raises(CatalogSyncError,match=reason): collect_catalog(page,timeout_seconds=8)
    assert page.evaluate('mutations')==0


def test_page_budget_is_not_extended(page):
    load(page,html())
    with pytest.raises(CatalogSyncError,match='CATALOG_PAGE_BUDGET'):
        collect_catalog(page,timeout_seconds=3,max_pages=1)
    assert page.evaluate('mutations')==0


def test_loading_cannot_renew_timeout_or_complete_on_old_rows(page):
    load(page,html(slow=True))
    with pytest.raises((CatalogSyncError,TimeoutError)):
        collect_catalog(page,timeout_seconds=.3)
    assert page.evaluate('mutations')==0


def test_pagination_actionability_timeout_preserves_diagnostics(page):
    load(page,html()+ '<div style="position:fixed;inset:0;z-index:9999"></div>')
    with pytest.raises(CatalogSyncError,match='CATALOG_SYNC_TIMEOUT') as error:
        collect_catalog(page,timeout_seconds=1.2)
    diagnostic=error.value.diagnostics
    assert diagnostic['last_phase']=='pagination'
    assert diagnostic['snapshot']['state']=='READY'
    assert diagnostic['snapshot']['row_count']==2
    assert diagnostic['timings_seconds']['pagination'] > .5
    assert page.evaluate('mutations')==0 and page.evaluate('flips')==0


def delayed_html(delay=2200):
    # 删除整个 table，避免测试只覆盖有表但无行的另一条路径。
    return html().replace('</script>', '''
    const table=document.querySelector('table'), marker=document.createComment('table');
    table.replaceWith(marker);setTimeout(()=>marker.replaceWith(table),'''+str(delay)+''');
    </script>''')


def test_first_table_delayed_over_two_seconds_is_not_empty(page):
    load(page,delayed_html())
    started=monotonic(); diagnostics={}
    document,_=collect_catalog(page,timeout_seconds=4,diagnostics=diagnostics)
    assert monotonic()-started >= 2
    assert document['total_items']==3
    assert diagnostics['snapshot']['state']=='READY'
    assert diagnostics['snapshot']['dialog_count']==1
    assert diagnostics['snapshot']['visible_table_count']==1
    assert diagnostics['snapshot']['id_wrap_count']==1  # 最后一页
    assert diagnostics['snapshot']['headers']==['商品','库存','价格','店铺','操作']
    assert diagnostics['timings_seconds']['collection'] >= 2
    assert page.evaluate('mutations')==0


@pytest.mark.parametrize('body,reason,state,min_elapsed', [
    ('<div class="ant-empty-description">暂无商品</div>', 'CATALOG_EMPTY_CONFIRMED','EMPTY_CONFIRMED',0),
    ('<div>陌生的新结构</div><div class="pagination-wrap" style="display:none"></div>', 'CATALOG_UNSUPPORTED','UNSUPPORTED',.5),
])
def test_empty_and_unrecognized_structure_are_distinct_and_read_only(page,body,reason,state,min_elapsed):
    content='''<div class="post-component-choose-wrap">选择需要添加的商品</div>
      <div role="dialog">从橱窗添加商品'''+body+'''<div class="hint">token=PRIVATE_CANARY</div>
      <button onclick="mutations++">添加</button><input type="radio" onclick="mutations++"></div>
      <input type="file" onchange="mutations++"><button onclick="mutations++">保存草稿</button>
      <button onclick="mutations++">发表</button><script>let mutations=0;</script>'''
    load(page,content,'?token=PRIVATE_CANARY#PRIVATE_CANARY')
    started=monotonic()
    with pytest.raises(CatalogSyncError,match=reason) as error:
        collect_catalog(page,timeout_seconds=.6)
    diagnostics=error.value.diagnostics
    assert monotonic()-started >= min_elapsed
    assert diagnostics['snapshot']['state']==state
    assert diagnostics['snapshot']['dialog_count']==1
    assert diagnostics['snapshot']['visible_table_count']==0
    assert diagnostics['snapshot']['row_count']==0
    assert diagnostics['snapshot']['id_wrap_count']==0
    assert len(diagnostics['snapshot']['pagination_nodes']) >= 5
    if state=='UNSUPPORTED':
        assert diagnostics['snapshot']['pagination_nodes'][0]=={'selector':'.pagination-wrap','count':1,'visible_count':0,'texts':[]}
    assert all(n['count']==0 for n in diagnostics['account_nodes'])
    assert diagnostics['url_path']=='/platform/post/create'
    assert diagnostics['timings_seconds']['collection'] >= min_elapsed
    assert 'PRIVATE_CANARY' not in json.dumps(diagnostics)
    assert page.evaluate('mutations')==0


def test_transient_empty_under_spinner_does_not_end_collection(page):
    content=delayed_html().replace('从橱窗添加商品<table>', '从橱窗添加商品<div class="ant-spin-spinning">加载中</div><div class="ant-empty-description">暂无商品</div><table>')
    content=content.replace('</script>', "setTimeout(()=>{document.querySelector('.ant-spin-spinning').remove();document.querySelector('.ant-empty-description').remove()},2100);</script>")
    load(page,content)
    assert collect_catalog(page,timeout_seconds=4)[0]['total_items']==3
    assert page.evaluate('mutations')==0


def test_stored_public_dialog_has_rows_but_no_explicit_total(page):
    fixture=Path(__file__).resolve().parents[1]/'fixtures/wechat_catalog_public_dialog_20261010.html'
    load(page,fixture.read_text() + '''<script>let mutations=0;
      document.addEventListener('click',e=>{if(e.target.closest('input[type=radio],button')) mutations++},true);
      document.addEventListener('change',()=>mutations++,true);</script>''')
    with pytest.raises(CatalogSyncError,match='CATALOG_ACCOUNT_UNVERIFIED') as error:
        collect_catalog(page,timeout_seconds=8)
    diagnostic=error.value.diagnostics
    assert error.value.partial['observed_items']==14
    assert diagnostic['snapshot']['headers']==['','商品信息','商品来源','价格','库存','']
    assert diagnostic['snapshot']['row_count']==14
    assert diagnostic['snapshot']['id_wrap_count']==14
    # 原完整 frame 的唯一 pagination-wrap 属于其他弹窗，不能借作商品完整性证据。
    assert all(n['count']==0 for n in diagnostic['snapshot']['pagination_nodes'])
    assert diagnostic['account_id_observed'] is False and diagnostic['total_verified'] is False
    assert all(n['count']==0 for n in diagnostic['snapshot']['total_nodes'])
    assert page.evaluate('mutations')==0

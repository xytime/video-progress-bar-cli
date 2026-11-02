"""合成官方 URL 页面中的真实 Chromium 只读分页验收；无真实平台请求。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 分页完整性、库存/可售、账号/总数缺失、异步和预算；禁止选中/上传/发表。 |
"""
import pytest
import json
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


def load(page, content):
    page.route('**/*', lambda route: route.fulfill(status=200,content_type='text/html; charset=utf-8',body=content))
    page.goto('https://channels.weixin.qq.com/platform/post/create')


def test_read_only_complete_pagination_and_sale_states(page,tmp_path):
    load(page,html())
    document,proof=collect_catalog(page,timeout_seconds=3,max_pages=20)
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
    with pytest.raises(CatalogSyncError,match=reason): collect_catalog(page,timeout_seconds=3)
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

"""公开滚动表与首页稳定账号的离线 Chromium 验证，不访问真实平台。"""
import json
from pathlib import Path
import pytest
from tests.browser_fixtures import chromium
from tests.browser.test_wechat_product_catalog_browser import page, load
from video_processing.utils.wechat_product_collector import collect_catalog, CatalogSyncError
from video_processing.utils.wechat_catalog_account import read_home_id, visit_home_account
from video_processing.utils.wechat_product_pool import validate_observation
from video_processing.utils.wechat_product_catalog import decode_catalog


def content(extra='', script=''):
    return '''<div data-publisher-finder-username="test-account">测试账号</div>
    <div class="post-component-choose-wrap">选择需要添加的商品</div>
    <div role="dialog">从橱窗添加商品'''+extra+'''
    <div class="ant-table-wrapper"><div class="ant-table-header"><table><thead><tr>
    <th>商品信息</th><th>价格</th><th>库存</th><th>选择</th></tr></thead></table></div>
    <div class="ant-table-body" style="height:90px;overflow-y:scroll"><table><tbody></tbody></table></div></div>
    <div class="common-table-loading" style="display:none">加载中</div>
    <button onclick="mutations++">添加</button></div>
    <input type="file" onchange="mutations++"><button onclick="mutations++">发表</button>
    <script>let mutations=0;
    function row(id){return `<tr style="height:42px"><td><span class="id-wrap">${id}</span><span class="title">商品${id}</span></td><td>20</td><td>999</td><td><input type="radio" onclick="mutations++"></td></tr>`}
    document.querySelector('tbody').innerHTML=[1,2,3,4].map(row).join('');
    '''+script+'''</script>'''


def test_split_header_scroll_collects_without_platform_total(page):
    load(page,content())
    data,proof=collect_catalog(page,timeout_seconds=8)
    assert data['total_items']==4
    assert all(i['stock']==999 and i['price']=='20' for i in data['pages'][0]['items'])
    assert proof['completeness_evidence']['kind']=='PUBLIC_DOM_SCROLL_ENUMERATION'
    assert proof['completeness_evidence']['explicit_total'] is False
    _,catalog=decode_catalog(json.dumps(data).encode())
    assert len(validate_observation(catalog,proof))==4
    proof['completeness_evidence']['identity_digest']='forged'
    with pytest.raises(ValueError):validate_observation(catalog,proof)
    assert page.evaluate('mutations')==0


def test_scroll_waits_for_delayed_loading_and_reenumerates(page):
    load(page,content(script='''let loaded=false;const b=document.querySelector('.ant-table-body');
    b.addEventListener('scroll',()=>{if(!loaded && b.scrollTop+b.clientHeight>=b.scrollHeight-2){loaded=true;
      document.querySelector('.common-table-loading').style.display='block';
      setTimeout(()=>{document.querySelector('tbody').innerHTML+=row(5)+row(6);
        document.querySelector('.common-table-loading').style.display='none'},1600);}});'''))
    data,_=collect_catalog(page,timeout_seconds=12)
    assert data['total_items']==6
    assert page.evaluate('mutations')==0


@pytest.mark.parametrize('extra', ['<input value="筛选词">','<div class="rc-virtual-list"></div>',
    '<span class="weui-desktop-dropdown__list-ele checked">某店铺</span>'])
def test_unknown_virtual_or_filtered_list_cannot_claim_complete(page,extra):
    load(page,content(extra))
    with pytest.raises(CatalogSyncError,match='CATALOG_TOTAL_UNVERIFIED'):
        collect_catalog(page,timeout_seconds=4)
    assert page.evaluate('mutations')==0


def test_scroll_step_budget_not_extended(page):
    load(page,content())
    with pytest.raises(CatalogSyncError,match='CATALOG_PAGE_BUDGET'):
        collect_catalog(page,timeout_seconds=8,max_pages=1)
    assert page.evaluate('mutations')==0


def test_changes_between_scroll_rounds_fail_closed(page):
    load(page,content(script='''let down=false;const b=document.querySelector('.ant-table-body');
    b.addEventListener('scroll',()=>{if(b.scrollTop>0)down=true;else if(down)document.querySelector('.title').textContent='已变更';});'''))
    with pytest.raises(CatalogSyncError,match='CATALOG_ENUMERATION_CHANGED'):
        collect_catalog(page,timeout_seconds=8)


HOME='''<a class="finder-ui-desktop-menu__link" onclick="document.querySelector('.finder-uniq-id-wrap').style.display='block'">首页</a>
<div class="finder-uniq-id-wrap" style="display:none">视频号ID:
<span class="finder-uniq-id" data-clipboard-text="sphTEST123456">sphTEST123456</span></div>'''


def test_public_home_id_requires_label_visible_and_double_read(page):
    load(page,HOME)
    assert read_home_id(page) is None
    diagnostics={}
    evidence=visit_home_account(page,timeout_ms=500,diagnostics=diagnostics)
    assert evidence['value']=='sphTEST123456'
    assert diagnostics['stable_id_observed']
    page.locator('.finder-uniq-id').evaluate("e=>e.textContent='sphDIFFERENT'")
    assert read_home_id(page) is None


def test_home_id_attestation_requires_before_after(page):
    load(page,content())
    data,proof=collect_catalog(page,timeout_seconds=8)
    _,catalog=decode_catalog(json.dumps(data).encode())
    evidence={'kind':'PUBLIC_DOM_STABLE_ID','value':catalog['account_id'], 'selector':'.finder-uniq-id', 'attribute':'data-clipboard-text'}
    proof['account_evidence']=evidence
    with pytest.raises(ValueError,match='前后核对'): validate_observation(catalog,proof)
    proof['account_checks']={'before':evidence,'after':evidence}
    assert len(validate_observation(catalog,proof))==4


def test_home_closes_only_cancel_and_never_adds_product(page):
    load(page, HOME + '<div role="dialog">从橱窗添加商品<button onclick="writes++">添加</button><input type="radio" onclick="writes++"><button onclick="this.closest(\'[role=dialog]\').remove()">取消</button></div><script>let writes=0</script>')
    diagnostics = {}
    assert visit_home_account(page, timeout_ms=1500, diagnostics=diagnostics)['value']=='sphTEST123456'
    assert diagnostics['dialog_close']=='CANCELLED_WITHOUT_SELECTION'
    assert page.evaluate('writes')==0


def test_home_provenance_fixture(page):
    fixture = Path(__file__).resolve().parents[1]/'fixtures/wechat_catalog_home_identity_20260523.html'
    load(page, fixture.read_text())
    evidence = read_home_id(page)
    assert evidence['value']=='sphTEST123456'
    page.locator('.finder-uniq-id-wrap').evaluate("e=>e.firstChild.textContent='昵称:'")
    assert read_home_id(page) is None


def test_account_after_change_rejects_attestation(page):
    load(page, content())
    data, proof = collect_catalog(page, timeout_seconds=8)
    _, catalog = decode_catalog(json.dumps(data).encode())
    before={'kind':'PUBLIC_DOM_STABLE_ID','value':catalog['account_id'], 'selector':'.finder-uniq-id', 'attribute':'data-clipboard-text'}
    proof['account_evidence']=before
    proof['account_checks']={'before':before,'after':dict(before,value='sphCHANGED')}
    with pytest.raises(ValueError,match='前后核对'): validate_observation(catalog,proof)

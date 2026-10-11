"""只在合成 DOM 中验证真实 Chromium 行为，不访问视频号或复用登录态。"""
import time
import pytest
from tests.browser_fixtures import chromium
from video_processing.core.wechat_product_policy import ProductIdentity, ProductLookup, ProductDecision, ProductRole
from video_processing.utils.wechat_product_picker import PlaywrightProductPicker, BindingIdentityUnavailable
from video_processing.utils.wechat_product_selection import select_required_product

TARGET=ProductIdentity('123','完整图书版本')
DEFAULT=ProductIdentity('456','默认图书')

@pytest.fixture
def page(chromium):
    context=chromium.new_context()
    context.route('**/*', lambda route: route.abort())
    page=context.new_page()
    yield page
    context.close()


def card(identifier='123',title='完整图书版本'):
    return f'<div class="post-component-choose-wrap"><div class="choose-content" data-product-id="{identifier}"><span class="name">{title}</span></div></div><button>发表</button>'


def row(identifier='123',title='完整图书版本',disabled=''):
    return f'<tr><td>{identifier}</td><td>{title}</td><td><input type="radio" name="book" {disabled}></td></tr>'


def form(rows):
    return '''<div class="choosen-link-wrap">商品</div>
    <div class="post-component-choose-wrap"><div class="choose-content">选择需要添加的商品</div><button class="close-icon" onclick="document.querySelector('.choose-content').outerHTML='<div class=choose-content>选择需要添加的商品</div>'">移除</button></div>
    <div role="dialog" id="products">从橱窗添加商品<table>'''+rows+'''</table><button id="add" onclick="addProduct()">添加(1)</button><button onclick="this.parentElement.hidden=true">取消</button></div>
    <div role="dialog" id="timing" hidden>选择商品出现时机<button onclick="confirmProduct()">确认</button></div><button>发表</button>
    <script>
    let selected;
    function addProduct(){ selected=document.querySelector('input:checked').closest('tr'); document.querySelector('#products').hidden=true; document.querySelector('#timing').hidden=false; }
    function confirmProduct(){
      const id=selected.cells[0].innerText, title=selected.cells[1].innerText;
      document.querySelector('.choose-content').outerHTML=`<div class="choose-content" data-product-id="${id}"><span class="name">${title}</span></div>`;
      document.querySelector('#timing').hidden=true;
    }
    document.querySelector('.choose-content').onclick=()=>document.querySelector('#products').hidden=false;
    </script>'''


def test_actual_binding_id_never_inferred_from_same_title(page):
    page.set_content(card('999'))
    picker=PlaywrightProductPicker(page)
    assert picker.read_binding(timeout_ms=500)==ProductIdentity('999',TARGET.title)
    decision=ProductDecision(ProductRole.DEFAULT,'test',candidates=(TARGET,))
    result=select_required_product(decision=decision,picker=picker)
    assert result.reason=='EXISTING_LINK_CONFLICT'


@pytest.mark.parametrize('html',[card(''), '<button>发表</button>',card().replace('data-product-id="123"','data-product-id="123"><a href="https://example.invalid/?product_id=999"></a><span')])
def test_unknown_identity_blocks(page,html):
    page.set_content(html)
    with pytest.raises(BindingIdentityUnavailable):
        PlaywrightProductPicker(page).read_binding(timeout_ms=500)


def test_binding_from_actual_product_link(page):
    page.set_content(card('').replace('<span class="name">','<a href="https://example.invalid/item?product_id=123">商品</a><span class="name">'))
    assert PlaywrightProductPicker(page).read_binding(timeout_ms=500)==TARGET


@pytest.mark.parametrize('rows,status',[(row('91234'),ProductLookup.UNAVAILABLE),(row(title='其他版本'),ProductLookup.IDENTITY_CONFLICT),(row()+row(),ProductLookup.IDENTITY_CONFLICT),(row(disabled='disabled'),ProductLookup.UNAVAILABLE),(row(),ProductLookup.AVAILABLE)])
def test_exact_row_identity_and_availability(page,rows,status):
    page.set_content(form(rows))
    assert PlaywrightProductPicker(page).find(TARGET,timeout_ms=500)==status


def test_complete_flow_and_timing_confirmation(page):
    page.set_content(form(row()+row('456','默认图书')))
    picker=PlaywrightProductPicker(page)
    decision=ProductDecision(ProductRole.FINANCE,'test',candidates=(TARGET,DEFAULT))
    result=select_required_product(decision=decision,picker=picker,timeout_seconds=3)
    assert result.binding_confirmed and result.actual==TARGET
    assert picker.cancel_and_clear(timeout_ms=500)
    assert picker.read_binding(timeout_ms=500) is None


def test_unavailable_target_cleared_then_default(page):
    page.set_content(form(row('456','默认图书')))
    result=select_required_product(decision=ProductDecision(ProductRole.FINANCE,'test',candidates=(TARGET,DEFAULT)),picker=PlaywrightProductPicker(page),timeout_seconds=3)
    assert result.binding_confirmed and result.actual==DEFAULT
    assert result.fallback_reason=='TARGET_UNAVAILABLE'


def test_hidden_and_unrelated_dialog_rows_ignored(page):
    page.set_content(form(row())+'<div role="dialog" hidden>从橱窗添加商品<table>'+row()+'</table></div><div role="dialog">其他<table>'+row()+'</table></div>')
    assert PlaywrightProductPicker(page).find(TARGET,timeout_ms=500)==ProductLookup.AVAILABLE


def test_frame_opening_uses_same_frame(page):
    page.set_content('<iframe name="content"></iframe>')
    frame=page.frame(name='content'); frame.set_content(form(row()))
    frame.locator('#products').evaluate('(e)=>e.hidden=true')
    picker=PlaywrightProductPicker(page)
    assert picker.find(TARGET,timeout_ms=500)==ProductLookup.AVAILABLE
    picker.select(TARGET,timeout_ms=500)
    assert picker.read_binding(timeout_ms=500)==TARGET


def test_disabled_publish_button_not_ready(page):
    page.set_content(card().replace('<button>','<button disabled>'))
    assert not PlaywrightProductPicker(page).ready_to_submit(timeout_ms=500)


def test_short_timeout_is_not_expanded_by_fixed_waits(page):
    page.set_content(form(row()))
    page.locator('#add').evaluate('(e)=>e.onclick=()=>{}')
    start=time.monotonic()
    with pytest.raises(TimeoutError):
        PlaywrightProductPicker(page).select(TARGET,timeout_ms=100)
    assert time.monotonic()-start < 0.6


def test_real_playwright_timeout_recoverable_within_total_budget(page):
    page.set_content(form(row()))
    page.locator('#products').evaluate('(e)=>e.hidden=true')
    page.locator('.choose-content').evaluate('(e)=>e.onclick=null')
    with pytest.raises(TimeoutError):
        PlaywrightProductPicker(page).find(TARGET,timeout_ms=100)


def searched_form(results):
    # 公开历史 DOM 控件和商品 ID span；radio.value/data-row-key 与商品 ID 故意不同。
    source=form(row('999','第一页其他图书'))
    controls='''<input placeholder="请输入商品名称/编码搜索"><button ml-key="filter_btn" onclick="filterProducts()">筛选</button>'''
    source=source.replace('从橱窗添加商品<table>','从橱窗添加商品'+controls+'<div id="loading" class="ant-spin-spinning" hidden></div><div id="empty" class="ant-empty" hidden>暂无数据</div><table>')
    return source+'''<script>
    const filteredRows='''+repr(results)+''';
    function filterProducts(){
      const loading=document.querySelector('#loading');loading.hidden=false;
      setTimeout(()=>{document.querySelector('#products table').innerHTML=filteredRows;
        document.querySelector('#empty').hidden=!!filteredRows;loading.hidden=true;}, 100);
    }
    </script>'''


@pytest.mark.parametrize('result,status', [
    ('<tr data-row-key="888"><td><span class="id-wrap" id="id-123">123</span></td><td class="title">完整图书版本</td><td><input type="radio" name="book" value="888"></td></tr>',ProductLookup.AVAILABLE),
    ('',ProductLookup.UNAVAILABLE),
    (row()+row(),ProductLookup.IDENTITY_CONFLICT),
    (row(title='相同ID不同版本'),ProductLookup.IDENTITY_CONFLICT),
    (row(disabled='disabled'),ProductLookup.UNAVAILABLE)])
def test_native_exact_id_search_cross_page_empty_and_conflict(page,result,status):
    page.set_content(searched_form(result))
    picker=PlaywrightProductPicker(page)
    assert picker.find(TARGET,timeout_ms=1800)==status
    assert page.get_by_placeholder('请输入商品名称/编码搜索').input_value()=='123'
    if status==ProductLookup.AVAILABLE:
        picker.select(TARGET,timeout_ms=1000)
        assert picker.read_binding(timeout_ms=500)==TARGET

"""只在合成 DOM 中验证真实 Chromium 行为，不访问视频号或复用登录态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Codex | 覆盖隐藏同名 iframe 与公开 Shadow DOM 的完整选品及多根冲突。 |
"""
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


@pytest.mark.parametrize('initial,final,allowed', [(True,True,True),(False,False,True),(True,False,False),(False,True,False)])
def test_final_dom_binding_matches_receipt_before_submission(page,tmp_path,initial,final,allowed):
    from video_processing.utils.wechat_product_config import atomic_json
    from video_processing.utils.wechat_product_execution import finalize_product_before_submit
    page.set_content(card() if initial else form(''))
    if not initial:page.locator('#products').evaluate('(node)=>node.hidden=true')
    evidence=tmp_path/'e';evidence.mkdir()
    atomic_json(evidence/'product_selection_receipt.json',dict(required=True,state='BOUND' if initial else 'UNBOUND',
        binding_confirmed=initial,unbound_confirmed=not initial,
        actual_product_id=TARGET.product_id if initial else None,actual_title=TARGET.title if initial else None))
    page.set_content(card() if final else form(''))
    if not final:page.locator('#products').evaluate('(node)=>node.hidden=true')
    assert finalize_product_before_submit(None,PlaywrightProductPicker(page),evidence) is allowed
    assert (evidence/'product_pre_submit_readback.json').exists() is allowed


@pytest.mark.parametrize('case', ['unbound','bound','wrong_work','error','duplicate'])
def test_same_work_native_detail_readback_is_read_only(page,tmp_path,case):
    import json
    from scripts.wechat_uploader import _read_management_product_detail
    payload=dict(errCode=0,data=dict(object=dict(objectId='native-current',objectNonce='12345',desc=dict(
        media=[dict(videoPlayLen=32)],description='原生描述',shortTitle=[dict(shortTitle='原生标题')],extReading={},modFeedInfo={}))))
    if case=='bound':payload['data']['object']['desc']['product']=dict(productId='123',title=TARGET.title)
    if case=='wrong_work':payload['data']['object']['objectId']='other-work'
    if case=='error':payload['errCode']=1
    page.route('**/post/get_post_info',lambda route:route.fulfill(json=payload,headers={'Access-Control-Allow-Origin':'*'}))
    row='''<div class="post-feed-item"><div class="edit-cover-item"><button class="opr-item" onclick="fetch('https://fixture.test/post/get_post_info')">修改描述和封面</button></div></div>'''
    page.set_content(row*(2 if case=='duplicate' else 1)+'''<button id="save" onclick="window.saved=true">完成</button>
        <script>window.saved=false;for(const n of document.querySelectorAll('.post-feed-item'))n.__vue__={$props:{post:{objectId:'native-current',objectNonce:'12345'}}};</script>''')
    result=_read_management_product_detail(page,tmp_path,dict(platform_post_id='native-current',platform_object_nonce='12345'))
    assert result['state']==('BOUND' if case=='bound' else 'UNBOUND' if case=='unbound' else 'UNVERIFIED')
    assert page.evaluate('window.saved') is False


def test_hidden_legacy_frame_and_shadow_form_complete_binding(page):
    page.set_content('<iframe name="content" hidden></iframe><wujie-app></wujie-app>')
    page.frame(name='content').set_content(card('999','旧页面图书'))
    page.evaluate("""html => {
        const scope = document.querySelector('wujie-app').attachShadow({mode:'open'});
        scope.innerHTML = '<body>' + html.replaceAll('document.querySelector', 'window.fixtureRoot.querySelector') + '</body>';
        window.fixtureRoot = scope;
        window.eval(scope.querySelector('script').textContent.replaceAll('document.querySelector', 'window.fixtureRoot.querySelector').replace('let selected;', 'window.selected = null;'));
        scope.querySelector('#products').hidden = true;
    }""", form(row()))
    picker = PlaywrightProductPicker(page)
    assert picker.find(TARGET,timeout_ms=1200) == ProductLookup.AVAILABLE
    picker.select(TARGET,timeout_ms=1200)
    assert picker.read_binding(timeout_ms=500) == TARGET
    assert picker.ready_to_submit(timeout_ms=500)
    assert picker.cancel_and_clear(timeout_ms=500)
    assert picker.read_binding(timeout_ms=500) is None


def test_multiple_visible_shadow_product_roots_block(page):
    page.set_content('<wujie-app></wujie-app><wujie-app></wujie-app>')
    page.evaluate('html => document.querySelectorAll("wujie-app").forEach(h => h.attachShadow({mode:"open"}).innerHTML = html)',card())
    with pytest.raises(BindingIdentityUnavailable, match='PRODUCT_VISIBLE_ROOT_CONFLICT'):
        PlaywrightProductPicker(page).read_binding(timeout_ms=500)


def idless_form():
    return form(row()).replace('data-product-id="${id}"','')


def test_binding_id_from_actual_selected_row_with_unchanged_idless_card(page):
    page.set_content(idless_form())
    picker=PlaywrightProductPicker(page)
    picker.select(TARGET,timeout_ms=800)
    assert page.locator('.choose-content').get_attribute('data-product-id') is None
    assert picker.read_binding(timeout_ms=500) == TARGET
    assert picker.binding_identity_source == 'DOM_SELECTION_AND_UNCHANGED_FORM'
    assert picker.ready_to_submit(timeout_ms=500)
    assert picker.read_binding(timeout_ms=500) == TARGET


@pytest.mark.parametrize('mutation', ['replace','same_text_write','reopen'])
def test_idless_card_attestation_invalidated_by_product_changes(page,mutation):
    page.set_content(idless_form())
    picker=PlaywrightProductPicker(page)
    picker.select(TARGET,timeout_ms=800)
    if mutation=='replace':
        page.locator('.choose-content').evaluate('e => e.outerHTML=e.outerHTML')
    elif mutation=='same_text_write':
        page.locator('.name').evaluate('e => e.textContent=e.textContent')
    else:
        page.locator('.choose-content').click()
    with pytest.raises(BindingIdentityUnavailable):
        picker.read_binding(timeout_ms=500)


def test_same_title_different_selected_id_not_inferred_from_configuration(page):
    page.set_content(form(row('999')).replace('data-product-id="${id}"',''))
    picker=PlaywrightProductPicker(page)
    with pytest.raises(BindingIdentityUnavailable):
        picker.select(TARGET,timeout_ms=500)
    picker.select(ProductIdentity('999',TARGET.title),timeout_ms=800)
    assert picker.read_binding(timeout_ms=500) == ProductIdentity('999',TARGET.title)


def test_final_idless_binding_proof_requires_same_selection_session(page,tmp_path):
    import json
    from video_processing.utils.wechat_product_execution import finalize_product_before_submit
    page.set_content(idless_form())
    picker=PlaywrightProductPicker(page)
    picker.select(TARGET,timeout_ms=800)
    (tmp_path/'product_selection_receipt.json').write_text(json.dumps(dict(state='BOUND',
        binding_confirmed=True,unbound_confirmed=False,actual_product_id=TARGET.product_id,actual_title=TARGET.title)))
    assert finalize_product_before_submit(None,picker,tmp_path,require_bound=True)
    evidence=json.loads((tmp_path/'product_pre_submit_readback.json').read_text())
    assert evidence['identity_source']=='DOM_SELECTION_AND_UNCHANGED_FORM'
    assert evidence['binding_required'] is True
    assert not finalize_product_before_submit(None,PlaywrightProductPicker(page),tmp_path,require_bound=True)

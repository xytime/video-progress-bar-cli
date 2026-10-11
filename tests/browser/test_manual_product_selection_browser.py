"""真实 Chromium 验证手动商品入口；HTTP 夹具只验证前端，不冒充平台挂载。"""
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, TimeoutError as PlaywrightTimeoutError

from tests.browser_fixtures import chromium, TEMPLATE, STATIC_DIR, STATIC_CONTENT_TYPES, _payload, _video


@pytest.fixture
def manual_ui(chromium):
    page = chromium.new_page(viewport={'width':1280,'height':900})
    state = {'writes':[], 'errors':[], 'hold_catalog':False, 'catalog_failure':False,
             'hold_add':False, 'add_failure':False, 'duplicate':False, 'payload':_payload([], total=0)}
    state['catalog'] = {
        'account_id':'account-test', 'captured_at':'2026-10-11T01:00:00Z',
        'source':'可靠导入清单', 'completeness':'完整性已校验，非实时同步', 'live_verified':False,
        'products':[
            {'alias':'unconfigured','product_id':'70001001','title':'未被类型规则引用的可靠图书：完整长书名与版本',
             'shop':'快捷英语教辅图书','selectable':True,'reason':''},
            {'alias':'finance','product_id':'70001002','title':'股市技术分析（完整版本）','shop':'另一店铺','selectable':True,'reason':''},
            {'alias':'unverified','product_id':'70001003','title':'待核验图书','shop':'快捷英语教辅图书','selectable':False,'reason':'账号未核实'},
        ]}
    page.on('pageerror', lambda error:state['errors'].append(str(error)))

    def add_response(route):
        if state['add_failure']:
            route.fulfill(status=422,json={'detail':'所选商品已失效，请重新选择'}); return
        if state['duplicate']:
            route.fulfill(json={'success':False,'already_exists':True,'error':'视频已有任务，保留原商品意图'}); return
        chosen = state['writes'][-1]
        product = next((p for p in state['catalog']['products'] if p['alias']==chosen['product_alias']),None)
        video = dict(_video('manual-video'), product_intent=chosen['product_intent'],
                     product_id=product['product_id'] if product else None,
                     product_title=product['title'] if product else None,
                     product_decision={'reason':'ATTACH_MANUAL' if product else 'SKIP_MANUAL_NONE'})
        state['payload'] = _payload([video], total=1)
        route.fulfill(json={'success':True,'title':'测试入队视频','channel_name':'测试频道'})

    def route_handler(route):
        req = route.request; path = urlparse(req.url).path
        if req.is_navigation_request():
            route.fulfill(content_type='text/html',body=TEMPLATE.read_text()); return
        if path.startswith('/static/'):
            file = (STATIC_DIR / path.removeprefix('/static/')).resolve()
            if file.is_file() and file.is_relative_to(STATIC_DIR.resolve()):
                route.fulfill(content_type=STATIC_CONTENT_TYPES.get(file.suffix,'text/plain'),body=file.read_bytes())
            else: route.fulfill(status=404,body='Not Found')
            return
        if path == '/api/products/manual-options':
            if state['hold_catalog']: state['catalog_route']=route; return
            if state['catalog_failure']: route.fulfill(status=503,json={'detail':'暂不可用'}); return
            route.fulfill(json=state['catalog']); return
        if path == '/api/videos/add':
            state['writes'].append(req.post_data_json)
            if state['hold_add']: state['add_route']=route; return
            add_response(route); return
        if path == '/api/videos': route.fulfill(json=state['payload']); return
        if path == '/api/stats':
            route.fulfill(json={'total':0,'pending':0,'active':0,'published':0,'failed':0,'breakdown':{},'server_time':'测试'}); return
        if path == '/api/channels': route.fulfill(json={'approved':[],'total_approved':0}); return
        route.fulfill(json={'success':True,'platforms':{}})

    page.route('**/*',route_handler)
    # 各测试可在首次加载前设定慢响应或失败；不以脚本注入操作绕过用户控件。
    state['navigate'] = lambda:page.goto('http://manual-test.invalid/',wait_until='domcontentloaded')
    state['release_add'] = lambda:add_response(state.pop('add_route'))
    yield page,state
    page.close()
    assert state['errors']==[]


def choose(page, alias, query=''):
    page.locator('#video-product-picker').click()
    if query: page.locator('#picker-search').fill(query)
    page.locator('#picker-list').select_option(alias)
    page.locator('.picker-apply').click()


def fill_video(page):
    page.locator('#video-url-input').fill('https://youtu.be/manualvideo')
    page.locator('#enable-trim-checkbox').check()
    page.locator('#video-trim-start').fill('00:00:10')
    page.locator('#video-trim-end').fill('00:01:10')
    page.locator('#video-content-type').select_option('ENGLISH_WORLD_SHORT')


def test_defaults_none_and_success_resets_all_inputs(manual_ui):
    page,state=manual_ui;state['navigate']()
    expect(page.locator('#video-product-picker')).to_be_enabled()
    fill_video(page)
    page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('不绑定商品')
    assert state['writes']==[{'url':'https://youtu.be/manualvideo','trim_start':'00:00:10',
        'trim_end':'00:01:10','content_type':'ENGLISH_WORLD_SHORT','product_intent':'NONE','product_alias':None}]
    expect(page.locator('#video-url-input')).to_have_value('')
    expect(page.locator('#video-product')).to_have_value('')
    expect(page.locator('#video-content-type')).to_have_value('GENERAL')
    page.locator('#tab-queue').click()
    expect(page.locator('#row-manual-video .product-intent-detail')).to_contain_text('手动明确不绑定商品')


def test_loading_catalog_does_not_block_none(manual_ui):
    page,state=manual_ui;state['hold_catalog']=True;state['navigate']()
    expect(page.locator('#video-product-picker')).to_be_disabled()
    fill_video(page);page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('已加入队列')
    assert state['writes'][0]['product_intent']=='NONE'
    state.pop('catalog_route').fulfill(json=state['catalog'])
    expect(page.locator('#video-product-picker')).to_be_enabled()
    expect(page.locator('#video-product')).to_have_value('')


@pytest.mark.parametrize('unavailable',['network','account'])
def test_unavailable_catalog_still_allows_explicit_none(manual_ui,unavailable):
    page,state=manual_ui
    if unavailable=='network': state['catalog_failure']=True
    else:
        state['catalog']['account_id']=None
        for product in state['catalog']['products']:
            product.update(selectable=False,reason='发布账号归属未核实')
    state['navigate']();fill_video(page)
    if unavailable=='network': expect(page.locator('#manual-products-state')).to_contain_text('读取失败')
    else:
        expect(page.locator('#manual-products-state')).to_contain_text('账号 未登记')
        expect(page.locator('#manual-products-state')).to_contain_text('不绑定商品仍可提交')
        page.locator('#video-product-picker').click()
        expect(page.locator('#picker-list option')).to_have_count(4)
        page.locator('#picker-search').fill('70001001')
        expect(page.locator('.picker-apply')).to_be_disabled()
        page.keyboard.press('Escape')
    page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('不绑定商品')
    assert state['writes'][0]['product_intent']=='NONE'


def test_historical_exact_identity_can_be_selected_with_pending_session_verification(manual_ui):
    page, state = manual_ui
    state['catalog']['account_id'] = None
    state['catalog']['products'][0].update(
        identity_status='HISTORICAL_PENDING_SESSION_CHECK',
        verification_note='历史精确 ID 与全名，发布时须在当前会话严格核实')
    state['navigate']()
    fill_video(page)
    page.locator('#video-product-picker').click()
    page.locator('#picker-search').fill('70001001')
    expect(page.locator('#picker-list option')).to_contain_text('待发布会话核验')
    page.locator('#picker-list').select_option('unconfigured')
    page.locator('.picker-apply').click()
    expect(page.locator('#manual-product-detail')).to_contain_text('历史精确 ID 与全名，发布时须在当前会话严格核实')
    page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('已保存指定商品')
    assert state['writes'][0]['product_intent'] == 'PRODUCT'
    assert state['writes'][0]['product_alias'] == 'unconfigured'
    page.locator('#tab-queue').click()
    expect(page.locator('#row-manual-video .product-intent-detail')).to_contain_text('不代表平台已挂载')


def test_catalog_failure_retry_preserves_url_and_trim(manual_ui):
    page,state=manual_ui;state['catalog_failure']=True;state['navigate']()
    fill_video(page)
    expect(page.locator('#manual-products-state')).to_contain_text('读取失败')
    state['catalog_failure']=False;page.locator('#manual-products-retry').click()
    expect(page.locator('#manual-products-state')).to_contain_text('3 件')
    expect(page.locator('#video-url-input')).to_have_value('https://youtu.be/manualvideo')
    expect(page.locator('#video-trim-start')).to_have_value('00:00:10')
    expect(page.locator('#manual-products-state')).to_contain_text('2026/10/11 09:00:00')
    expect(page.locator('#manual-products-state')).to_contain_text('不代表平台实时全量核验')
    choose(page,'unconfigured','70001001')
    expect(page.locator('#manual-product-detail')).to_contain_text('完整长书名与版本')
    expect(page.locator('#manual-product-detail')).to_contain_text('快捷英语教辅图书')
    page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('已保存指定商品')
    assert state['writes'][0]['product_alias']=='unconfigured'
    page.locator('#tab-queue').click()
    expect(page.locator('#row-manual-video .product-intent-detail')).to_contain_text('ID 70001001')
    expect(page.locator('#row-manual-video .product-intent-detail')).to_contain_text('不代表平台已挂载')


def test_invalid_product_disabled_keyboard_cancel_preserves_selection(manual_ui):
    page,state=manual_ui;state['navigate']()
    choose(page,'finance','技术分析')
    button=page.locator('#video-product-picker');button.click()
    page.locator('#picker-search').fill('待核验')
    expect(page.locator('#picker-list option')).to_have_count(1)
    expect(page.locator('#picker-list option')).to_be_disabled()
    expect(page.locator('#picker-list option')).to_contain_text('账号未核实')
    expect(page.locator('.picker-apply')).to_be_disabled()
    page.keyboard.press('Escape')
    expect(page.locator('.product-picker-dialog')).not_to_be_visible()
    expect(button).to_be_focused();expect(page.locator('#video-product')).to_have_value('finance')
    assert state['writes']==[]


def test_submit_failure_and_duplicate_keep_choice_without_overwrite(manual_ui):
    page,state=manual_ui;state['navigate']();fill_video(page);choose(page,'unconfigured')
    state['add_failure']=True;page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('所选商品已失效')
    expect(page.locator('#video-product')).to_have_value('unconfigured')
    expect(page.locator('#video-url-input')).to_have_value('https://youtu.be/manualvideo')
    expect(page.locator('#video-trim-end')).to_have_value('00:01:10')
    state['add_failure']=False;state['duplicate']=True;page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('保留原商品意图')
    expect(page.locator('#video-product')).to_have_value('unconfigured')
    assert len(state['writes'])==2


def test_refresh_missing_product_does_not_silently_change_to_none(manual_ui):
    page,state=manual_ui;state['navigate']();fill_video(page);choose(page,'unconfigured')
    state['catalog']['products']=[p for p in state['catalog']['products'] if p['alias']!='unconfigured']
    page.locator('#manual-products-retry').click()
    expect(page.locator('#manual-product-detail')).to_contain_text('当前清单无法核实')
    expect(page.locator('#video-product')).to_have_value('unconfigured')
    page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('所选商品当前不可用')
    assert state['writes']==[]
    choose(page,'')
    page.locator('#btn-add-video').click()
    expect(page.locator('#add-video-feedback')).to_contain_text('不绑定商品')
    assert state['writes'][0]['product_intent']=='NONE'


def test_pending_submission_freezes_inputs_and_blocks_second_click(manual_ui):
    page,state=manual_ui;state['navigate']();fill_video(page);choose(page,'finance')
    state['hold_add']=True;page.locator('#btn-add-video').click()
    expect(page.locator('#manual-video-fields')).to_have_attribute('disabled','')
    expect(page.locator('#video-product-picker')).to_be_disabled()
    expect(page.locator('#video-url-input')).to_be_disabled()
    with pytest.raises(PlaywrightTimeoutError):page.locator('#btn-add-video').click(timeout=200)
    page.locator('.trim-toggle-row').click()
    expect(page.locator('#enable-trim-checkbox')).to_be_checked()
    assert len(state['writes'])==1
    state['release_add']()
    expect(page.locator('#add-video-feedback')).to_contain_text('已加入队列')
    expect(page.locator('#manual-video-fields')).not_to_have_attribute('disabled','')
    expect(page.locator('#video-product')).to_have_value('')


@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('theme',['light','dark','contrast'])
def test_picker_responsive_geometry_and_search_keyboard(manual_ui,width,theme,tmp_path):
    page,state=manual_ui;page.set_viewport_size({'width':width,'height':844});state['navigate']()
    page.locator('#btn-toggle-preferences').click();page.locator('#display-theme').select_option(theme)
    expect(page.locator('html')).to_have_attribute('data-theme',theme)
    assert page.locator('#video-content-type').bounding_box()['width']>=250
    page.locator('#video-product-picker').click();page.locator('#picker-search').fill('70001001')
    page.keyboard.press('ArrowDown');page.keyboard.press('Enter')
    expect(page.locator('#video-product')).to_have_value('unconfigured')
    page.locator('#video-product-picker').click()
    popup=page.locator('.product-picker-dialog');box=popup.bounding_box()
    assert 0 <= box['x'] and box['x']+box['width'] <= width
    assert 0 <= box['y'] and box['y']+box['height'] <= 844
    page.screenshot(path=str(tmp_path/f'manual-product-{width}-{theme}.png'))
    page.keyboard.press('Escape')
    assert state['writes']==[]

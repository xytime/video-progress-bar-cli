"""真实 Chromium + 实际 FastAPI 路由；所有 HTTP 在隔离夹具内转送 TestClient。"""
import json
from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from tests.unit.test_wechat_product_groups import api_setup, data
from video_processing.utils.wechat_product_config import load_policy

@pytest.fixture
def ui(chromium, api_setup):
    client,active,status,records=api_setup
    page=chromium.new_page(viewport={'width':1280,'height':900})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    flags={'offline':False,'conflict':False,'empty':False,'slow_save':False,'writes':0}
    def route(route):
        req=route.request;path=urlparse(req.url).path
        if flags['offline'] and path.startswith('/api/'):
            route.fulfill(status=503,json={'detail':'隔离测试：服务暂不可用'});return
        if flags['conflict'] and req.method=='PUT':
            route.fulfill(status=409,json={'detail':'配置已被其他窗口更新。请先重新载入，再修改保存。'});return
        if flags['empty'] and path.endswith('/videos'):
            route.fulfill(json={'videos':[],'limit':100});return
        if req.method=='PUT': flags['writes']+=1
        if flags.get('hold') == (req.method,path):
            def release():
                response=client.request(req.method,path,content=req.post_data,headers={'Content-Type':'application/json'})
                route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
            flags['release']=release
            return
        response=client.request(req.method,path,content=req.post_data,headers={'Content-Type':'application/json'})
        route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',route)
    page.goto('http://settings-test.invalid/product-settings')
    expect(page.locator('#editor')).to_be_enabled()
    yield page,active,status,flags
    page.close();assert errors==[]


def save_with_preview(page):
    page.locator('#save').click()
    page.wait_for_function("document.querySelector('#impact-dialog').open || !document.querySelector('#editor').disabled")
    if page.locator('#impact-dialog').is_visible():
        page.locator('#impact-confirm').click()


def test_real_save_preview_persist_and_version(ui):
    page,active,status,flags=ui
    expect(page).to_have_title('商品挂载设置 · 视频控制台')
    expect(page.locator('#publisher-state')).to_contain_text('尚未接入')
    page.locator('#english_world-0').select_option('finance')
    page.locator('#english_world-1').select_option('news')
    page.locator('#video').select_option('english:1')
    page.locator('#preview').click()
    expect(page.locator('#preview-result')).to_contain_text('英语世界短视频')
    expect(page.locator('#preview-result')).to_contain_text('当前未保存表单的预览')
    expect(page.locator('#preview-result li')).to_have_count(3)
    assert not status.exists()
    before=load_policy(active).digest
    save_with_preview(page)
    expect(page.locator('#feedback')).to_contain_text('配置已保存；发布器尚未接入')
    assert flags['writes']==1 and load_policy(active).digest!=before
    expect(page.locator('#adopted-version')).to_contain_text('尚无实际选品记录')
    page.reload();expect(page.locator('#english_world-0')).to_have_value('finance')
    assert not status.exists()


def test_conflict_failure_preserves_draft_and_reload_cancel(ui):
    page,active,status,flags=ui
    old=active.read_bytes();page.locator('#ted-0').select_option('finance');flags['conflict']=True
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('其他窗口更新')
    expect(page.locator('#ted-0')).to_have_value('finance');assert active.read_bytes()==old
    page.locator('#reload').click();expect(page.locator('#discard-dialog')).to_be_visible()
    expect(page.locator('#keep-editing')).to_be_focused()
    page.keyboard.press('Escape');expect(page.locator('#discard-dialog')).not_to_be_visible()
    page.locator('#reload').click();page.locator('#discard').click()
    expect(page.locator('#ted-0')).to_have_value('default')
    flags['offline']=True;page.locator('#reload').click();expect(page.locator('#feedback')).to_contain_text('读取失败')
    flags['offline']=False;page.locator('#reload').click();expect(page.locator('#feedback')).to_contain_text('配置已载入')


def test_invalid_chain_does_not_save(ui):
    page,active,_,_=ui
    old=active.read_bytes();page.locator('#english_world-0').select_option('finance');page.locator('#english_world-1').select_option('news')
    page.locator('summary').filter(has_text='识别条件').click();page.locator('#attempts').select_option('2')
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('默认回退不可达')
    assert active.read_bytes()==old
    page.locator('#timeout').fill('0');save_with_preview(page)
    expect(page.locator('#timeout')).to_have_attribute('aria-invalid','true');expect(page.locator('#timeout')).to_be_focused()


@pytest.mark.parametrize('width',[1280,390])
def test_keyboard_responsive_and_screenshot(ui,width):
    page,_,_,_=ui
    page.set_viewport_size({'width':width,'height':900})
    page.emulate_media(reduced_motion='reduce')
    control=page.locator('#wallstreet-0');control.focus();page.keyboard.press('Space');page.keyboard.press('ArrowDown');page.keyboard.press('Enter')
    expect(control).to_be_focused()
    assert ui[3]['writes']==0
    page.locator('#video').select_option('english:1');page.locator('#preview').click()
    expect(page.locator('#preview-result li')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.evaluate("Array.from(document.querySelectorAll('select,input')).every(x=>x.labels.length>0)")
    evidence=Path(__file__).resolve().parents[2]/'output/test-evidence';evidence.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(evidence/f'product-settings-{width}.png'),full_page=True)


def test_empty_list_and_draft_preview(ui):
    page,_,_,flags=ui
    flags['empty']=True;page.locator('#reload').click();expect(page.locator('#videos-state')).to_contain_text('暂无待发布')
    page.locator('#sample-context summary').click();page.locator('#topic').select_option('AI');page.locator('#preview').click()
    expect(page.locator('#preview-result')).to_contain_text('AI 相关资讯')
    page.locator('#topic').select_option('');page.locator('#category').select_option('科技');page.locator('#preview').click()
    expect(page.locator('#preview-result h3')).to_have_text('其他')


def test_pending_save_blocks_duplicate_clicks(ui):
    page,active,_,flags=ui
    before=active.read_bytes();page.locator('#ted-0').select_option('finance')
    flags['hold']=('PUT','/api/product-settings')
    save_with_preview(page);expect(page.locator('#save')).to_be_disabled()
    expect(page.locator('#feedback')).to_contain_text('正在保存')
    page.locator('#save').evaluate('(button)=>button.click()')
    assert flags['writes']==1 and active.read_bytes()==before
    flags['release']();expect(page.locator('#feedback')).to_contain_text('配置已保存；发布器尚未接入')


def test_old_preview_cannot_overwrite_new_context(ui):
    page,_,_,flags=ui
    flags['hold']=('POST','/api/product-settings/preview')
    page.locator('#preview').click();expect(page.locator('#preview-result')).to_contain_text('正在计算')
    page.locator('#video').select_option('english:1')
    flags['release']();expect(page.locator('#preview')).to_be_enabled()
    expect(page.locator('#preview-result')).to_have_text('上下文已修改，请重新预览。')


def test_all_product_dropdowns_use_catalog_and_new_selection_persists(ui):
    from tests.unit.test_wechat_product_catalog import install_catalog
    page, active, _, flags = ui
    saved=json.loads(active.read_text())
    rows=list(saved['products'].values())+[dict(product_id='70001',title='新增真实目录商品'),dict(product_id='70002',title='新增真实目录商品')]
    path=install_catalog(active,rows)
    catalog=json.loads(path.read_text());catalog['items'][-1]['stock']=0;path.write_text(json.dumps(catalog))
    original=active.read_bytes()
    page.locator('#reload').click()
    expect(page.locator('#catalog-state')).to_contain_text('5 件商品')
    expect(page.locator('#catalog-state')).to_contain_text('全量完整性尚未确认')
    assert active.read_bytes()==original
    controls=['#default-product','#manual','#rule-0','#rule-1']
    controls += [f'#{group}-{index}' for group in saved['profiles'] for index in (0,1)]
    for control in controls:
        expect(page.locator(control+' option[value="product_70001"]')).to_have_count(1)
        expect(page.locator(control+' option[value="product_70002"]')).to_have_count(1)
        expect(page.locator(control+' option[value="product_70002"]')).to_contain_text('采集时缺货')
    page.locator('#english_world-0').select_option('product_70001')
    expect(page.locator('#english_world-0-detail')).to_contain_text('ID 70001')
    expect(page.locator('#english_world-0-detail')).to_contain_text('采集时库存未知')
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    page.reload();expect(page.locator('#english_world-0')).to_have_value('product_70001')
    page.locator('#video').select_option('english:1');page.locator('#preview').click()
    expect(page.locator('#preview-result li').first).to_contain_text('ID 70001')
    assert flags['writes']==1
    assert json.loads(active.read_text())['profiles']['ted']==saved['profiles']['ted']
    path.write_text('{')
    page.locator('#reload').click();expect(page.locator('#catalog-state')).to_contain_text('商品清单读取失败')
    expect(page.locator('#english_world-0')).to_have_value('product_70001')


def test_catalog_file_preview_import_and_error_keeps_current(ui):
    from tests.unit.test_wechat_catalog_import import document
    page,active,_,flags=ui
    original=active.read_bytes()
    doc=document(list(json.loads(original)['products'].values())+[dict(product_id='8880001',title='新导入目录图书')])
    page.locator('summary').filter(has_text='更新商品清单').click()
    page.locator('#catalog-file').set_input_files({'name':'catalog.json','mimeType':'application/json','buffer':json.dumps(doc).encode()})
    page.locator('#catalog-check').click()
    expect(page.locator('#catalog-import-feedback')).to_contain_text('文件完整性校验通过，尚未导入')
    expect(page.locator('#catalog-import-preview')).to_contain_text('首次登记清单账号')
    assert not active.with_name('wechat_product_catalog.json').exists()
    page.locator('#catalog-apply').click()
    expect(page.locator('#catalog-import-feedback')).to_contain_text('已导入 4 件商品')
    expect(page.locator('#catalog-state')).to_contain_text('导入完整性校验通过（2 页），非平台实时核验')
    for control in ('#default-product','#english_world-0','#ted-1','#manual','#rule-0'):
        expect(page.locator(control+' option[value="product_8880001"]')).to_have_count(1)
    assert active.read_bytes()==original
    page.reload();expect(page.locator('#catalog-state')).to_contain_text('2 页')
    page.locator('summary').filter(has_text='更新商品清单').click()
    old=active.with_name('wechat_product_catalog.json').read_bytes();doc['pages'].pop()
    page.locator('#catalog-file').set_input_files({'name':'broken.json','mimeType':'application/json','buffer':json.dumps(doc).encode()})
    page.locator('#catalog-check').click()
    expect(page.locator('#catalog-import-feedback')).to_contain_text('分页不完整')
    expect(page.locator('#catalog-apply')).to_be_disabled()
    assert active.with_name('wechat_product_catalog.json').read_bytes()==old
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_catalog_import_protects_unsaved_config_and_blocks_duplicate_submit(ui):
    from tests.unit.test_wechat_catalog_import import document
    page,active,_,flags=ui
    doc=document(list(json.loads(active.read_text())['products'].values()))
    page.locator('summary').filter(has_text='更新商品清单').click()
    page.locator('#catalog-file').set_input_files({'name':'catalog.json','mimeType':'application/json','buffer':json.dumps(doc).encode()})
    page.locator('#ted-0').select_option('finance')
    page.locator('#catalog-check').click()
    expect(page.locator('#catalog-import-feedback')).to_contain_text('有未保存修改')
    expect(page.locator('#ted-0')).to_have_value('finance')
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    page.locator('#catalog-check').click();expect(page.locator('#catalog-apply')).to_be_enabled()
    flags['hold']=('POST','/api/product-settings/catalog/import')
    page.locator('#catalog-apply').click();expect(page.locator('#catalog-apply')).to_be_disabled()
    expect(page.locator('#save')).to_be_disabled()
    page.locator('#catalog-apply').evaluate('(el)=>el.click()')
    assert not active.with_name('wechat_product_catalog.json').exists()
    flags['release']();expect(page.locator('#catalog-import-feedback')).to_contain_text('已导入 3 件商品')
    expect(page.locator('#ted-0')).to_have_value('finance')


def test_impact_cancel_and_history_restore_as_draft(ui):
    page,active,status,flags=ui
    old=load_policy(active);page.locator('#english_world-0').select_option('finance')
    page.locator('#save').click();expect(page.locator('#impact-dialog')).to_be_visible()
    expect(page.locator('#impact-result')).to_contain_text('变化 1 条')
    assert active.read_bytes() and load_policy(active).digest==old.digest
    page.locator('#impact-cancel').click();assert flags['writes']==0
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    expect(page.locator('#revision option')).to_have_count(2)
    page.locator('#revision').select_option(old.digest);page.locator('#restore-revision').click()
    expect(page.locator('#feedback')).to_contain_text('恢复草稿')
    expect(page.locator('#english_world-0')).to_have_value('default')
    assert load_policy(active).digest!=old.digest
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert load_policy(active).version!=old.version
    assert load_policy(active).decide(content_type='ENGLISH_WORLD_SHORT').candidates==old.decide(content_type='ENGLISH_WORLD_SHORT').candidates


def test_library_pending_then_verified_and_selected(ui):
    page,active,_,flags=ui
    page.locator('#library-new').click()
    page.locator('#lib-title').fill('新书完整名称')
    page.locator('#lib-shop').fill('快捷英语教辅图书')
    page.locator('#lib-merchant_appid').fill('wx490e65efa3751b8c')
    page.locator('#library-apply').click()
    expect(page.locator('#library-feedback')).to_contain_text('已应用到草稿')
    alias=page.locator('#library-choice').input_value()
    expect(page.locator(f'#default-product option[value="{alias}"]')).to_have_count(0)
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert json.loads(active.read_text())['library'][alias]['identity_status']=='UNVERIFIED'
    page.locator('#library-choice').select_option(alias)
    page.locator('#lib-product_id').fill('88888888')
    page.locator('#lib-account_id').fill('verified-publisher')
    page.locator('#lib-verified_source').fill('人工核对后台资料')
    page.locator('#lib-verified_at').fill('2026-01-01T00:00:00+08:00')
    page.locator('#lib-identity_status').select_option('VERIFIED')
    page.locator('#library-apply').click()
    page.locator('#english_world-0').select_option(alias)
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert load_policy(active).decide(content_type='ENGLISH_WORLD_SHORT').candidates[0].product_id=='88888888'
    page.reload();expect(page.locator('#english_world-0')).to_have_value(alias)
    page.locator('#library-search').fill('快捷英语')
    expect(page.locator('#library-choice option')).to_have_count(2)


def test_refresh_wait_parameters_and_disabled_reference(ui):
    page,active,_,_=ui
    page.locator('#catalog-refresh').click();expect(page.locator('#refresh-state')).to_contain_text('尚未核验')
    expect(page.locator('#wait-state')).to_contain_text('调度接入')
    page.locator('#library-choice').select_option('default');page.locator('#library-toggle').click()
    page.locator('#save').click();expect(page.locator('#feedback')).to_contain_text('停用')
    page.locator('#library-toggle').click()
    page.locator('summary').filter(has_text='等待与恢复检查').click()
    page.locator('#wait-base_seconds').fill('600')
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert json.loads(active.read_text())['wait_policy']['base_seconds']==600

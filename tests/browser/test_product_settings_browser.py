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


def test_real_save_preview_persist_and_version(ui):
    page,active,status,flags=ui
    expect(page).to_have_title('商品挂载设置 · 视频控制台')
    page.locator('#english_world-0').select_option('finance')
    page.locator('#english_world-1').select_option('news')
    page.locator('#video').select_option('english:1')
    page.locator('#preview').click()
    expect(page.locator('#preview-result')).to_contain_text('英语世界短视频')
    expect(page.locator('#preview-result')).to_contain_text('当前未保存表单的预览')
    expect(page.locator('#preview-result li')).to_have_count(3)
    assert not status.exists()
    before=load_policy(active).digest
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert flags['writes']==1 and load_policy(active).digest!=before
    expect(page.locator('#adopted-version')).to_contain_text('尚无实际选品记录')
    page.reload();expect(page.locator('#english_world-0')).to_have_value('finance')
    assert not status.exists()


def test_conflict_failure_preserves_draft_and_reload_cancel(ui):
    page,active,status,flags=ui
    old=active.read_bytes();page.locator('#ted-0').select_option('finance');flags['conflict']=True
    page.locator('#save').click();expect(page.locator('#feedback')).to_contain_text('其他窗口更新')
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
    page.locator('#save').click();expect(page.locator('#feedback')).to_contain_text('默认回退不可达')
    assert active.read_bytes()==old
    page.locator('#timeout').fill('0');page.locator('#save').click()
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
    page.locator('#save').click();expect(page.locator('#save')).to_be_disabled()
    expect(page.locator('#feedback')).to_contain_text('正在保存')
    page.locator('#save').evaluate('(button)=>button.click()')
    assert flags['writes']==1 and active.read_bytes()==before
    flags['release']();expect(page.locator('#feedback')).to_contain_text('配置已保存')


def test_old_preview_cannot_overwrite_new_context(ui):
    page,_,_,flags=ui
    flags['hold']=('POST','/api/product-settings/preview')
    page.locator('#preview').click();expect(page.locator('#preview-result')).to_contain_text('正在计算')
    page.locator('#video').select_option('english:1')
    flags['release']();expect(page.locator('#preview')).to_be_enabled()
    expect(page.locator('#preview-result')).to_have_text('上下文已修改，请重新预览。')

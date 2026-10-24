"""真实Chromium配置中心全流程；全部HTTP转送隔离API，无平台请求。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| optional-publish-v1 | 2026-10-25 | Codex | 适配取消发布日额与英语世界安全无商品降级，保留其他门禁与冻结身份。 |
| runtime-center-v1 | 2026-10-24 | Codex | 编辑/预览/保存/回滚、失败草稿、移动主题与键盘状态验收。 |
"""
from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from tests.unit.test_runtime_configuration import api_setup,configured,active,save
from video_processing.utils import runtime_configuration as runtime


@pytest.fixture
def ui(chromium,api_setup):
    client,db,first=api_setup
    page=chromium.new_page(viewport={'width':1440,'height':1000})
    errors=[];warnings=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('console',lambda m:warnings.append(m.text) if m.type=='error' else None)
    flags={}
    def route(route):
        request=route.request;parsed=urlparse(request.url);path=parsed.path
        if flags.get('state_error') and path.endswith('/state'):
            route.fulfill(status=503,json={'detail':'合成状态不可用'});return
        if flags.get('apply_error') and path.endswith('/apply'):
            route.fulfill(status=409,json={'detail':'合成并发版本冲突'});return
        if flags.get('hold_preview') and path.endswith('/preview'):
            def release():
                result=client.request(request.method,path,content=request.post_data,headers={'Content-Type':'application/json'})
                route.fulfill(status=result.status_code,body=result.content,content_type='application/json')
            flags['release_preview']=release;return
        response=client.request(request.method,path,content=request.post_data,headers={'Content-Type':'application/json'})
        route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',route)
    page.goto('http://127.0.0.1:9100/runtime-configuration')
    expect(page.locator('#revision')).to_contain_text('v-')
    expect(page.locator('#state-feedback')).to_contain_text('本地快照')
    yield page,flags,first
    page.close();assert errors==[]
    assert not [w for w in warnings if 'Failed to load resource' not in w]


def change(page,value='49'):
    page.locator('#field-wechat_operations-operations-first_comment-rolling_24h_limit').fill(value)
    page.locator('#reason').fill('合成用户操作验收')


def test_publish_unlimited_save_reload_and_clear_finite_cap(ui):
    page,_,_=ui
    field=page.locator('#field-wechat_operations-operations-publish-rolling_24h_limit')
    expect(field).to_have_value('')
    expect(field).to_have_attribute('placeholder','无每日上限')
    expect(page.locator('#gate-publish')).to_contain_text('无每日上限')
    field.fill('25');page.locator('#reason').fill('合成临时收紧测试')
    page.locator('#preview').click()
    expect(page.locator('#preview-content')).to_contain_text('无每日上限 → 25')
    page.locator('#apply').click();expect(page.locator('#feedback')).to_contain_text('配置已提交')
    field.fill('');page.locator('#reason').fill('合成取消每日上限')
    expect(field).to_have_attribute('aria-invalid','false')
    page.locator('#preview').click()
    expect(page.locator('#preview-content')).to_contain_text('25 → 无每日上限')
    page.locator('#apply').click();expect(page.locator('#feedback')).to_contain_text('配置已提交')
    page.reload();expect(field).to_have_value('')
    assert runtime.store().read().domains()['wechat_operations']['operations']['publish']['rolling_24h_limit'] is None


def test_real_save_reload_and_history_rollback(ui):
    page,_,first=ui
    assert page.title()=='运行配置 · 视频运营工作台'
    expect(page.locator('#operation-cards section')).to_have_count(6)
    change(page);page.locator('#preview').click()
    expect(page.locator('#preview-dialog')).to_be_visible()
    expect(page.locator('#cancel-preview')).to_be_focused()
    expect(page.locator('#preview-content')).to_contain_text('50 → 49')
    page.locator('#apply').click()
    expect(page.locator('#feedback')).to_contain_text('配置已提交')
    assert runtime.store().read().domains()['wechat_operations']['operations']['first_comment']['rolling_24h_limit']==49
    page.reload();expect(page.locator('#field-wechat_operations-operations-first_comment-rolling_24h_limit')).to_have_value('49')
    assert page.locator('#field-wechat_operations-operations-first_comment-rolling_24h_limit').get_attribute('max')=='50'
    page.locator('#reason').fill('合成回滚验证')
    page.get_by_role('button',name='版本与回滚',exact=True).click()
    page.get_by_role('button',name='预览回滚',exact=True).click()
    expect(page.locator('#preview-content')).to_contain_text('49 → 50')
    page.locator('#apply').click();expect(page.locator('#feedback')).to_contain_text('配置已提交')
    assert runtime.store().read().domains()['wechat_operations']['operations']['first_comment']['rolling_24h_limit']==50


def test_reply_switch_real_persistence_and_unchanged_time_window(ui):
    page,_,_=ui
    expect(page.locator('#automatic-replies-enabled')).not_to_be_checked()
    page.locator('#automatic-replies-enabled').check()
    page.locator('#reason').fill('合成启用观众回复验证')
    page.locator('#preview').click()
    expect(page.locator('#preview-content')).to_contain_text('automatic_replies_enabled')
    expect(page.locator('#preview-content')).to_contain_text('北京时间')
    page.locator('#apply').click();expect(page.locator('#feedback')).to_contain_text('配置已提交')
    page.reload();expect(page.locator('#automatic-replies-enabled')).to_be_checked()
    page.locator('#automatic-replies-enabled').uncheck();page.locator('#reason').fill('合成关闭观众回复验证')
    page.locator('#preview').click();page.locator('#apply').click()
    expect(page.locator('#feedback')).to_contain_text('配置已提交')
    assert runtime.store().read().domains()['interaction_controls']['automatic_replies_enabled'] is False


def test_catalog_coverage_search_clear_and_form_source(ui):
    page,_,_=ui;page.get_by_role('button',name='全部配置目录',exact=True).click()
    expect(page.locator('#coverage')).to_contain_text('18组')
    expect(page.locator('#config-files')).to_contain_text('内容安全规则')
    page.locator('#search').fill('wait_notice_cooldown')
    expect(page.locator('.catalog-row')).to_have_count(1)
    expect(page.locator('.catalog-row')).to_contain_text('活动版本 observability')
    page.locator('#field-observability-wait_notice_cooldown_seconds').fill('7200')
    expect(page.locator('#dirty-state')).to_contain_text('未保存')
    page.locator('#clear-search').click();expect(page.locator('#search')).to_be_focused()
    page.locator('#search').fill('no-such-configuration-合成')
    expect(page.locator('#catalog-fields')).to_contain_text('没有匹配参数')
    assert 'q=no-such' in page.url


def test_conflict_keeps_draft_and_discard_escape_focus(ui):
    page,flags,_=ui;change(page);page.locator('#preview').click();flags['apply_error']=True
    page.locator('#apply').click();expect(page.locator('#apply-feedback')).to_contain_text('草稿已保留')
    expect(page.locator('#apply')).to_be_disabled();page.locator('#cancel-preview').click()
    expect(page.locator('#field-wechat_operations-operations-first_comment-rolling_24h_limit')).to_have_value('49')
    page.locator('#reload').click();expect(page.locator('#discard-dialog')).to_be_visible()
    expect(page.locator('#keep-editing')).to_be_focused();page.keyboard.press('Escape')
    expect(page.locator('#reload')).to_be_focused()
    expect(page.locator('#field-wechat_operations-operations-first_comment-rolling_24h_limit')).to_have_value('49')


def test_stale_preview_cannot_apply_changed_form(ui):
    page,flags,_=ui;change(page);flags['hold_preview']=True;page.locator('#preview').click()
    expect(page.locator('#preview')).to_be_disabled()
    page.locator('#field-wechat_operations-operations-first_comment-rolling_24h_limit').fill('48')
    flags['release_preview']()
    expect(page.locator('#feedback')).to_contain_text('草稿已变化')
    expect(page.locator('#preview-dialog')).not_to_be_visible()


def test_invalid_fields_and_failed_status_do_not_claim_ready(ui):
    page,flags,_=ui;change(page,'51')
    expect(page.locator('#preview')).to_be_disabled()
    expect(page.locator('#field-wechat_operations-operations-first_comment-rolling_24h_limit')).to_have_attribute('aria-invalid','true')
    flags['state_error']=True
    expect(page.locator('#state-feedback')).to_contain_text('读取失败',timeout=8000)
    expect(page.locator('#gate-publish')).to_contain_text('状态未知')


@pytest.mark.parametrize('theme',['light','dark','contrast'])
def test_themes_mobile_keyboard_and_screenshots(ui,theme):
    page,_,_=ui;page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
    evidence=Path(__file__).resolve().parents[2]/'output/test-evidence/runtime-configuration';evidence.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(evidence/(theme+'-desktop.png')),full_page=True)
    page.get_by_role('button',name='全部配置目录',exact=True).focus();page.keyboard.press('Enter')
    expect(page.locator('#catalog-view')).to_be_visible()
    page.locator('#group').select_option('G12')
    expect(page.locator('#catalog-count')).to_contain_text('项')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,id:e.id,className:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))")
    page.screenshot(path=str(evidence/(theme+'-mobile.png')),full_page=True)
    page.emulate_media(reduced_motion='reduce')
    page.get_by_role('button',name='操作额度与等待',exact=True).click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,id:e.id,className:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))")
    page.screenshot(path=str(evidence/(theme+'-mobile-operations.png')),full_page=False)

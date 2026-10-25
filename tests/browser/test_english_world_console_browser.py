"""英语世界真实 Chromium 列表/证据/手机流程，网络只接隔离 API。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 合成台账验证组合筛选、Esc焦点、失败旧数据与手机返回。 |
"""
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from tests.unit.test_english_world_console import console_data, console_api, ORIGIN


@pytest.fixture
def ui(chromium,console_api):
    client,_=console_api
    page=chromium.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)));flags={}
    def route(request):
        parsed=urlsplit(request.request.url);path=parsed.path+('?' + parsed.query if parsed.query else '')
        if flags.get('error') and parsed.path=='/api/english-world/console':
            request.fulfill(status=503,json={'detail':'synthetic failure'});return
        response=client.get(path)
        request.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',route);page.goto(ORIGIN+'/english-world')
    expect(page.locator('#ew-feedback')).to_contain_text('已读取')
    yield page,flags
    page.close();assert not errors


def capture(page,name):
    directory=Path(__file__).resolve().parents[2]/'output/test-evidence/english-world-console'
    directory.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(directory/(name+'.png')),full_page='report' not in name)


def test_desktop_filter_paging_dialog_focus_and_error(ui):
    page,flags=ui
    expect(page.locator('.ew-task')).to_have_count(20)
    page.locator('#ew-next').click();expect(page.locator('.ew-task')).to_have_count(6)
    page.locator('#ew-search').fill('  oCeAn ')
    page.locator('#ew-search').press('Enter')
    page.locator('#ew-trigger').select_option('manual')
    page.locator('#ew-date').fill('2026-10-25')
    expect(page.locator('.ew-task')).to_have_count(1)
    expect(page.locator('#ew-task-heading')).to_have_text('Ocean 科学 0')
    page.locator('[data-report="language"]').click()
    expect(page.locator('#ew-report')).to_be_visible()
    expect(page.locator('#ew-report-body')).to_contain_text('证据缺失')
    page.keyboard.press('Escape');expect(page.locator('[data-report="language"]')).to_be_focused()
    page.locator('#ew-search').fill('zero matches');page.locator('#ew-search').press('Enter')
    expect(page.locator('.ew-task')).to_have_count(0)
    expect(page.locator('#ew-detail')).to_contain_text('没有匹配')
    page.locator('#ew-reset').click();expect(page.locator('.ew-task')).to_have_count(20)
    capture(page,'desktop')
    flags['error']=True;page.locator('#ew-refresh').click()
    expect(page.locator('#ew-feedback')).to_contain_text('上次记录，当前进度未知')
    expect(page.locator('.ew-task')).to_have_count(20)


@pytest.mark.parametrize('width',[390,320])
def test_mobile_return_filters_report_and_no_overflow(ui,width):
    page,_=ui;page.set_viewport_size({'width':width,'height':844})
    page.locator('#ew-search').fill('ocean');page.locator('#ew-search').press('Enter')
    page.locator('#ew-more').click();page.locator('#ew-trigger').select_option('manual')
    expect(page.locator('.ew-task')).to_have_count(1)
    page.locator('.ew-task').click()
    expect(page.locator('#ew-task-heading')).to_be_focused()
    expect(page.locator('#ew-list-view')).not_to_be_visible()
    page.locator('[data-report="platform"]').click()
    expect(page.locator('#ew-report-body')).to_contain_text('视频号')
    capture(page,'mobile-report-'+str(width))
    page.locator('#ew-report-close').click();expect(page.locator('[data-report="platform"]')).to_be_focused()
    page.locator('.ew-detail-back').click()
    expect(page.locator('#ew-search')).to_have_value('ocean')
    expect(page.locator('#ew-trigger')).to_have_value('manual')
    expect(page.locator('.ew-task')).to_be_focused()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    capture(page,'mobile-'+str(width))


def test_url_restore_native_controls_navigation_and_read_only(ui):
    page,_=ui
    page.goto(ORIGIN+'/english-world?q=Ocean&trigger=manual&category=attention')
    expect(page.locator('.ew-task')).to_have_count(1)
    expect(page.locator('a[href="/english-world"]')).to_have_attribute('aria-current','page')
    page.locator('#ew-trigger').focus();page.keyboard.press('ArrowDown');page.keyboard.press('Enter')
    expect(page.locator('#ew-feedback')).to_contain_text('已读取')
    assert not page.locator('button:has-text("批准"),button:has-text("重试"),button:has-text("发布")').count()


@pytest.mark.parametrize('theme',['dark','light','contrast'])
def test_desktop_panels_fit_and_theme_scope(ui,theme):
    page,_=ui;page.set_viewport_size({'width':1366,'height':768})
    page.evaluate('(theme)=>localStorage.setItem("vp-display-preferences",JSON.stringify({theme,size:"large"}))',theme)
    page.reload();expect(page.locator('#ew-feedback')).to_contain_text('已读取')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    bounds=page.locator('.ew-workspace').bounding_box()
    assert bounds['height']>=200 and bounds['y']+bounds['height']<=768
    assert page.locator('.ew-task').first.bounding_box()['y']<650
    page.locator('.ew-task').nth(1).click()
    expect(page.locator('#ew-task-heading')).to_have_text('Ocean 科学 9')
    capture(page,'desktop-'+theme)

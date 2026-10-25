"""双设置入口联动的真实 Chromium 验收；请求仅送合成临时 API。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 保存重读、手动保护、恢复自动、失败竞态和窄屏键盘。 |
"""
from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from tests.unit.test_reply_linkage import linked_api, configured, active


@pytest.fixture
def ui(chromium, linked_api):
    client, _ = linked_api
    page = chromium.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    flags={}
    def route_handler(route):
        request=route.request;url=urlparse(request.url);path=url.path+('?' + url.query if url.query else '')
        if url.path.endswith('/reply-recommend'):
            if flags.get('fail'):
                route.fulfill(status=503,json={'detail':'合成计算暂不可用'});return
            if flags.get('hold')==request.post_data_json['config']['daily_quota']:
                response=client.request(request.method,path,content=request.post_data,headers={'Content-Type':'application/json'})
                flags['release']=lambda:route.fulfill(status=response.status_code,body=response.content,content_type='application/json');return
        if flags.get('conflict') and request.method=='PUT':
            route.fulfill(status=409,json={'detail':'合成其他窗口已更新'});return
        response=client.request(request.method,path,content=request.post_data,headers={'Content-Type':'application/json'})
        route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',route_handler)
    page.goto('http://127.0.0.1:9100/secondary-reply-settings?tab=policy')
    expect(page.locator('#daily-quota')).to_be_visible()
    yield page,flags
    page.close();assert errors==[]


def test_cross_entry_save_override_restore_and_no_initial_migration(ui):
    page,_=ui
    expect(page.locator('#min-interval-seconds')).to_have_value('60')
    expect(page.locator('#save')).to_be_disabled()
    page.locator('#daily-quota').fill('200')
    expect(page.locator('#hourly-quota')).to_have_value('10')
    expect(page.locator('#min-interval-seconds')).to_have_value('360')
    page.locator('#hourly-quota').fill('8')
    expect(page.locator('#reply-linkage-hourly_quota-mode')).to_contain_text('手动')
    expect(page.locator('#reply-linkage-capacity')).to_contain_text('容量不足')
    page.locator('#save').click()
    expect(page.get_by_role('button',name='返回调整',exact=True)).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.locator('#save')).to_be_focused()
    page.locator('#reply-linkage-hourly_quota-restore').click()
    expect(page.locator('#hourly-quota')).to_have_value('10')
    page.locator('#min-interval-seconds').fill('720')
    page.locator('#daily-quota').fill('500')
    expect(page.locator('#hourly-quota')).to_have_value('25')
    expect(page.locator('#min-interval-seconds')).to_have_value('720')
    page.locator('#save').click()
    page.get_by_role('button',name='仍保存此配置',exact=True).click()
    expect(page.locator('#feedback')).to_contain_text('策略已保存')
    page.reload()
    expect(page.locator('#min-interval-seconds')).to_have_value('720')
    expect(page.locator('#reply-linkage-min_interval_seconds-mode')).to_contain_text('手动')
    page.locator('#reply-linkage-min_interval_seconds-restore').click()
    expect(page.locator('#min-interval-seconds')).to_have_value('144')
    page.locator('#save').click();expect(page.locator('#feedback')).to_contain_text('策略已保存')
    page.goto('http://127.0.0.1:9100/runtime-configuration')
    prefix='#field-wechat_operations-operations-reply-'
    expect(page.locator(prefix+'rolling_24h_limit')).to_have_value('500')
    page.locator(prefix+'rolling_24h_limit').fill('800')
    expect(page.locator(prefix+'rolling_1h_limit')).to_have_value('40')
    expect(page.locator(prefix+'min_interval_seconds')).to_have_value('72')
    page.locator('#reason').fill('合成双入口保存验收');page.locator('#preview').click()
    expect(page.locator('#preview-content')).to_contain_text('500 → 800')
    expect(page.locator('#preview-content')).to_contain_text('目标容量足够')
    page.locator('#apply').click();expect(page.locator('#feedback')).to_contain_text('配置已提交')
    page.goto('http://127.0.0.1:9100/secondary-reply-settings?tab=policy')
    expect(page.locator('#daily-quota')).to_have_value('800')
    expect(page.locator('#hourly-quota')).to_have_value('40')
    expect(page.locator('#min-interval-seconds')).to_have_value('72')


def test_old_recommendation_error_recovery_and_conflict_preserve_draft(ui):
    page,flags=ui
    flags['hold']=200
    page.locator('#daily-quota').fill('200')
    expect(page.locator('#save')).to_be_disabled()
    page.wait_for_timeout(100)
    assert flags.get('release')
    page.locator('#daily-quota').fill('500')
    expect(page.locator('#hourly-quota')).to_have_value('25')
    flags['release']();flags.pop('hold')
    expect(page.locator('#hourly-quota')).to_have_value('25')
    flags['fail']=True
    page.locator('#daily-quota').fill('200')
    expect(page.locator('#reply-linkage-capacity')).to_contain_text('暂不可用')
    expect(page.locator('#save')).to_be_disabled()
    expect(page.locator('#daily-quota')).to_have_value('200')
    flags['fail']=False
    page.locator('#reply-linkage-restore-all').click()
    expect(page.locator('#hourly-quota')).to_have_value('10')
    flags['conflict']=True
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('保存冲突')
    expect(page.locator('#daily-quota')).to_have_value('200')
    expect(page.locator('#save')).to_be_disabled()


@pytest.mark.parametrize('theme,width',[('light',1440),('dark',390),('contrast',320)])
def test_responsive_keyboard_and_capacity_evidence(ui,theme,width):
    page,_=ui;page.set_viewport_size({'width':width,'height':1000})
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
    page.locator('#daily-quota').fill('200')
    expect(page.locator('#hourly-quota')).to_have_value('10')
    page.locator('#hourly-quota').fill('8')
    expect(page.locator('#reply-linkage-capacity')).to_contain_text('容量不足')
    restore=page.locator('#reply-linkage-hourly_quota-restore')
    restore.focus();page.keyboard.press('Enter')
    expect(page.locator('#hourly-quota')).to_have_value('10')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    evidence=Path(__file__).resolve().parents[2]/'output/test-evidence/reply-linkage';evidence.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(evidence/f'{theme}-{width}-policy.png'),full_page=True)
    page.locator('#save').click();expect(page.locator('#feedback')).to_contain_text('策略已保存')
    page.goto('http://127.0.0.1:9100/runtime-configuration')
    expect(page.locator('#runtime-reply-linkage-capacity')).to_contain_text('200 条')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(evidence/f'{theme}-{width}-runtime.png'),full_page=True)


def test_runtime_manual_values_survive_save_reload_and_later_daily_change(ui):
    page,_=ui
    page.goto('http://127.0.0.1:9100/runtime-configuration')
    prefix='#field-wechat_operations-operations-reply-'
    page.locator(prefix+'rolling_24h_limit').fill('200')
    expect(page.locator(prefix+'rolling_1h_limit')).to_have_value('10')
    page.locator(prefix+'rolling_1h_limit').fill('8')
    expect(page.locator('#runtime-reply-linkage-hourly_quota-mode')).to_contain_text('手动')
    page.locator(prefix+'min_interval_seconds').fill('600')
    expect(page.locator('#runtime-reply-linkage-capacity')).to_contain_text('容量不足')
    page.locator('#reason').fill('合成手动容量保存');page.locator('#preview').click()
    expect(page.locator('#preview-content')).to_contain_text('容量不足')
    page.locator('#apply').click();expect(page.locator('#feedback')).to_contain_text('配置已提交')
    page.reload();expect(page.locator(prefix+'rolling_1h_limit')).to_have_value('8')
    page.locator(prefix+'rolling_24h_limit').fill('500')
    expect(page.locator('#runtime-reply-linkage-capacity')).to_contain_text('500 条')
    expect(page.locator(prefix+'rolling_1h_limit')).to_have_value('8')
    expect(page.locator(prefix+'min_interval_seconds')).to_have_value('600')
    page.locator('#runtime-reply-linkage-hourly_quota-restore').click()
    expect(page.locator(prefix+'rolling_1h_limit')).to_have_value('25')
    expect(page.locator(prefix+'min_interval_seconds')).to_have_value('600')
    page.locator('#runtime-reply-linkage-min_interval_seconds-restore').click()
    expect(page.locator(prefix+'min_interval_seconds')).to_have_value('144')
    expect(page.locator(prefix+'min_interval_seconds')).to_have_attribute('aria-invalid','false')

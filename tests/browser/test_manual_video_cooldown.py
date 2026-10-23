"""冷却弹窗真实 Chromium 验收；业务请求均为隔离回执，不访问生产或微信。"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium, dashboard


@pytest.fixture
def cooldown_page(dashboard):
    page, state = dashboard
    state.update(process_requests=[], force_error=False, changed=False)
    info = dict(active=True, until=datetime.now(timezone.utc).timestamp() + 3600,
                remaining_seconds=3600, version='current', business_code=-360, reason='视频号返回限流')
    def route(route):
        query = parse_qs(urlsplit(route.request.url).query)
        state['process_requests'].append(query)
        action = query.get('cooldown_action', [''])[0]
        if action == 'force' and state['force_error']:
            route.fulfill(status=503, json={'error':'任务未启动，执行者不可用'})
        elif action == 'force' and state['changed']:
            state['changed'] = False
            route.fulfill(json={'success':False,'code':'WECHAT_COOLDOWN','cooldown':dict(info,version='updated'),
                                'prepared':True,'error':'冷却状态已变化，请重新确认'})
        elif action:
            route.fulfill(json={'success':True, 'waiting':action=='wait',
                                'message':'保留任务，等待冷却结束后自动重试' if action=='wait' else '已确认跳过本地冷却，仅尝试一次'})
        else:
            route.fulfill(json={'success':False,'code':'WECHAT_COOLDOWN','cooldown':info,'prepared':True})
    page.route('**/api/videos/**/process*', route)
    yield page, state


def execute(page):
    button = page.locator('#row-first button[onclick*="processVideoNow"]')
    button.click()
    expect(page.locator('#manual-cooldown-confirm')).to_be_visible()
    return button


def test_cancel_escape_and_focus_never_issue_force(cooldown_page):
    page, state = cooldown_page
    button = execute(page)
    dialog = page.get_by_role('dialog', name='视频号账号正在冷却')
    expect(dialog.get_by_text('视频号返回限流（-360）', exact=True)).to_be_visible()
    expect(dialog.get_by_role('button',name='取消',exact=True)).to_be_focused()
    expect(button).to_be_disabled()
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    expect(button).to_be_enabled()
    expect(button).to_be_focused()
    assert state['process_requests'] == [{}]
    execute(page)
    page.get_by_role('button',name='取消',exact=True).click()
    assert state['process_requests'] == [{},{}]


def test_wait_keeps_task_and_sends_no_force(cooldown_page):
    page, state = cooldown_page
    execute(page)
    page.get_by_role('button', name='等待自动重试', exact=True).click()
    expect(page.locator('#manual-cooldown-confirm')).not_to_be_visible()
    expect(page.locator('#toast-container')).to_contain_text('等待冷却结束后自动重试')
    assert state['process_requests'] == [{}, {'cooldown_action':['wait'],'cooldown_version':['current']}]


def test_force_sends_exactly_one_scoped_request(cooldown_page):
    page, state = cooldown_page
    execute(page)
    page.get_by_role('button', name='跳过冷却，执行一次', exact=True).click()
    expect(page.locator('#toast-container')).to_contain_text('仅尝试一次')
    assert state['process_requests'] == [{}, {'cooldown_action':['force'],'cooldown_version':['current']}]


def test_changed_cooldown_requires_second_confirmation(cooldown_page):
    page, state = cooldown_page; state['changed'] = True
    execute(page)
    page.get_by_role('button', name='跳过冷却，执行一次', exact=True).click()
    expect(page.locator('#manual-cooldown-confirm')).to_be_visible()
    expect(page.get_by_role('button',name='取消',exact=True)).to_be_focused()
    assert len(state['process_requests']) == 2
    page.get_by_role('button', name='取消', exact=True).click()
    assert len(state['process_requests']) == 2


def test_force_failure_is_visible_and_does_not_retry(cooldown_page):
    page, state = cooldown_page; state['force_error'] = True
    button = execute(page)
    page.get_by_role('button', name='跳过冷却，执行一次', exact=True).click()
    expect(page.locator('#toast-container')).to_contain_text('执行者不可用')
    expect(button).to_be_enabled()
    assert len(state['process_requests']) == 2
    # 此用例的预期 503 会生成浏览器网络错误，非 JS 故障。
    state['warnings'][:] = [w for w in state['warnings'] if '503' not in w]


@pytest.mark.parametrize('width,theme', [(1366,'dark'),(390,'light'),(390,'contrast')])
def test_theme_mobile_keyboard_and_screenshot(cooldown_page, width, theme):
    page, state = cooldown_page
    page.set_viewport_size(dict(width=width,height=844))
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
    execute(page)
    dialog = page.locator('#manual-cooldown-confirm')
    expect(dialog).to_be_visible()
    box = dialog.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.keyboard.press('Tab')
    expect(dialog.get_by_role('button',name='等待自动重试',exact=True)).to_be_focused()
    folder = Path(__file__).resolve().parents[2] / 'output/test-evidence/manual-cooldown'
    folder.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(folder / f'cooldown-{width}-{theme}.png'))
    page.keyboard.press('Escape')

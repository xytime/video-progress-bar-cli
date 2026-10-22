"""真实 Chromium + 本地 API + SQLite 验收；平台提交在管线边界替身。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.0.0 | 2026-10-22 | Codex | 等待恢复替代单次跳过，验证手机布局和刷新后真实状态。 |
"""
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from tests.browser_fixtures import chromium, dashboard
from tests.unit.test_execution_recovery import setup
from video_processing.core import wechat_request_guard as guards
from video_processing.utils.execution_recovery import dispatch_recovery_once
from web import app as web


@pytest.fixture
def recovery_page(dashboard, setup):
    page, state = dashboard
    db, manager, guard, calls = setup
    # 页面夹具的 first 行与真实数据库任务统一身份。
    db.add_video('first', '低分人工任务', 'channel', score=20, source='MANUAL')
    db.mark_video_ready_for_publication('first')
    guard.record_limited(endpoint='/post/post_list')
    client = TestClient(web.app)
    writes = []
    def api(route):
        parsed = urlsplit(route.request.url)
        path = parsed.path + ('?' + parsed.query if parsed.query else '')
        if route.request.method == 'POST': writes.append(path)
        response = client.request(route.request.method, path)
        route.fulfill(status=response.status_code, json=response.json())
    page.route('**/api/execution-recovery**', api)
    page.route('**/api/videos/**/process*', api)
    yield page, state, db, manager, guard, calls, writes
    client.close()


def execute(page):
    button = page.locator('#row-first button[onclick*="processVideoNow"]')
    button.click()
    expect(page.get_by_role('dialog', name='执行与恢复状态')).to_be_visible()
    return button


def test_cancel_and_escape_do_not_register(recovery_page):
    page, _, db, _, _, calls, writes = recovery_page
    button = execute(page)
    expect(page.get_by_role('button', name='取消', exact=True)).to_be_focused()
    expect(page.get_by_role('button', name='跳过冷却，执行一次', exact=True)).to_have_count(0)
    page.keyboard.press('Escape')
    expect(button).to_be_enabled()
    expect(button).to_be_focused()
    assert not db.execution_recovery('first') and not calls
    assert len(writes) == 1


def test_wait_reload_and_actual_dispatch_state(recovery_page):
    page, _, db, manager, guard, calls, writes = recovery_page
    execute(page)
    page.get_by_role('button', name='恢复后执行此任务', exact=True).click()
    expect(page.locator('#toast-container')).to_contain_text('已登记等待恢复')
    rid = db.execution_recovery('first')['id']
    page.reload()
    page.locator('#execution-recovery-panel summary').click()
    expect(page.locator('[data-recovery-content]')).to_contain_text('等待恢复')
    # 再次点击仅回读同一请求，不再次入队或执行。
    page.locator('#row-first button[onclick*="processVideoNow"]').click()
    expect(page.locator('#manual-cooldown-confirm')).to_have_count(0)
    assert db.execution_recovery('first')['id'] == rid
    assert dispatch_recovery_once(manager) == 0
    with patch.object(guards.time, 'time', return_value=guard.cooldown()['until'] + 1):
        assert dispatch_recovery_once(manager) == 1
        assert dispatch_recovery_once(manager) == 0
    page.locator('[data-recovery-refresh]').click()
    expect(page.locator('[data-recovery-content]')).to_contain_text('已结束')
    expect(page.locator('[data-recovery-content]')).to_contain_text('UNDER_REVIEW')
    assert calls == ['first']
    assert sum('/api/execution-recovery/first' in p for p in writes) == 1


@pytest.mark.parametrize('width,theme', [(1366,'dark'),(390,'light'),(390,'contrast'),(320,'dark')])
def test_mobile_keyboard_and_screenshot(recovery_page, width, theme):
    page, _, db, _, _, _, _ = recovery_page
    page.set_viewport_size(dict(width=width,height=844))
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
    execute(page)
    dialog = page.locator('#manual-cooldown-confirm')
    box = dialog.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.keyboard.press('Tab')
    expect(dialog.get_by_role('button', name='恢复后执行此任务', exact=True)).to_be_focused()
    assert dialog.get_by_role('button', name='恢复后执行此任务').bounding_box()['height'] >= 44 or width > 650
    folder = Path(__file__).resolve().parents[2] / 'output/test-evidence/execution-recovery'
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / f'dialog-{width}-{theme}.png'))
    page.keyboard.press('Enter')
    expect(dialog).not_to_be_visible()
    page.locator('#execution-recovery-panel summary').click()
    expect(page.locator('[data-recovery-content]')).to_contain_text('等待恢复')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    toast = page.locator('#toast-container .toast-item').last
    expect(toast).to_be_visible()
    toast_box = toast.bounding_box()
    assert toast_box['x'] >= 0 and toast_box['x'] + toast_box['width'] <= width
    assert toast.evaluate("el => getComputedStyle(el).whiteSpace") == 'normal'
    page.screenshot(path=str(folder / f'panel-{width}-{theme}.png'))

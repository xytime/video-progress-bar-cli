"""全局 header 的维护闭锁、确认取消及手机布局；所有业务请求均为隔离回执。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 全分区入口、读取故障、重复任务、确认及主题重排 |
"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from web import app as web_app


@pytest.fixture
def header_page(chromium):
    client = TestClient(web_app.app, base_url='http://127.0.0.1:9100')
    page = chromium.new_page(viewport=dict(width=1366, height=900))
    state = dict(mode='MAINTENANCE', login='expired', scan=False, offline=False, writes=[], errors=[])
    page.on('pageerror', lambda error: state['errors'].append(str(error)))
    def route(route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method != 'GET':
            state['writes'].append(path)
            route.fulfill(json={'started': True, 'success': True, 'message': '隔离任务受理'})
            return
        if path == '/api/console/header':
            route.fulfill(status=503 if state['offline'] else 200, json={
                'state': state['mode'], 'reason': '界面审查',
                'channel_scan': {'running': state['scan'], 'outcome': 'idle'}})
        elif path == '/api/wechat/status':
            route.fulfill(json={'login_flow_active': state['login'] == 'active',
                                'status_label': '授权已过期' if state['login'] == 'expired' else '状态未知'})
        elif path == '/api/high-likes/status':
            route.fulfill(json={'running': False})
        else:
            url = urlsplit(request.url)
            response = client.get(path + ('?' + url.query if url.query else ''))
            route.fulfill(status=response.status_code, body=response.content, headers=dict(response.headers))
    page.route('**/*', route)
    page.goto('http://127.0.0.1:9100/?view=topics&tab=high_likes')
    expect(page.locator('#header-runtime-state')).to_have_text('维护中')
    page.evaluate('clearTimeout(refreshTimeoutId); scheduleNextRefresh=()=>{}')
    yield page, state
    page.close(); client.close()
    assert not state['errors']


def test_maintenance_menus_and_all_workspace_sections(header_page):
    page, state = header_page
    for section in ('overview', 'topics', 'production', 'publications', 'operations'):
        page.locator(f'.console-primary[data-section={section}]').click()
        expect(page.get_by_text('扫描视频源', exact=True)).to_be_visible()
        expect(page.locator('#btn-wechat-login')).to_be_visible()
        expect(page.locator('#btn-wechat-login')).to_be_disabled()
        expect(page.locator('#header-wechat-state')).to_contain_text('授权已过期')
    page.locator('#header-scan-menu summary').click()
    for id in ('btn-scan-channels', 'btn-scan-engagement'):
        expect(page.locator('#' + id)).to_be_visible()
        expect(page.locator('#' + id)).to_be_disabled()
    page.keyboard.press('Escape')
    expect(page.locator('#header-scan-menu summary')).to_be_focused()
    page.locator('#header-more-menu summary').click()
    expect(page.locator('#btn-run-pipeline')).to_be_disabled()
    expect(page.locator('#ai-audit-mini')).to_be_visible()
    assert state['writes'] == []


def test_unknown_status_closes_confirmation_and_prevents_actions(header_page):
    page, state = header_page
    state['mode'] = 'RUNNING'
    page.evaluate('ConsoleHeader.refresh()')
    page.locator('#header-more-menu summary').click()
    page.locator('#btn-run-pipeline').click()
    expect(page.locator('#header-pipeline-confirm')).to_be_visible()
    expect(page.locator('#header-pipeline-cancel')).to_be_focused()
    assert not state['writes']
    page.keyboard.press('Escape')
    expect(page.locator('#header-pipeline-confirm')).not_to_be_visible()
    page.locator('#btn-run-pipeline').click()
    state['offline'] = True
    page.evaluate('ConsoleHeader.refresh()')
    expect(page.locator('#header-pipeline-confirm')).not_to_be_visible()
    expect(page.locator('#btn-run-pipeline')).to_be_disabled()
    expect(page.locator('#header-operation-feedback')).to_contain_text('读取失败')
    assert not state['writes']


def test_isolated_scan_and_duplicate_login(header_page):
    page, state = header_page
    state.update(mode='RUNNING', login='active', scan=True)
    page.evaluate('ConsoleHeader.refresh()')
    expect(page.locator('#btn-wechat-login')).to_be_disabled()
    page.locator('#header-scan-menu summary').click()
    expect(page.locator('#btn-scan-channels')).to_be_disabled()
    state.update(scan=False, login='expired')
    page.evaluate('ConsoleHeader.refresh()')
    page.locator('#btn-scan-channels').click()
    expect(page.locator('#btn-scan-channels')).to_be_disabled()
    expect(page.locator('#header-operation-feedback')).to_have_text('隔离任务受理')
    assert state['writes'] == ['/api/console/scan-channels']


@pytest.mark.parametrize('theme,size', [('dark','standard'), ('light','large'), ('contrast','standard')])
def test_mobile_header_open_menus_and_theme(header_page, theme, size):
    page, state = header_page
    page.set_viewport_size(dict(width=390, height=844))
    page.locator('#btn-toggle-preferences').click()
    page.locator('#display-theme').select_option(theme)
    # 使用主题测试及原工作台字号重排回归。
    page.locator('#header-scan-menu summary').click()
    expect(page.locator('#btn-scan-channels')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#workspace-title').bounding_box()['x'] < 40
    folder = Path(__file__).resolve().parents[2] / 'output/test-evidence/console-header'
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / f'mobile-{theme}.png'), full_page=True)
    assert not state['writes']


def test_pipeline_submits_only_after_explicit_confirmation(header_page):
    page, state = header_page
    state['mode'] = 'RUNNING'
    page.evaluate('ConsoleHeader.refresh()')
    page.locator('#header-more-menu summary').click()
    page.locator('#btn-run-pipeline').click()
    expect(page.locator('#header-pipeline-confirm')).to_be_visible()
    assert not state['writes']
    page.locator('#header-pipeline-submit').click()
    expect(page.locator('#header-operation-feedback')).to_contain_text('完整流水线请求已受理')
    assert state['writes'] == ['/api/pipeline/run']

"""全局 header 的维护闭锁、确认取消及手机布局；所有业务请求均为隔离回执。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 全分区入口、读取故障、重复任务、确认及主题重排 |
| 1.1.0 | 2026-10-25 | Codex | 新增高互动刷新回执、零新增原因与刷新后恢复验证 |
"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from web import app as web_app
from web.high_likes_refresh import result_message


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
                                'status_label': '授权已过期' if state['login'] == 'expired' else '状态未知',
                                'authorization_relative_age': '2小时前',
                                'authorization_time_bj': '2026-10-20 16:00:00 BJ'})
        elif path == '/api/high-likes/status':
            route.fulfill(status=503 if state.get('engagement_offline') else 200,
                          json=state.get('engagement', {'running': False}))
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
        expect(page.locator('#header-wechat-age')).to_have_text('上次授权：2小时前')
        expect(page.locator('#header-wechat-age')).to_have_attribute('title', '上次授权：2026-10-20 16:00:00 BJ（本地记录）')
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


def set_refresh_result(state, *, outcome='complete', report=None):
    result = dict(run_id='isolated-refresh', outcome=outcome,
                  report=report or {'added': 0, 'duplicates': 10}, destination='high_likes')
    result['message'] = result_message(result)
    state['engagement'] = dict(running=outcome == 'running', result=result)
    return result['message']


@pytest.mark.parametrize('button', ['btn-scan-engagement', 'btn-refresh-high-likes'])
def test_refresh_reports_count_destination_and_preserves_filters(header_page, button):
    page, state = header_page
    state['mode'] = 'RUNNING'
    page.goto('http://127.0.0.1:9100/?view=topics&tab=high_likes&channel=Wall+Street+Truthbombs&created_window=24h')
    page.evaluate('ConsoleHeader.refresh()')
    before = page.evaluate('({channel:filterState.channel,createdWindow:filterState.createdWindow})')
    assert before == {'channel': 'Wall Street Truthbombs', 'createdWindow': '24h'}
    if button == 'btn-scan-engagement':
        page.locator('#header-scan-menu summary').click()
    page.locator('#' + button).click()
    expect(page.locator('#header-operation-feedback')).to_have_text('隔离任务受理')
    expect(page.locator('#' + button)).to_be_disabled()
    assert state['writes'] == ['/api/high-likes/refresh']
    set_refresh_result(state, outcome='running', report={'added': 2})
    page.evaluate('ConsoleHeader.refresh({quiet:true})')
    expect(page.locator('#high-likes-refresh-status')).to_contain_text('已新增 2 条')
    expect(page.locator('#btn-refresh-high-likes')).to_be_disabled()
    message = set_refresh_result(state, report={'added': 13, 'duplicates': 7, 'completed': 2})
    page.evaluate('ConsoleHeader.refresh({quiet:true})')
    expect(page.locator('#header-operation-feedback')).to_have_text(message)
    expect(page.locator('#high-likes-refresh-status')).to_have_text(message)
    expect(page.locator('#high-likes-refresh-status')).to_have_attribute('role', 'status')
    assert '新增 13 条' in message and '素材进入「近期高互动」' in message
    assert page.evaluate('({channel:filterState.channel,createdWindow:filterState.createdWindow})') == before
    expect(page.locator('#btn-refresh-high-likes')).to_be_enabled()
    folder = Path(__file__).resolve().parents[2] / 'output/test-evidence/high-likes-refresh'
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / f'desktop-{button}.png'), full_page=True)
    page.evaluate('ConsoleHeader.refresh({quiet:true})')
    expect(page.locator('#header-operation-feedback')).to_have_text(message)
    page.reload()
    expect(page.locator('#header-operation-feedback')).to_have_text(message)
    assert state['writes'] == ['/api/high-likes/refresh']


@pytest.mark.parametrize('outcome,report,phrase', [
    ('complete', {'added': 0, 'duplicates': 10}, '已有记录 10 条'),
    ('complete', {'added': 0, 'low_views': 5, 'outdated': 2}, '观看量未超过 500'),
    ('error', {'added': 0, 'failed': 2, 'timeouts': 1}, '搜索超时 1 组'),
    ('partial', {'added': 1, 'failed': 1}, '部分完成'),
    ('interrupted', {'added': 3}, '最终新增数量尚未核实'),
])
def test_refresh_failure_and_empty_feedback_reflows_on_mobile(header_page, outcome, report, phrase):
    page, state = header_page
    state['mode'] = 'RUNNING'
    message = set_refresh_result(state, outcome=outcome, report=report)
    page.evaluate('ConsoleHeader.refresh()')
    expect(page.locator('#header-operation-feedback')).to_have_text(message)
    assert phrase in message
    page.set_viewport_size(dict(width=390, height=844))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    box = page.locator('#high-likes-refresh-status').bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 390
    folder = Path(__file__).resolve().parents[2] / 'output/test-evidence/high-likes-refresh'
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / f'mobile-{outcome}-{phrase[:4]}.png'), full_page=True)
    assert not state['writes']


def test_refresh_status_failure_disables_repeat_until_readback(header_page):
    page, state = header_page
    state.update(mode='RUNNING', engagement_offline=True)
    page.evaluate('ConsoleHeader.refresh()')
    expect(page.locator('#btn-refresh-high-likes')).to_be_disabled()
    expect(page.locator('#high-likes-refresh-status')).to_contain_text('状态读取失败')
    expect(page.locator('#header-operation-feedback')).to_contain_text('新增结果尚未核实')
    expect(page.locator('#header-status-retry')).to_be_visible()
    state['engagement_offline'] = False
    message = set_refresh_result(state)
    page.locator('#header-status-retry').click()
    expect(page.locator('#header-operation-feedback')).to_have_text(message)
    expect(page.locator('#btn-refresh-high-likes')).to_be_enabled()
    assert not state['writes']

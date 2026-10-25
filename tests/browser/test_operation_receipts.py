"""HTTPS Origin、真实 FastAPI/SQLite 和 Chromium 的回执闭环；网络与生产隔离。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-25 | Codex | 授权成功/403/响应丢失只读恢复、认证状态和移动端焦点闭环。 |
"""
from urllib.parse import urlsplit
import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from video_processing.db.database import PipelineDB
from video_processing.censorship_service import CensorshipService


@pytest.fixture
def console(chromium, tmp_path, monkeypatch):
    import web.app as dashboard
    import video_processing.utils.agy_background_auth as auth
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    db.add_video('subject', 'Obama responds to Republican attacks', 'channel', score=100)
    monkeypatch.setattr(dashboard, 'db', db)
    monkeypatch.setattr(dashboard, '_OUT_DIR', tmp_path)
    monkeypatch.setattr(dashboard.settings, 'dashboard_review_public_origin', 'https://v.optionbank.us')
    monkeypatch.setattr(dashboard.settings, 'enable_channel_policy_filter', True)
    monkeypatch.setattr(dashboard.settings, 'enable_censorship_engine', True)
    assert CensorshipService(db, lambda _: None).check('subject', 'Obama responds', 'Donald Trump re-election')
    state = dict(posts=0, mode='normal', errors=[], starts=0)
    def start(_): state['starts'] += 1
    monkeypatch.setattr(dashboard, '_trigger_video_async', start)
    monkeypatch.setattr(auth, 'require_auth', lambda *a, **k: None)
    client = TestClient(dashboard.app, base_url='http://v.optionbank.us', client=('127.0.0.1', 50000))
    page = chromium.new_page(viewport={'width':1366, 'height':900})
    page.on('pageerror', lambda error: state['errors'].append(str(error)))
    def route(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'v.optionbank.us': route.fulfill(status=204); return
        headers = dict(request.headers)
        is_approval = url.path.endswith('/bypass-censor') and request.method == 'POST'
        if is_approval:
            state['posts'] += 1
            if state['mode'] == 'reject': headers['origin'] = 'https://attacker.invalid'
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
            headers=headers, content=request.post_data_buffer)
        if is_approval and state['mode'] == 'lost': route.abort(); return
        route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
    page.route('**/*', route)
    page.goto('https://v.optionbank.us/?tab=error&created_window=all&search=subject')
    yield page, state, db
    page.close(); client.close()
    assert not state['errors']


def open_approval(page):
    page.get_by_role('button', name='🔓 复核放行', exact=True).first.click()
    expect(page.locator('#btn-confirm-bypass')).to_be_enabled()


def test_authorization_success_stays_visible_and_survives_reload(console):
    page, state, db = console
    open_approval(page); page.locator('#btn-confirm-bypass').click()
    expect(page.locator('#bypass-feedback')).to_contain_text('授权已保存 · 回执 #')
    expect(page.locator('#bypass-feedback')).to_contain_text('（北京时间）')
    expect(page.locator('#btn-confirm-bypass')).to_be_disabled()
    expect(page.locator('#bypass-modal')).to_be_visible()
    page.locator('#btn-check-bypass-receipt').click()
    expect(page.locator('#bypass-feedback')).to_contain_text('输入指纹：')
    assert state['posts'] == state['starts'] == 1
    page.reload()
    result = db.get_censorship_incidents('subject')[0]
    assert result['decision'] == 'MANUAL_CP_APPROVED'
    page.goto('https://v.optionbank.us/?tab=active&created_window=all&search=subject')
    page.get_by_role('button', name='授权回执', exact=True).first.click()
    expect(page.locator('#operation-receipt-content')).to_contain_text('授权已保存 · 回执 #')
    page.keyboard.press('Escape')


@pytest.mark.parametrize('mode,saved', [('reject',False),('lost',True)])
def test_failed_response_never_reposts_and_readback_resolves_result(console, mode, saved):
    page, state, db = console; state['mode'] = mode
    open_approval(page); page.locator('#btn-confirm-bypass').click()
    expect(page.locator('#bypass-feedback')).to_contain_text('核实授权结果')
    expect(page.locator('#btn-confirm-bypass')).to_be_disabled()
    page.locator('#btn-check-bypass-receipt').click()
    expect(page.locator('#bypass-feedback')).to_contain_text('授权已保存' if saved else '当前授权未确认保存')
    assert state['posts'] == 1 and state['starts'] == int(saved)
    assert bool(db.get_video_by_youtube_id('subject')['bypass_censorship']) is saved


@pytest.mark.parametrize('width', [390,1366])
def test_auth_status_recheck_mobile_and_keyboard(console, width):
    page, state, db = console
    page.set_viewport_size({'width':width,'height':844})
    expect(page.locator('#cover-auth-status')).to_have_text('封面登录待核实')
    page.locator('#cover-auth-status').click()
    expect(page.locator('#operation-receipt-content')).to_contain_text('封面服务已登录')
    expect(page.locator('#operation-receipt-content')).to_contain_text('最近检查：')
    assert page.locator('#operation-receipt-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.keyboard.press('Escape')
    expect(page.locator('#cover-auth-status')).to_be_focused()
    assert not state['posts'] and not state['starts']

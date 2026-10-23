"""真实 Chromium、临时审计库验证平台题材复核完整闭环；平台触发替身。"""
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from tests.unit.test_social_unrest_review import manager, vtt
from web import app as web_app


@pytest.fixture
def flow(chromium, manager, monkeypatch):
    source = vtt(manager._OUT_DIR, 'Protesters march over fuel costs.')
    assert manager._check_censorship('unrest', 'Daily technology update', stage='source_subtitle_preflight')
    source.write_text(source.read_text().replace('fuel costs', 'rising prices'))
    monkeypatch.setattr(web_app, 'db', manager.db)
    monkeypatch.setattr(web_app, '_OUT_DIR', manager._OUT_DIR)
    trigger = Mock()
    monkeypatch.setattr(web_app, '_trigger_video_async', trigger)
    client = TestClient(web_app.app)
    page = chromium.new_page(viewport=dict(width=1280, height=900))
    state = dict(errors=[], writes=[], offline=False)
    page.on('pageerror', lambda err: state['errors'].append(str(err)))

    def handler(route):
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != '127.0.0.1':
            route.fulfill(status=404, body='隔离验收')
            return
        if req.method == 'POST':
            state['writes'].append(url.path)
            assert url.path.endswith(('/review-censor', '/bypass-censor'))
            if state['offline']:
                route.fulfill(status=503, json={'detail':'隔离故障，请重试'})
                return
        response = client.request(req.method, url.path + ('?' + url.query if url.query else ''),
                                  content=req.post_data, headers={'content-type':'application/json'})
        route.fulfill(status=response.status_code, body=response.content, headers=dict(response.headers))

    page.route('**/*', handler)
    page.goto('http://127.0.0.1:9100/?tab=error&created_window=all')
    expect(page.locator('.btn-bypass')).to_be_visible()
    page.evaluate('clearTimeout(refreshTimeoutId); scheduleNextRefresh=()=>{}')
    yield page, manager, source, trigger, state
    page.close()
    client.close()
    assert not state['errors']


@pytest.mark.parametrize('width', [1280, 390])
def test_unavailable_rereview_bound_approval_and_keyboard(flow, width):
    page, manager, source, trigger, state = flow
    page.set_viewport_size(dict(width=width, height=900))
    original = manager.db.get_video_by_youtube_id('unrest')
    page.locator('.btn-bypass').click()
    expect(page.locator('#bypass-evidence')).to_contain_text('须重新审查')
    expect(page.locator('#btn-confirm-bypass')).to_be_disabled()
    expect(page.locator('#btn-rereview-censor')).to_be_visible()
    assert page.locator('#bypass-modal').evaluate('el => el.matches(":modal")')
    page.keyboard.press('Escape')
    expect(page.locator('#bypass-modal')).not_to_be_visible()
    expect(page.locator('.btn-bypass')).to_be_focused()
    page.locator('.btn-bypass').click()
    page.locator('#btn-rereview-censor').click()
    expect(page.locator('#bypass-feedback')).to_contain_text('重新审查完成')
    expect(page.locator('#bypass-evidence')).to_contain_text('真实命中')
    expect(page.locator('#bypass-evidence')).to_contain_text('输入指纹')
    expect(page.locator('#btn-confirm-bypass')).to_be_enabled()
    assert manager.db.get_video_by_youtube_id('unrest') == original
    trigger.assert_not_called()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#bypass-modal > div').evaluate('el=>el.scrollWidth<=el.clientWidth')
    folder = Path('output/test-evidence/social-unrest-review')
    folder.mkdir(parents=True, exist_ok=True)
    box = page.locator('#btn-confirm-bypass').bounding_box()
    assert box['y'] >= 0 and box['y'] + box['height'] <= 900
    page.screenshot(path=str(folder / f'verified-{width}.png'))
    # 两次同步点击只有一次 POST，服务端随后也拒绝重复状态恢复。
    page.evaluate('confirmBypass(); confirmBypass()')
    expect(page.locator('#bypass-modal')).not_to_be_visible()
    trigger.assert_called_once()
    assert state['writes'].count('/api/videos/unrest/bypass-censor') == 1


def test_error_recovery_stale_evidence_and_close_during_load(flow):
    page, manager, source, trigger, state = flow
    page.locator('.btn-bypass').click()
    expect(page.locator('#btn-rereview-censor')).to_be_enabled()
    state['offline'] = True
    page.locator('#btn-rereview-censor').click()
    expect(page.locator('#bypass-feedback')).to_contain_text('隔离故障')
    expect(page.locator('#btn-confirm-bypass')).to_be_disabled()
    state['offline'] = False
    page.locator('#btn-rereview-censor').click()
    expect(page.locator('#btn-confirm-bypass')).to_be_enabled()
    source.write_text(source.read_text().replace('rising prices', 'new conditions'))
    page.locator('#btn-confirm-bypass').click()
    expect(page.locator('#bypass-feedback')).to_contain_text('重新审查')
    expect(page.locator('#btn-confirm-bypass')).to_be_disabled()
    trigger.assert_not_called()
    page.keyboard.press('Escape')
    # 关闭后到达的旧响应不得重新启用已关闭弹窗。
    page.evaluate('''() => {
      const actual = window.fetch;
      window.fetch = async (...args) => {
        const result = await actual(...args);
        if (String(args[0]).includes('censor-keywords')) await new Promise(r=>setTimeout(r,100));
        return result;
      };
      openBypassModal('unrest'); closeBypassModal();
    }''')
    expect(page.locator('#bypass-modal')).not_to_be_visible()
    page.wait_for_timeout(150)
    expect(page.locator('#btn-confirm-bypass')).to_be_disabled()

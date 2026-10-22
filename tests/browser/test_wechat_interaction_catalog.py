"""目录发现的真实 Chromium 写路由隔离验收。"""
import json
from pathlib import Path
import pytest
from video_processing.interaction.browser_commenter import BrowserCommenter


def test_catalog_branch_blocks_writes_and_never_opens_editor(tmp_path, monkeypatch):
    from config.settings import settings
    root = Path(__file__).resolve().parents[2]
    marker = json.loads((root / '.test-sandbox.json').read_text())
    state = tmp_path / 'state.json'
    state.write_text('{"cookies": [], "origins": []}')
    monkeypatch.setattr(settings, 'wechat_account_scheduler_enabled', False)
    adapter = BrowserCommenter(state_path=state, browser_executable_path=marker['browser']['executable'])
    attempted = []

    def open_page(page, before_navigation, **kwargs):
        before_navigation()
        def fixture_route(route):
            if route.request.is_navigation_request():
                route.fulfill(content_type='text/html', body='<html><body>catalog fixture</body></html>')
            else:
                route.fallback()
        page.route('**/*', fixture_route)
        page.goto('https://channels.weixin.qq.com/platform/interaction/comment')
        return None

    def load_catalog(page, post_id, description, ids, descriptions):
        assert post_id is None
        attempted.append(page.evaluate("""async () => {
            try { await fetch('/cgi-bin/mmfinderassistant-bin/comment/create_comment',
                               {method:'POST',body:'{}'}); return 'sent'; }
            catch (_) { return 'blocked'; }
        }"""))
        ids.append('export/observed')
        descriptions['export/observed'] = '完整目录文案'

    monkeypatch.setattr(adapter, '_open_comment_page', open_page)
    monkeypatch.setattr(adapter, '_load_target_page', load_catalog)
    result = adapter._run_browser(comment_text='', platform_post_id='export/anchor',
                                  video_title=None, attempt_dir=tmp_path,
                                  before_submit=lambda: pytest.fail('catalog must never submit'),
                                  verify_only=True, catalog_only=True)
    assert result[0] == 'CATALOG_OBSERVED'
    assert attempted == ['blocked']
    receipt = json.loads((tmp_path / 'receipt.json').read_text())
    assert receipt['observed_posts'] == {'export/observed': '完整目录文案'}
    assert receipt['clicked'] is False

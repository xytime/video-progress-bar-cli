"""真实 Chromium 与临时 DB 验证只读证据、P0 保护及读取故障，不连接生产。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-10-23 | Codex | 只读断言区分测试主动恢复标题导致的更新时间，避免跨秒误报。 |
| 1.0.0 | 2026-10-17 | Codex | 三主题桌面/手机证据与错误清理、原文注入及双确认验收。 |
"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from tests.unit.test_censorship_evidence import FIXTURE, evidence_fixture
from video_processing.censorship_service import CensorshipService
from video_processing.db.database import PipelineDB
from video_processing.utils.file_utils import read_webvtt_text
from web import app as web_app


@pytest.fixture
def review(chromium, tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / 'review.db'))
    video, _, _ = evidence_fixture()
    # 字幕中的 HTML 形似文本须作为文字显示，不能执行。
    vtt = FIXTURE.read_text().replace('killed', 'killed &lt;img src=x onerror=window.evidenceInjection=true&gt;', 1)
    source = tmp_path / 'review-case_source_subtitle.en.vtt'
    source.write_text(vtt)
    subtitle = read_webvtt_text([source])
    db.add_video('review-case', video['title'], 'UC-review', score=85, source='KEYWORD')
    monkeypatch.setattr(web_app.settings, 'enable_censorship_engine', True)
    monkeypatch.setattr(web_app.settings, 'enable_channel_policy_filter', False)
    monkeypatch.setattr(web_app.settings, 'enable_blacklist_tombstone', True)
    CensorshipService(db, lambda _: None).check('review-case', **video, subtitle_text=subtitle,
                                              stage='source_subtitle_preflight')
    original = db.get_video_by_youtube_id('review-case')
    monkeypatch.setattr(web_app, 'db', db)
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    client = TestClient(web_app.app, base_url='http://127.0.0.1:9100', client=('127.0.0.1', 50000))
    page = chromium.new_page(viewport=dict(width=1280, height=900))
    state = dict(offline=False, writes=[], errors=[])
    page.on('pageerror', lambda error: state['errors'].append(str(error)))

    def route_handler(route):
        req = route.request
        url = urlsplit(req.url)
        if req.method != 'GET':
            state['writes'].append(req.url)
            route.fulfill(status=500, json={'detail': '验收禁止写入'})
        elif state['offline'] and url.path.endswith('/censor-keywords'):
            route.fulfill(status=503, json={'error': '隔离故障'})
        elif url.hostname != '127.0.0.1':
            route.fulfill(status=404, body='离线验收')
        else:
            response = client.get(url.path + ('?' + url.query if url.query else ''))
            if url.path.endswith('/censor-keywords') and response.status_code == 200:
                data = response.json()
                # 生产标签云会包含长规则名；需覆盖真实手机最小宽度。
                data['keywords'].insert(0, {'word': 'china_sensitive_negative_news', 'weight': 100, 'flagged': True})
                route.fulfill(status=200, json=data)
            else:
                route.fulfill(status=response.status_code, body=response.content, headers=dict(response.headers))

    page.route('**/*', route_handler)
    yield page, state, db
    page.close()
    client.close()
    assert not state['writes'] and not state['errors']
    assert db.get_video_by_youtube_id('review-case') == {**original, 'updated_at': state.get('intentional_updated_at', original['updated_at'])}
    assert db.is_blacklisted('review-case') and not db.has_manual_p0_approval('review-case')


def open_review(page):
    page.goto('http://127.0.0.1:9100/?tab=error&created_window=all')
    expect(page.locator('.btn-bypass')).to_be_visible()
    page.evaluate('clearTimeout(refreshTimeoutId); scheduleNextRefresh=()=>{}')
    page.locator('.btn-bypass').click()
    expect(page.locator('#bypass-evidence')).to_contain_text('只读复核')


@pytest.mark.parametrize('theme', ['dark', 'light', 'contrast'])
def test_actual_evidence_responsive_and_p0_unchanged(review, theme):
    page, state, db = review
    page.add_init_script('localStorage.setItem("vp-display-preferences",' +
                         repr('{"theme":"' + theme + '","size":"standard"}') + ')')
    for width, height in [(1280, 900), (390, 844)]:
        page.set_viewport_size(dict(width=width, height=height))
        open_review(page)
        evidence = page.locator('#bypass-evidence')
        for text in ['China', 'killed', '00:06:21.280', '00:06:23.699', '87 ≤ 240',
                     'china_sensitive_negative_news', '1910', '规则版本']:
            expect(evidence).to_contain_text(text)
        assert page.locator('#bypass-evidence img').count() == 0
        expect(evidence).to_contain_text('<img src=x onerror=window.evidenceInjection=true>')
        assert not page.evaluate('Boolean(window.evidenceInjection)')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert evidence.evaluate('el=>el.scrollWidth<=el.clientWidth')
        assert page.locator('#bypass-cloud').evaluate('el=>el.scrollWidth<=el.clientWidth')
        assert page.locator('#bypass-modal > div').evaluate('el=>el.scrollWidth<=el.clientWidth')
        button = page.locator('#btn-confirm-bypass')
        expect(button).to_be_disabled()
        page.locator('#bypass-p0-review-checkbox').check()
        expect(button).to_be_disabled()
        page.locator('#bypass-p0-resume-checkbox').check()
        expect(button).to_be_enabled()
        # 留证前恢复双确认未勾选，不触发放行。
        page.locator('#bypass-p0-review-checkbox').uncheck()
        page.locator('#bypass-p0-resume-checkbox').uncheck()
        evidence.scroll_into_view_if_needed()
        folder = Path('output/test-evidence/censorship-evidence')
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / f'evidence-{theme}-{width}.png'), full_page=True)
        page.locator('#bypass-modal button').filter(has_text='取消').click()


def test_failed_and_missing_evidence_do_not_leave_old_hit(review):
    page, state, db = review
    open_review(page)
    page.locator('#bypass-modal button').filter(has_text='取消').click()
    state['offline'] = True
    page.locator('.btn-bypass').click()
    expect(page.locator('#bypass-evidence')).to_have_text('读取失败，暂无可核实证据。')
    expect(page.locator('#btn-confirm-bypass')).to_be_disabled()
    expect(page.locator('#bypass-evidence')).not_to_contain_text('China')
    page.locator('#bypass-modal button').filter(has_text='取消').click()
    state['offline'] = False
    # 送审后原始输入改变，只显示不可核实，不混用当前扫描。
    original_title = db.get_video_by_youtube_id('review-case')['zh_title']
    db.update_video_zh_title('review-case', '送审后修改')
    page.locator('.btn-bypass').click()
    expect(page.locator('#bypass-evidence')).to_contain_text('与原审计输入不一致')
    expect(page.locator('#bypass-evidence')).not_to_contain_text('真实命中')
    expect(page.locator('#btn-confirm-bypass')).to_be_disabled()
    db.update_video_zh_title('review-case', original_title)
    state['intentional_updated_at'] = db.get_video_by_youtube_id('review-case')['updated_at']

"""评论回复分栏、筛选和策略表单的隔离 Chromium 验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-18 | Codex | 使用隔离 API 验证桌面、手机、竞态与草稿保护。 |
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from config.settings import settings
from tests.browser_fixtures import chromium
from web.secondary_reply_settings import create_secondary_reply_settings_router
from video_processing.utils.secondary_reply_policy import current_policy_from_settings, load_policy


@pytest.fixture
def isolated_reply_policy():
    original = current_policy_from_settings()
    # 真实保存接口会热更新单例；页面测试结束必须恢复全部策略字段。
    with pytest.MonkeyPatch.context() as restore:
        for key in original.keys() - {'schema_version'}:
            name = 'wechat_reply_' + key
            restore.setattr(settings, name, getattr(settings, name))
        yield original
    assert current_policy_from_settings() == original


@pytest.fixture
def ui(chromium, tmp_path, isolated_reply_policy):
    active = tmp_path / 'secondary-policy.json'
    import json
    active.write_text(json.dumps(isolated_reply_policy), encoding='utf-8')
    now = int(datetime.now(timezone.utc).timestamp())
    records = [dict(task_id=i, status=['APPROVED','VERIFIED','PENDING_REVIEW','UNCERTAIN','FAILED','SKIPPED','MANUAL'][i % 7],
                    nickname=f'观众{i}', comment_content=f'原评{i}：' + '完整长评论内容' * 30,
                    video_title=f'视频{i % 2}', platform_post_id=f'post{i % 2}',
                    comment_id=f'comment-{i}', comment_createtime=now-i*86400-60,
                    comment_like_count=i, created_at=f'2026-10-{i:02d} 01:00:00',
                    comment_discovered_at='2026-10-18 01:00:00', approved_at='2026-10-18 02:00:00',
                    verified_at='2026-10-18 03:00:00' if i % 7 == 1 else None,
                    platform_reply_comment_id=f'reply-{i}', chinese_reply=f'中文回复{i}',
                    english_reply=f'English response {i}', style='MACRO' if i % 2 else 'PRAGMATIC',
                    provider='manual_import' if i % 2 else 'codex', intent='交流', evidence_refs=['safe-proof'])
               for i in range(1,14)]
    records[-1]['nickname'] = '<img src=x onerror=alert(1)>'
    flags = dict(save_error=None, history_error=False, queries=[], writes=[], held=[])
    app = FastAPI()
    app.include_router(create_secondary_reply_settings_router(active=active, history_lookup=lambda limit: records[:limit]))
    root = Path(__file__).resolve().parents[2]
    app.mount('/static', StaticFiles(directory=root/'src/web/static'), name='static')
    client = TestClient(app)
    page = chromium.new_page(viewport=dict(width=1440,height=1000))
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route_handler(route):
        request = route.request
        url = urlparse(request.url)
        if request.method == 'PUT':
            flags['writes'].append(request.post_data_json)
            if flags['save_error']:
                route.fulfill(status=flags['save_error'], json=dict(detail='测试保存错误')); return
        if url.path.endswith('/history'):
            query = parse_qs(url.query); flags['queries'].append(query)
            if flags['history_error']:
                route.fulfill(status=503,json=dict(detail='测试记录读取失败')); return
            if flags.get('hold_search') == query.get('search',[''])[0]:
                flags['held'].append(route); return
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                  content=request.post_data, headers={'Content-Type':'application/json'})
        route.fulfill(status=response.status_code, body=response.content,
                      content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',route_handler)
    page.goto('http://reply-test.invalid/secondary-reply-settings')
    expect(page.locator('#editor')).to_be_enabled()
    expect(page.locator('#history-counts')).to_contain_text('共 13 条')
    yield page, active, flags
    page.close(); client.close()
    assert errors == []


def test_full_details_filters_sort_and_pagination(ui):
    page, _, _ = ui
    expect(page.locator('.sr-record')).to_have_count(10)
    expect(page.locator('#record-detail')).to_contain_text('English response 13')
    assert page.locator('#history-list img').count() == 0
    page.get_by_text('查看技术凭据',exact=True).click()
    expect(page.locator('#record-detail')).to_contain_text('comment-13')
    page.locator('#filter-size').select_option('5')
    expect(page.locator('.sr-record')).to_have_count(5)
    page.get_by_role('button',name='下一页',exact=True).click()
    expect(page.locator('#history-counts')).to_contain_text('第 2 / 3 页')
    page.locator('#filter-sort').select_option('likes_desc')
    expect(page.locator('.sr-record').first).to_contain_text('13 赞')
    page.locator('[data-status=VERIFIED]').click()
    expect(page.locator('#history-counts')).to_contain_text('共 2 条')
    page.locator('#btn-clear-filters').click()
    page.locator('#filter-other-status').select_option('INACTIVE')
    expect(page.locator('#history-counts')).to_contain_text('共 4 条')
    page.locator('#btn-clear-filters').click()
    page.locator('#filter-video').select_option('post1')
    page.locator('#filter-style').select_option('MACRO')
    page.locator('#filter-provider').select_option('manual')
    expect(page.locator('#history-counts')).to_contain_text('共 7 条')
    page.locator('#filter-time-window').select_option('24h')
    expect(page.locator('#history-counts')).to_contain_text('共 0 条')
    expect(page.locator('#history-feedback')).to_contain_text('全量统计')
    expect(page.locator('#history-list')).to_contain_text('清除筛选')
    page.locator('#btn-clear-filters').click()
    page.locator('#filter-search').fill('comment-12')
    expect(page.locator('#history-counts')).to_contain_text('共 1 条')
    expect(page.locator('#record-detail')).to_contain_text('中文回复12')
    assert 'comment-12' not in page.url
    page.locator('#clear-search').click()
    expect(page.locator('#history-counts')).to_contain_text('共 13 条')


def test_policy_validation_save_conflict_and_discard(ui):
    page, active, flags = ui
    original = load_policy(active)
    summary = page.locator('#saved-summary').text_content()
    page.locator('#edit-policy').click()
    page.locator('#hourly-quota').fill('2.5')
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('整数')
    assert flags['writes'] == []
    page.locator('#hourly-quota').fill('7')
    expect(page.locator('#saved-summary')).to_have_text(summary)
    expect(page.locator('#policy-preview')).to_contain_text('未保存草稿')
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('策略已保存')
    assert load_policy(active)['hourly_quota'] == 7
    assert load_policy(active)['schema_version'] == original['schema_version']
    page.locator('#hourly-quota').fill('8')
    flags['save_error'] = 503
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('草稿已保留')
    flags['save_error'] = 409
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('保存冲突')
    expect(page.locator('#save')).to_be_disabled()
    page.locator('#refresh-history').click()
    expect(page.locator('#feedback')).to_contain_text('保存冲突')
    expect(page.locator('#hourly-quota')).to_have_value('8')
    page.locator('#reload-policy').click()
    expect(page.locator('#keep-editing')).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.locator('#reload-policy')).to_be_focused()
    expect(page.locator('#hourly-quota')).to_have_value('8')
    page.locator('#reload-policy').click(); page.locator('#discard').click()
    expect(page.locator('#hourly-quota')).to_have_value('7')
    expect(page.locator('#save')).to_be_disabled()


def test_history_error_retry_search_race_and_ime(ui):
    page, _, flags = ui
    flags['history_error'] = True
    page.locator('#refresh-history').click()
    expect(page.locator('#history-feedback')).to_contain_text('保留上次读取结果')
    flags['history_error'] = False
    page.locator('#retry-history').click()
    expect(page.locator('#history-feedback')).to_be_empty()
    search = page.locator('#filter-search')
    search.dispatch_event('compositionstart')
    search.fill('正在拼音')
    page.wait_for_timeout(350)
    assert not any(q.get('search') == ['正在拼音'] for q in flags['queries'])
    search.dispatch_event('compositionend')
    expect(page.locator('#history-counts')).to_contain_text('共 0 条')
    flags['hold_search'] = 'old-query'
    search.fill('old-query')
    page.wait_for_timeout(450)
    assert flags['held']
    search.fill('comment-11')
    expect(page.locator('#history-counts')).to_contain_text('共 1 条')
    flags['held'][0].fulfill(json=dict(items=[], total_count=0, total_pages=1, page=1))
    expect(page.locator('#record-detail')).to_contain_text('中文回复11')


@pytest.mark.parametrize('theme',['dark','light','contrast'])
def test_mobile_keyboard_long_text_and_evidence(ui,theme):
    page, _, _ = ui
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
    evidence = Path(__file__).resolve().parents[2]/'output/test-evidence/secondary-reply-settings'
    evidence.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(evidence/f'{theme}-desktop.png'),full_page=True)
    page.set_viewport_size(dict(width=390,height=844))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(page.locator('#filter-time-window')).to_be_visible()
    expect(page.locator('#filter-provider')).to_be_visible()
    page.screenshot(path=str(evidence/f'{theme}-mobile-list.png'),full_page=True)
    page.locator('.sr-record').first.click()
    expect(page.locator('#back-to-list')).to_be_visible()
    expect(page.locator('#record-detail')).to_contain_text('完整长评论内容' * 30)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(evidence/f'{theme}-mobile-detail.png'),full_page=True)
    page.locator('#back-to-list').click()
    expect(page.locator('.sr-record').first).to_be_focused()
    page.locator('#tab-ledger').focus(); page.keyboard.press('ArrowRight')
    expect(page.locator('#tab-policy')).to_be_focused()
    expect(page.locator('#view-policy')).to_be_visible()
    page.evaluate("document.documentElement.dataset.textSize='xlarge'")
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_approved_reference_composition_and_full_record(ui):
    """以选中 demo 的主要区域位置约束视觉回归，避免仅因存在分栏就通过。"""
    page, _, _ = ui
    page.set_viewport_size(dict(width=1487,height=1058))
    panel = page.locator('#reading-workspace').bounding_box()
    left = page.locator('.sr-list-pane').bounding_box()
    right = page.locator('#record-detail').bounding_box()
    assert 345 <= panel['y'] <= 360
    assert abs(left['x'] - 270) <= 2
    assert abs(left['width'] - 486) <= 3
    assert abs(right['x'] - 772) <= 3
    assert page.locator('.sr-timeline li').count() == 4
    assert page.locator('.sr-record').first.bounding_box()['height'] <= 108
    assert page.locator('.console-subnav:visible').count() == 1
    page.locator('#expand-record').click()
    expect(page.locator('#record-evidence')).to_have_attribute('open','')
    expect(page.locator('#record-generation')).to_have_attribute('open','')
    expect(page.locator('#record-evidence')).to_contain_text('审批通过时间')
    expect(page.locator('#record-evidence')).to_contain_text('原评发布时间')
    page.locator('#expand-record').click()
    page.set_viewport_size(dict(width=390,height=844))
    page.locator('#tab-ledger').scroll_into_view_if_needed()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    header = page.locator('.page-header').bounding_box()
    refresh = page.locator('#refresh-history').bounding_box()
    assert refresh['y'] < header['y'] + 10

    page.evaluate('window.scrollTo(0,0)')
    assert page.locator('.sr-record').first.bounding_box()['y'] <= 450
    assert page.locator('#filter-size').bounding_box()['height'] >= 44
    menu = page.locator('.console-menu')
    menu.click()
    expect(menu).to_have_attribute('aria-expanded','true')
    page.keyboard.press('Escape')
    expect(menu).to_be_focused()

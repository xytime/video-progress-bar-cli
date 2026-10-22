"""真实浏览器验证来源新鲜度，不连接生产或外网。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Codex | 六档边界、旧日期、动态刷新、所有列表及分集、主题与手机截图 |
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.browser_fixtures import chromium, dashboard, _video, _payload
from tests.browser.test_topic_candidates_browser import ui as topic_ui
from tests.browser.test_video_prefilter_browser import ui as prefilter_ui
from tests.topic_candidate_fixtures import tracker, topic, run, video
from tests.unit.test_topic_candidates_api import topic_client


def screenshot(page, name):
    folder = Path(__file__).resolve().parents[2] / 'output/test-evidence/source-publication'
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / (name + '.png')), full_page=True)


def test_boundaries_bad_dates_and_live_refresh(dashboard):
    page, state = dashboard
    page.clock.install(time=datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
    page.reload()
    expect(page.locator('#row-first .source-age')).to_be_visible()
    results = page.evaluate('''() => {
      const now = Date.now(), day = 86400000, describe = SourcePublication.describe;
      return {tiers: [0, .999, 1, 1.999, 2, 2.999, 3, 6.999, 7, 9.999, 10, 100].map(
        age => describe(new Date(now-age*day).toISOString(), null, now).tier),
        missing: describe(null, null, now), invalid: describe('2026-02-30T12:00:00Z', null, now),
        future: describe('2026-10-23T12:00:00Z', null, now),
        legacy: describe(null, '20261020', now),
        nozone: describe('2026-10-22T01:00:00', null, now)};
    }''')
    assert results['tiers'] == ['fresh', 'fresh', 'green', 'green', 'yellow', 'yellow',
                                'orange', 'orange', 'rust', 'rust', 'old', 'old']
    assert results['missing']['age'] == '时间未知'
    assert results['legacy']['age'] == '约 2 天前'
    for key in ('invalid', 'future', 'nozone'):
        assert results[key]['tier'] == 'unknown' and results[key]['age'] == '时间异常'
    page.evaluate('''() => { document.body.append(SourcePublication.create(
      new Date(Date.now()-86400000+30000).toISOString(), null, '刷新验证')); }''')
    badge = page.locator('.source-age').filter(has_text='刷新验证')
    expect(badge).to_have_attribute('data-freshness', 'fresh')
    page.clock.fast_forward(61000)
    expect(badge).to_have_attribute('data-freshness', 'green')
    assert not state['writes']


@pytest.mark.parametrize('width,theme', [(1440, 'dark'), (1280, 'light'), (390, 'dark'),
                                        (390, 'light'), (390, 'contrast')])
def test_all_lists_slices_and_readable_mobile(dashboard, width, theme):
    page, state = dashboard
    page.set_viewport_size(dict(width=width, height=900))
    page.clock.install(time=datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
    rows = []
    for index, days in enumerate((.5, 1.5, 2.5, 5, 8, 12)):
        item = _video('age-' + str(index))
        item['title'] = item['display_title'] = '原视频发布时间与素材新鲜度验收 ' + str(index + 1)
        item['source_published_at'] = datetime.fromtimestamp(
            datetime(2026, 10, 22, 12, tzinfo=timezone.utc).timestamp() - days * 86400,
            tz=timezone.utc).isoformat()
        item['slices_count'] = 1 if index == 0 else 0
        rows.append(item)
    state['payload'] = _payload(rows, total=6)
    page.route('**/api/videos/age-0/slices', lambda route: route.fulfill(json={
        'slices': [dict(_video('age-0'), slice_index=1, trim_start='00:00', trim_end='00:30')]}))
    for tab in ('waitlist', 'queue', 'ready', 'active', 'wechat_deferred', 'review',
                'completed', 'error', 'high_likes'):
        page.goto('http://dashboard-test.invalid/?tab=' + tab + '&created_window=all')
        page.evaluate('''theme => {clearTimeout(refreshTimeoutId); scheduleNextRefresh=()=>{};
          document.documentElement.dataset.theme=theme;}''', theme)
        expect(page.locator('#row-age-0 .source-age')).to_have_text('原始发布 12 小时前')
        assert page.locator('.source-age').count() == 6
    # 实际展开分集；来源继承父视频，不取分集更新时间。
    page.locator('#btn-toggle-age-0').click()
    expect(page.locator('#row-age-0_s1 .source-age')).to_have_text('原视频发布 12 小时前')
    expect(page.locator('#row-age-0_s1 .source-age')).to_have_attribute('data-freshness', 'fresh')
    measurements = page.locator('.source-age').evaluate_all('''els => els.map(el => {
      const s=getComputedStyle(el), box=el.getBoundingClientRect();
      const rgb=value=>value.match(/[\\d.]+/g).slice(0,3).map(Number);
      const lum=value=>rgb(value).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4})
        .reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
      const a=lum(s.color), b=lum(s.backgroundColor);
      return {contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),
        left:box.left,right:box.right,border:parseFloat(s.borderLeftWidth)};
    })''')
    assert all(item['contrast'] >= 4.5 for item in measurements), measurements
    assert all(item['border'] >= 1 for item in measurements)
    if width == 390:
        assert all(item['left'] >= 0 and item['right'] <= 390 for item in measurements)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    screenshot(page, f'lists-slices-{width}-{theme}')
    assert not state['writes']


def test_topic_pool_uses_shared_field(topic_ui):
    page, tracker, flags = topic_ui
    rule = topic(tracker)
    run(tracker, rule)
    page.reload()
    expect(page.locator('.candidate-card .source-age').first).to_be_visible()
    page.set_viewport_size(dict(width=390, height=844))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    screenshot(page, 'topic-mobile')


def test_prefilter_results_and_history_use_shared_field(prefilter_ui):
    page, tracker, flags = prefilter_ui
    page.locator('#prefilter-name').fill('新鲜度验收')
    page.locator('#prefilter-save').click()
    expect(page.locator('#prefilter-search')).to_be_enabled()
    page.locator('#prefilter-search').click()
    expect(page.locator('#prefilter-results .source-age').first).to_be_visible()
    page.set_viewport_size(dict(width=390, height=844))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    screenshot(page, 'prefilter-mobile')

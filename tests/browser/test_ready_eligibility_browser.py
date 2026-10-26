"""隔离真实页面验证资格阻塞、50分文案、筛选、手机与只读失败恢复。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| backlog-v1 | 2026-10-26 | Codex | 浏览器+FastAPI+真实临时账本，禁止业务写入和平台访问。 |
"""
import re

from playwright.sync_api import expect
from tests.browser_fixtures import chromium  # noqa: F401

from tests.browser.test_dashboard_workspace import workspace, evidence  # noqa: F401
from video_processing.scoring import TED_AUTO_PUBLISH_CHANNEL_IDS


def test_ready_qualification_real_api_and_mobile(workspace):
    page,client,state,db = workspace
    for key,score,likes in [('older-ted',49,6),('rate-only',50,6)]:
        db.add_video(key,'验收老视频 '+key,TED_AUTO_PUBLISH_CHANNEL_IDS[0],score=score,view_count=1000,like_count=likes)
        db.mark_video_ready_for_publication(key)
    db.defer_ready_publication('older-ted','加工完成 · 等待账号冷却，可在控制台确认跳过一次')
    page.goto('http://127.0.0.1:9100/?tab=ready&created_window=all')
    expect(page.locator('#ready-admission-summary')).to_contain_text('资格阻塞 2')
    row=page.locator('#activity-body tr').filter(has_text='older-ted')
    expect(row).to_contain_text('资格阻塞')
    expect(row).to_contain_text('50分')
    expect(row.locator('.publication-wait-detail')).to_be_visible()
    expect(row).to_contain_text('严格大于0.6%')
    expect(row).not_to_contain_text('跳过一次')
    expect(row.locator('.plat-wechat')).to_contain_text('资格阻塞')
    expect(row.locator('.plat-wechat')).not_to_have_attribute('title',re.compile('跳过一次'))
    expect(row.locator('.plat-wechat')).to_have_attribute('title',re.compile('严格大于0.6%'))
    expect(page.locator('#ready-admission-summary a')).to_have_attribute('href','/?view=publications&tab=review')
    assert client.get('/api/videos?tab=ready').json()['publish_policy']['ted_min_score'] == 50
    page.locator('#video-filter-search').fill('zz-no-match')
    page.locator('#video-filter-search').press('Enter')
    expect(page.locator('#activity-body tr[id^="row-"]')).to_have_count(0)
    page.get_by_role('button',name='清除筛选',exact=True).click()
    expect(page.locator('#activity-body tr[id^="row-"]')).to_have_count(2)
    page.set_viewport_size(dict(width=390,height=844))
    expect(page.locator('#ready-admission-summary')).to_be_visible()
    expect(row).to_contain_text('低于50分准入线')
    expect(row.locator('.publication-wait-detail')).to_be_visible()
    expect(page.locator('#row-rate-only .mcm-tag-pass')).to_have_text('分数过线')
    expect(page.locator('#row-rate-only')).to_contain_text('资格阻塞')
    page.locator('#video-filter-sort').focus()
    page.keyboard.press('ArrowDown');page.keyboard.press('Enter')
    expect(page.locator('#ready-admission-summary')).to_contain_text('资格阻塞 2')
    evidence(page,'ready-eligibility-mobile')
    state['offline']=True
    page.reload()
    expect(page.locator('#activity-body')).to_contain_text('失败')
    state['offline']=False
    page.reload()
    expect(page.locator('#ready-admission-summary')).to_contain_text('资格阻塞 2')
    assert not state['writes']

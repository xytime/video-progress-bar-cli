"""v0.3：真实 Chromium、FastAPI 与临时 SQLite 验证总览和导航，不连接生产。

# Modification History
| filtered-counts-v1 | 2026-10-25 | Codex | 标签计数与列表筛选一致，验证频道、时间和清除筛选。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | H01–H14 首页口径、只读、恢复、失败、移动端证据 |
"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from video_processing.db.database import PipelineDB
from web import app as web_app


@pytest.fixture
def workspace(chromium, tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / 'workspace.db'))
    for yid, score, status in [('unscored',0,'PENDING'),('eligible',90,'PENDING'),
                              ('making',85,'PROCESSING'),('failed',20,'FAILED')]:
        db.add_video(yid, '运营验收 '+yid, 'UC-fixture', score=score, source='MONITOR')
        db.update_video_status(yid,status)
    monkeypatch.setattr(web_app,'db',db)
    monkeypatch.setattr(web_app.settings,'topic_search_enabled',False)
    client=TestClient(web_app.app,base_url='http://127.0.0.1:9100',client=('127.0.0.1',50000))
    page=chromium.new_page(viewport=dict(width=1366,height=768))
    state=dict(writes=[],errors=[],offline=False,capability_status=200,requests=[])
    page.on('pageerror',lambda error:state['errors'].append(str(error)))
    def route_handler(route):
        req=route.request;url=urlsplit(req.url);state['requests'].append(url.path)
        if req.method!='GET':
            state['writes'].append(req.url);route.fulfill(status=500,json={'detail':'禁止写入'});return
        if state['offline'] and url.path=='/api/videos':
            route.fulfill(status=503,json={'detail':'隔离故障'});return
        if url.path=='/api/console/capabilities' and state['capability_status']!=200:
            route.fulfill(status=state['capability_status'],json={'detail':'未采用或故障'});return
        if url.hostname not in ('127.0.0.1',):
            route.fulfill(status=404,body='离线验收');return
        response=client.get(url.path+('?' + url.query if url.query else ''))
        route.fulfill(status=response.status_code,body=response.content,headers=dict(response.headers))
    page.route('**/*',route_handler)
    page.goto('http://127.0.0.1:9100/')
    expect(page.locator('#overview-feedback')).to_contain_text('最后成功')
    page.evaluate('clearTimeout(refreshTimeoutId); scheduleNextRefresh=()=>{}')
    yield page,client,state,db
    page.close();client.close()
    assert not state['errors']
    assert not state['writes']


def evidence(page,name):
    folder=Path(__file__).resolve().parents[2]/'output/test-evidence/dashboard-workspace'
    folder.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(folder/(name+'.png')),full_page=True)


def test_home_entry_counts_readonly_and_first_screen(workspace):
    page,client,state,db=workspace
    expect(page.locator('.console-primary')).to_have_count(6)
    expect(page.locator('#console-search-state')).to_contain_text('生产搜索关闭')
    for tab in ('waitlist','active','ready','error'):
        total=client.get('/api/videos',params={'tab':tab,'created_window':'all'}).json()['total_count']
        expect(page.locator('#overview-'+tab)).to_have_text(str(total))
    assert client.get('/api/stats').json()['pending']!=client.get('/api/videos?tab=queue').json()['total_count']
    for selector in ('#btn-run-pipeline','#channel-list','#video-url-input','#workspace-list'):
        expect(page.locator(selector)).not_to_be_visible()
    for selector in ('.console-shortcuts [data-topic-entry]','.console-attention a:first-child','.console-tasks h2'):
        box=page.locator(selector).bounding_box();assert box and box['y']+box['height']<=768
    assert '/api/channels' not in state['requests']
    assert '/api/ai-audit/summary' not in state['requests']
    evidence(page,'overview-desktop')
    page.locator('#overview-error').click()
    expect(page.locator('#activity-count')).to_have_text('1')
    assert 'created_window=all' in page.url
    expect(page.locator('#video-filter-created-window')).to_have_value('all')


def test_url_restore_back_and_existing_deep_link(workspace):
    page,client,state,db=workspace
    page.goto('http://127.0.0.1:9100/?tab=waitlist&search=unscored&created_window=all&size=50')
    expect(page.locator('#workspace-title')).to_have_text('选题中心')
    expect(page.locator('#video-filter-search')).to_have_value('unscored')
    expect(page.locator('#activity-count')).to_have_text('1')
    page.locator('.console-primary[data-section=production]').click()
    expect(page.locator('#workspace-title')).to_have_text('生产队列')
    page.go_back()
    expect(page.locator('#video-filter-search')).to_have_value('unscored')
    expect(page.locator('#video-filter-size')).to_have_value('50')
    page.reload();expect(page.locator('#activity-count')).to_have_text('1')
    page.go_forward();expect(page.locator('#workspace-title')).to_have_text('生产队列')


def test_failed_read_stale_recovery_and_missing_adoption(workspace):
    page,client,state,db=workspace
    old=page.locator('#overview-active').inner_text();state['offline']=True
    page.locator('#overview-retry').click();expect(page.locator('#overview-feedback')).to_contain_text('旧数据')
    expect(page.locator('#overview-active')).to_have_text(old)
    state['capability_status']=404;page.locator('#overview-retry').click()
    expect(page.locator('#console-search-state')).to_contain_text('尚未采用')
    entry=page.locator('.console-shortcuts [data-topic-entry]')
    expect(entry).to_be_disabled()
    entry.focus();page.keyboard.press('Enter')
    assert urlsplit(page.url).path=='/'
    page.reload();expect(page.locator('#overview-feedback')).to_contain_text('暂无可信数据')
    expect(page.locator('#overview-active')).to_have_text('—')
    state['offline']=False;state['capability_status']=200
    page.locator('#overview-retry').click();expect(page.locator('#overview-feedback')).to_contain_text('最后成功')
    evidence(page,'recovered-read')


@pytest.mark.parametrize('width,theme,size',[(390,'dark','standard'),(1024,'light','large'),(1366,'contrast','xlarge'),(1920,'dark','large')])
def test_responsive_themes_and_keyboard(workspace,width,theme,size):
    page,client,state,db=workspace
    page.evaluate('(p)=>localStorage.setItem("vp-display-preferences",JSON.stringify(p))',dict(theme=theme,size=size))
    page.set_viewport_size(dict(width=width,height=844));page.reload()
    expect(page.locator('#overview-feedback')).to_contain_text('最后成功')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    if width<=1024:
        page.locator('.console-menu').focus();page.keyboard.press('Enter')
        expect(page.locator('.console-drawer')).to_be_visible()
        expect(page.locator('.console-drawer a[href="/topic-candidates"]')).to_be_visible()
        page.keyboard.press('Escape');expect(page.locator('.console-menu')).to_be_focused()
    evidence(page,f'overview-{width}-{theme}-{size}')
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.console-metric').first.evaluate('el=>getComputedStyle(el).animationName')=='none'


def test_configuration_and_manual_form_do_not_share_home(workspace):
    page,client,state,db=workspace
    page.locator('.console-primary[data-section=operations]').click()
    expect(page.locator('#channel-list')).to_be_visible()
    page.locator('#header-more-menu summary').click()
    expect(page.locator('#btn-run-pipeline')).to_be_visible()
    page.locator('.console-subnav a[href*="tab=manual"]').click()
    expect(page.locator('#video-url-input')).to_be_visible()
    page.locator('#video-url-input').fill('https://youtu.be/draft-only')
    page.locator('.console-primary[data-section=overview]').click()
    expect(page.locator('#video-url-input')).not_to_be_visible()
    page.locator('.console-subnav a[href*="tab=manual"]').click()
    expect(page.locator('#video-url-input')).to_have_value('https://youtu.be/draft-only')
    page.locator('.console-subnav a[href*="tab=waitlist"]').click()
    expect(page.locator('#workspace-list')).to_be_visible()


@pytest.mark.parametrize('theme',['dark','light','contrast'])
def test_contrast_large_first_screen_and_zoom(workspace,theme):
    page,client,state,db=workspace
    page.evaluate('(theme)=>localStorage.setItem("vp-display-preferences",JSON.stringify({theme,size:"large"}))',theme)
    page.reload();expect(page.locator('#overview-feedback')).to_contain_text('最后成功')
    for selector in ('.console-shortcuts [data-topic-entry]','.console-attention a:first-child','.console-tasks h2'):
        box=page.locator(selector).bounding_box();assert box and box['y']+box['height']<=768
    ratios=page.evaluate('''() => {
      const rgb=c=>(c.match(/[\\d.]+/g)||[]).map(Number);
      const blend=(a,b)=>a.slice(0,3).map((v,i)=>v*(a[3]??1)+b[i]*(1-(a[3]??1)));
      function bg(el){if(!el)return [255,255,255];return blend(rgb(getComputedStyle(el).backgroundColor),bg(el.parentElement));}
      const l=c=>c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
      return [...document.querySelectorAll('.console-rail a,.console-metric span,.console-attention a span,.console-shortcuts p,.console-task small')].map(el=>{
        const a=l(rgb(getComputedStyle(el).color)),b=l(bg(el));return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
      });
    }''')
    assert ratios and min(ratios)>=4.5
    # 桌面 200% 缩放等效 CSS viewport：1366 / 2，浏览器自动重排保持导航可达。
    page.set_viewport_size(dict(width=683,height=384))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('.console-menu').click()
    expect(page.locator('.console-drawer a[href="/topic-candidates"]')).to_be_visible()
    for selector in ('.console-drawer button','.console-drawer a'):
        assert all(row['height']>=44 for row in page.locator(selector).evaluate_all('els=>els.map(el=>({height:el.getBoundingClientRect().height}))'))
    page.keyboard.press('Escape');evidence(page,'zoom200-'+theme)


def test_local_capability_and_remote_boundary(workspace):
    page,client,state,db=workspace
    data=client.get('/api/console/capabilities').json()
    assert data==dict(topic_available=True,search_enabled=False)
    assert client.get('/topic-candidates').status_code==200
    remote=TestClient(web_app.app,client=('192.0.2.1',50000))
    try:
        assert remote.get('/api/console/capabilities').json()['topic_available'] is False
        assert remote.get('/topic-candidates').status_code==403
    finally:
        remote.close()


def test_v031_attention_link_restore_and_empty(workspace):
    page,client,state,db=workspace
    page.locator('#attention-main a').click()
    expect(page.locator('#attention-filter-banner')).to_be_visible()
    expect(page.locator('#attention-filter-label')).to_have_text('执行异常待排查')
    expect(page.locator('#activity-count')).to_have_text('1')
    assert 'attention_kind=execution' in page.url and 'sort=updated_at_desc' in page.url
    page.reload();expect(page.locator('#attention-filter-label')).to_have_text('执行异常待排查')
    expect(page.locator('#activity-count')).to_have_text('1')
    page.locator('#attention-filter-banner button').click()
    expect(page.locator('#attention-filter-banner')).not_to_be_visible()
    page.go_back();expect(page.locator('#attention-filter-banner')).to_be_visible()
    page.locator('.console-primary[data-section=overview]').click()
    page.go_back();expect(page.locator('#attention-filter-banner')).to_be_visible()
    page.go_forward();expect(page.locator('#workspace-overview')).to_be_visible()
    db.update_video_status('failed','PUBLISHED')
    page.locator('#overview-retry').click()
    expect(page.locator('#attention-main')).to_contain_text('当前没有这些待核实或受阻事项')
    evidence(page,'v031-empty-attention')


def test_v031_cohort_zero_and_low_score_completion(workspace):
    page,client,state,db=workspace
    with db.get_connection() as conn:
        conn.execute('UPDATE processed_videos SET score=20')
    db.update_video_status('failed','SUBMITTED_BOUND')
    page.locator('#overview-retry').click()
    expect(page.locator('#global-funnel-panel')).to_contain_text('无符合口径记录')
    expect(page.locator('#gf-qualified')).to_have_text('0')
    expect(page.locator('#global-funnel-panel')).not_to_contain_text('发布率')
    page.locator('.gf-stage-card').nth(3).click()
    expect(page.locator('#activity-count')).to_have_text('1')
    assert 'funnel_stage=published' in page.url
    evidence(page,'v031-local-records-drilldown')


def test_like_rate_presets_slider_url_reset_and_mobile(workspace):
    page, client, state, db = workspace
    for yid, likes in [('low-rate', 20), ('mid-rate', 40), ('high-rate', 80)]:
        db.add_video(yid, yid, 'rates', score=20, view_count=1000, like_count=likes)
    page.goto('http://127.0.0.1:9100/?view=topics&tab=waitlist&created_window=all&page=2')
    page.locator('#video-filter-like-rate').select_option('3,5')
    expect(page.locator('#activity-count')).to_have_text('1')
    expect(page.locator('#activity-body')).to_contain_text('mid-rate')
    assert 'like_rate_min=3' in page.url and 'page=1' in page.url
    page.reload()
    expect(page.locator('#like-rate-min')).to_have_value('3')
    expect(page.locator('#video-filter-like-rate')).to_have_value('3,5')
    # 键盘改变滑块，提交后的 URL 和数字输入一致。
    slider = page.locator('#like-rate-min-slider')
    slider.focus(); slider.press('ArrowRight')
    expect(page.locator('#like-rate-min')).to_have_value('3.1')
    assert 'like_rate_min=3.1' in page.url
    page.locator('#like-rate-min').fill('99')
    page.locator('#like-rate-min').press('Tab')
    expect(page.locator('#like-rate-min')).to_have_value('5')
    expect(page.locator('#activity-body')).to_contain_text('当前筛选下无匹配记录')
    page.locator('#tab-high_likes').click()
    expect(page.locator('#like-rate-min')).to_have_value('5')
    for theme in ('light', 'dark', 'high-contrast'):
        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#like-rate-filter').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
        assert page.locator('#activity-body .empty-state').bounding_box()['width'] > 250
    evidence(page, 'like-rate-mobile')
    state['offline'] = True
    page.locator('#video-filter-like-rate').select_option('1,3')
    expect(page.locator('#activity-body')).to_contain_text('列表加载失败')
    state['offline'] = False
    page.locator('.btn-filter-clear').click()
    expect(page.locator('#video-filter-like-rate')).to_have_value('all')
    expect(page.locator('#like-rate-bounds')).to_be_hidden()
    assert 'like_rate_min' not in page.url and 'like_rate_max' not in page.url


def test_filter_preferences_reopen_url_precedence_clear_and_rate_label(workspace):
    page,client,state,db=workspace
    entry='http://127.0.0.1:9100/?view=topics&tab=waitlist'
    page.goto(entry)
    search=page.locator('#video-filter-search')
    assert search.bounding_box()['width'] <= 210
    search.fill('运营');search.press('Enter')
    page.locator('#video-filter-size').select_option('50')
    page.locator('#video-filter-sort').select_option('views_desc')
    page.locator('#video-filter-like-rate').select_option('10,100')
    page.locator('#like-rate-min').fill('0.9');page.locator('#like-rate-min').press('Tab')
    expect(page.locator('#video-filter-like-rate option:checked')).to_have_text('0.9%+')
    page.goto(entry)
    expect(page.locator('#video-filter-search')).to_have_value('运营')
    expect(page.locator('#video-filter-size')).to_have_value('50')
    expect(page.locator('#video-filter-sort')).to_have_value('views_desc')
    expect(page.locator('#like-rate-min')).to_have_value('0.9')
    expect(page.locator('#like-rate-max')).to_have_value('100')
    expect(page.locator('#video-filter-like-rate option:checked')).to_have_text('0.9%+')
    page.reload()
    expect(page.locator('#like-rate-min')).to_have_value('0.9')
    page.goto(entry+'&search=eligible&like_rate_min=0&like_rate_max=5')
    expect(page.locator('#video-filter-search')).to_have_value('eligible')
    expect(page.locator('#like-rate-min')).to_have_value('0')
    expect(page.locator('#video-filter-like-rate option:checked')).to_have_text('0%–5%')
    page.locator('.btn-filter-clear').click()
    page.goto(entry)
    expect(page.locator('#video-filter-search')).to_have_value('')
    expect(page.locator('#video-filter-like-rate')).to_have_value('all')
    page.evaluate("localStorage.setItem('video_pipeline_filters_v1','broken')")
    page.goto(entry)
    expect(page.locator('#video-filter-like-rate')).to_have_value('all')
    page.locator('#video-filter-like-rate').select_option('10,100')
    expect(page.locator('#video-filter-like-rate option:checked')).to_have_text('10%+')
    page.goto(entry)
    expect(page.locator('#video-filter-like-rate')).to_have_value('10,100')
    evidence(page,'remembered-like-rate-desktop')


@pytest.mark.parametrize('width', [1366, 390])
def test_filtered_tab_counts_clear_channel_and_all_time(workspace, width):
    page, client, state, db = workspace
    db.add_channel('UC-fixture', '验收频道')
    db.add_channel('UC-other', '另一个频道')
    db.add_video('ready-other', '另一个频道的待发布成片', 'UC-other', score=90)
    db.set_video_preparation_ready('ready-other', True)
    page.set_viewport_size(dict(width=width, height=844))
    page.goto('http://127.0.0.1:9100/?view=production&tab=ready&channel=不存在&created_window=7d')
    expect(page.locator('#tab-ready')).to_have_text('成片待投(0)')
    expect(page.locator('#tab-queue')).to_have_text('待处理(0)')
    expect(page.locator('#tab-error')).to_have_text('出错异常(0)')
    expect(page.locator('#activity-body')).to_contain_text('当前筛选下无匹配记录')
    # 当前场景无成片的频道仍应通过原深链接保留，不能偷偷改为全部频道。
    page.goto('http://127.0.0.1:9100/?view=production&tab=ready&channel=验收频道&created_window=7d')
    expect(page.locator('#tab-queue')).to_have_text('待处理(1)')
    expect(page.locator('#tab-ready')).to_have_text('成片待投(0)')
    expect(page.locator('#tab-error')).to_have_text('出错异常(1)')
    evidence(page, f'filtered-empty-{width}')
    page.locator('.btn-filter-clear').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#video-filter-channel')).to_have_value('')
    expect(page.locator('#video-filter-created-window')).to_have_value('all')
    expect(page.locator('#tab-ready')).to_have_text('成片待投(1)')
    expect(page.locator('#activity-count')).to_have_text('1')
    expect(page.locator('#activity-body')).to_contain_text('另一个频道的待发布成片')
    assert 'created_window=all' in page.url
    page.reload()
    expect(page.locator('#video-filter-channel')).to_have_value('')
    expect(page.locator('#video-filter-created-window')).to_have_value('all')
    expect(page.locator('#tab-ready')).to_have_text('成片待投(1)')
    evidence(page, f'filtered-cleared-{width}')

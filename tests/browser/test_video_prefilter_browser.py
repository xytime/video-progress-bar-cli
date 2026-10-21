"""真实浏览器经隔离 TestClient 完成预筛选；禁止连接外部网络。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-21 | Codex | 修订稿折叠编辑、首屏结果、三主题和 200% 重排 |
| 1.0.0 | 2026-10-21 | Codex | 保存、手动搜索、整理、失败、键盘与窄屏 |
"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from tests.topic_candidate_fixtures import tracker
from tests.unit.test_topic_candidates_api import topic_client, ORIGIN
from tests.unit.test_video_prefilter import prepare


@pytest.fixture
def ui(chromium,topic_client,request):
    client,tracker=topic_client
    if getattr(request,'param',True):prepare(tracker)
    page=chromium.new_page(viewport=dict(width=1440,height=1000))
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    flags=dict(offline=False,conflict=False)
    def handler(route):
        req=route.request;url=urlsplit(req.url)
        if flags['offline'] and url.path.startswith('/api/'):
            route.fulfill(status=503,json=dict(detail='服务暂不可用'));return
        if flags['conflict'] and req.method=='PUT':
            route.fulfill(status=409,json=dict(detail=dict(code='STALE',message='规则已更新，当前草稿已保留')));return
        headers={k:v for k,v in req.all_headers().items() if k in ('origin','x-topic-csrf','host','sec-fetch-site','cookie','content-type')}
        client.headers.pop('origin',None);client.headers.pop('x-topic-csrf',None);client.cookies.clear()
        response=client.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data,headers=headers)
        route.fulfill(status=response.status_code,body=response.content,headers=dict(response.headers))
    page.route('**/*',handler);page.goto(ORIGIN+'/video-prefilter')
    expect(page.locator('#prefilter-name')).to_be_enabled()
    page.locator('#prefilter-editor').evaluate('el=>el.open=true')
    yield page,tracker,flags
    page.close();assert not errors


def evidence(page,name):
    path=Path(__file__).resolve().parents[2]/'output/test-evidence/video-prefilter';path.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(path/(name+'.png')),full_page=True)


def test_manual_only_complete_flow_and_refresh(ui):
    page,tracker,flags=ui
    assert not tracker.adapter.calls
    page.locator('#prefilter-name').fill('科技短片')
    expect(page.locator('#prefilter-search')).to_be_disabled()
    page.locator('#prefilter-save').click()
    expect(page.locator('#prefilter-form-feedback')).to_contain_text('配置已保存')
    assert not tracker.adapter.calls
    page.locator('#prefilter-search').click()
    expect(page.locator('#prefilter-job-status')).to_contain_text('完成')
    expect(page.locator('#prefilter-results')).to_contain_text('指标合格')
    page.locator('#prefilter-results').get_by_role('button',name='收藏',exact=True).click()
    expect(page.locator('#prefilter-results')).to_contain_text('已收藏')
    page.locator('#prefilter-reload').focus();page.evaluate('scrollTo(0,0)')
    evidence(page,'desktop')
    count=len(tracker.adapter.calls);page.reload()
    expect(page.locator('#prefilter-results')).to_contain_text('已收藏')
    assert len(tracker.adapter.calls)==count==2
    page.locator('#prefilter-results').get_by_role('button',name='排除',exact=True).click()
    expect(page.locator('#prefilter-results')).to_contain_text('已排除')
    page.locator('#prefilter-results').get_by_role('button',name='撤销整理',exact=True).click()
    expect(page.locator('#prefilter-results')).to_contain_text('未整理')


@pytest.mark.parametrize('theme',['dark','light','contrast'])
def test_draft_conflict_keyboard_narrow_and_failure(ui,theme):
    page,tracker,flags=ui;page.set_viewport_size(dict(width=390,height=844))
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
    page.locator('#prefilter-name').fill('保留草稿')
    flags['conflict']=True;page.locator('#prefilter-save').click()
    expect(page.locator('#prefilter-form-feedback')).to_contain_text('草稿已保留')
    expect(page.locator('#prefilter-name')).to_have_value('保留草稿')
    page.locator('#prefilter-reload').click()
    expect(page.locator('#prefilter-keep')).to_be_focused();page.keyboard.press('Escape')
    expect(page.locator('#prefilter-discard')).not_to_be_visible()
    expect(page.locator('#prefilter-name')).to_have_value('保留草稿')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    flags['conflict']=False;page.locator('#prefilter-save').click()
    expect(page.locator('#prefilter-form-feedback')).to_contain_text('配置已保存')
    page.locator('#prefilter-search').click()
    expect(page.locator('#prefilter-job-status')).to_contain_text('完成')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#prefilter-reload').focus()
    evidence(page,'mobile-'+theme)
    flags['offline']=True;page.locator('#prefilter-result-retry').click()
    expect(page.locator('#prefilter-result-feedback')).to_contain_text('读取失败')
    flags['offline']=False;page.locator('#prefilter-result-retry').click()
    expect(page.locator('#prefilter-results')).to_contain_text('指标合格')


def test_closed_search_configuration_still_available(ui):
    page,tracker,flags=ui;tracker.config.topic_search_enabled=False
    page.reload();expect(page.locator('#prefilter-search')).to_be_disabled()
    expect(page.locator('#prefilter-gate')).to_contain_text('搜索')
    page.locator('#prefilter-editor > summary').click()
    page.locator('#prefilter-name').fill('离线规则')
    page.locator('#prefilter-save').click()
    expect(page.locator('#prefilter-form-feedback')).to_contain_text('配置已保存')
    assert not tracker.adapter.calls


def test_empty_partial_and_official_request_failure_are_distinct(ui):
    from video_processing.utils.topic_search import SearchFailure
    page,tracker,flags=ui
    tracker.adapter.items=[]
    page.locator('#prefilter-search').click()
    expect(page.locator('#prefilter-job-status')).to_contain_text('完成')
    expect(page.locator('#prefilter-results')).to_contain_text('暂无可用记录')
    assert len(tracker.adapter.calls)==1
    from tests.topic_candidate_fixtures import video
    tracker.adapter.items=[video(duration='PT1M')];tracker.adapter.prefilter_details=lambda ids,timeout:[]
    tracker.clock.advance(minutes=16)
    page.locator('#prefilter-search').click()
    expect(page.locator('#prefilter-job-status')).to_contain_text('部分完成')
    page.locator('#prefilter-categories').get_by_role('button',name='资料不足 1',exact=True).click()
    expect(page.locator('#prefilter-results')).to_contain_text('资料不足')
    tracker.clock.advance(minutes=16);tracker.adapter.prefilter_details=tracker.adapter.details
    tracker.adapter.detail_error=SearchFailure('NETWORK','官方请求失败')
    page.locator('#prefilter-search').click()
    expect(page.locator('#prefilter-job-status')).to_contain_text('请求失败')
    page.locator('#prefilter-categories').get_by_role('button',name='请求失败 1',exact=True).click()
    expect(page.locator('#prefilter-results')).to_contain_text('官方请求失败')
    expect(page.locator('#prefilter-results').get_by_role('button',name='收藏',exact=True)).to_be_disabled()


@pytest.mark.parametrize('theme', ['dark', 'light', 'contrast'])
def test_primary_action_hover_contrast(ui, theme):
    page, tracker, flags = ui
    page.evaluate('(theme)=>localStorage.setItem("vp-display-preferences",JSON.stringify({theme,size:"standard"}))', theme)
    page.reload()
    expect(page.locator('#prefilter-search')).to_be_enabled()
    for selector in ('#prefilter-search',):
        page.locator(selector).hover()
        ratio = page.locator(selector).evaluate('''el => {
          const rgb = c => (c.match(/[\\d.]+/g) || []).map(Number);
          function bg(e) {
            if (!e) return [255,255,255];
            const c = rgb(getComputedStyle(e).backgroundColor), p = bg(e.parentElement), a = c[3] ?? 1;
            return c.slice(0,3).map((v,i) => v*a+p[i]*(1-a));
          }
          const l = c => c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
            .reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
          const a = l(rgb(getComputedStyle(el).color)), b = l(bg(el));
          return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        }''')
        assert ratio >= 4.5, (theme, selector, ratio)
    evidence(page, 'primary-hover-'+theme)


@pytest.mark.parametrize('ui',[False],indirect=True)
def test_initial_defaults_can_be_saved_without_edits(ui):
    page,tracker,flags=ui
    expect(page.locator('#prefilter-save')).to_be_enabled()
    expect(page.locator('#prefilter-search')).to_be_disabled()
    page.locator('#prefilter-save').click()
    expect(page.locator('#prefilter-form-feedback')).to_contain_text('配置已保存')
    assert len(tracker.db.prefilter_rules())==1
    assert not tracker.adapter.calls


def test_results_first_editor_keyboard_and_draft_summary(ui):
    page,tracker,flags=ui
    page.locator('#prefilter-editor > summary').click()
    expect(page.locator('#prefilter-name')).not_to_be_visible()
    expect(page.locator('#prefilter-keyword-summary')).to_contain_text('Elon Musk')
    assert not tracker.adapter.calls
    page.locator('#prefilter-editor > summary').focus();page.keyboard.press('Enter')
    expect(page.locator('#prefilter-name')).to_be_visible()
    page.locator('#prefilter-min_views').fill('9000')
    page.locator('#prefilter-editor > summary').click()
    expect(page.locator('#prefilter-dirty')).to_contain_text('未保存')
    expect(page.locator('#prefilter-search')).to_be_disabled()
    page.locator('#prefilter-editor > summary').click()
    page.locator('#prefilter-save').click()
    expect(page.locator('#prefilter-name')).not_to_be_visible()
    expect(page.locator('#prefilter-rule-summary')).to_contain_text('9,000')
    page.locator('#prefilter-search').click()
    expect(page.locator('#prefilter-job-status')).to_contain_text('完成')
    page.set_viewport_size(dict(width=1280,height=900))
    page.evaluate('scrollTo(0,0)')
    assert page.locator('.prefilter-table tbody tr').first.bounding_box()['y']<800
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    evidence(page,'revised-desktop-1280')
    page.locator('#prefilter-results details > summary').first.click()
    expect(page.locator('#prefilter-results')).to_contain_text('不代表内容或发布批准')
    count=len(tracker.adapter.calls);page.reload()
    expect(page.locator('#prefilter-results')).to_contain_text('指标合格')
    expect(page.locator('#prefilter-name')).not_to_be_visible()
    assert len(tracker.adapter.calls)==count
    page.set_viewport_size(dict(width=640,height=900))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    evidence(page,'revised-reflow-200')

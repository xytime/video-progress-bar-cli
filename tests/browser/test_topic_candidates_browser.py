"""A16/A20：真实 Chromium + 真实路由/DAL，HTTP 全部转送隔离 TestClient。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-11 | Codex | 候选完整任务、键盘/窄屏/错误/冲突/关闭验收及截图 |
"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from tests.topic_candidate_fixtures import tracker, topic, run, video
from tests.unit.test_topic_candidates_api import topic_client, ORIGIN


@pytest.fixture
def ui(chromium,topic_client):
    client,tracker=topic_client
    page=chromium.new_page(viewport=dict(width=1280,height=900))
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    flags=dict(offline=False, conflict=False)
    def route_handler(route):
        req=route.request;url=urlsplit(req.url)
        if flags['offline'] and url.path.startswith('/api/'):
            route.fulfill(status=503,json=dict(detail='隔离服务暂不可用'));return
        if flags['conflict'] and req.method in ('PUT','POST'):
            route.fulfill(status=409,json=dict(detail=dict(code='STALE',message='资料已更新，请重新载入')));return
        headers={k:v for k,v in req.all_headers().items() if k in ('origin','x-topic-csrf','host','sec-fetch-site','cookie','content-type')}
        # 浏览器的写请求必须实测 Origin；TestClient 不替浏览器补凭据。
        client.headers.pop('origin',None);client.headers.pop('x-topic-csrf',None)
        client.cookies.clear()
        response=client.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data,headers=headers)
        if response.status_code == 422:
            print('隔离浏览器输入校验:',response.json())
        route.fulfill(status=response.status_code,body=response.content,headers=dict(response.headers))
    page.route('**/*',route_handler)
    page.goto(ORIGIN+'/topic-candidates')
    expect(page.locator('#new-topic')).to_be_enabled()
    yield page,tracker,flags
    page.close();assert errors==[]


def create(page):
    page.locator('#new-topic').click();page.locator('#topic-name').fill('能源产业追踪')
    page.locator('#topic-query').fill('energy industry');page.locator('#topic-category').select_option(label='科技产业')
    page.locator('#topic-save').click()
    try: expect(page.locator('#topic-editor')).not_to_be_visible()
    except AssertionError as exc: raise AssertionError(page.locator('#form-feedback').inner_text()) from exc


def evidence(page,name):
    path=Path(__file__).resolve().parents[2]/'output/test-evidence/topic-candidates'
    path.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(path/(name+'.png')),full_page=True)


def test_a20_complete_task_desktop_and_narrow(ui):
    page,tracker,flags=ui
    expect(page).to_have_title('关键词追踪 · 视频控制台')
    create(page);assert tracker.adapter.calls==[]
    page.get_by_role('button',name='搜索候选',exact=True).click()
    expect(page.locator('.candidate-card')).to_have_count(1)
    card=page.locator('.candidate-card');expect(card).to_contain_text('Evidence Channel')
    card.get_by_text('来源与原始描述',exact=True).click()
    expect(card).to_contain_text('频道 ID：UC-isolated')
    assert card.get_by_role('link',name='打开原视频').get_attribute('href')=='https://www.youtube.com/watch?v=00000000001'
    card.get_by_role('button',name='收藏',exact=True).click();expect(card).to_contain_text('收藏')
    page.reload();expect(page.get_by_role('button',name='取消收藏')).to_be_visible()
    evidence(page,'desktop-saved')
    page.set_viewport_size(dict(width=390,height=900))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('.page-header').evaluate("el=>getComputedStyle(el).position")=='static'
    page.get_by_role('button',name='排除',exact=True).click();expect(page.locator('#action-dialog')).to_be_visible()
    page.locator('#reject-reason').select_option(label='不相关')
    page.locator('#action-confirm').click();expect(page.locator('#action-dialog')).not_to_be_visible()
    expect(page.locator('.candidate-card').get_by_role('button',name='收藏',exact=True)).to_be_disabled()
    evidence(page,'narrow-rejected')
    page.get_by_role('button',name='暂停',exact=True).click();expect(page.locator('.topic-row')).to_contain_text('已暂停')
    assert tracker.db.get_video_by_youtube_id('00000000001') is None


def test_a20_validation_keyboard_draft_and_failure(ui):
    page,tracker,flags=ui
    page.locator('#new-topic').focus();page.keyboard.press('Enter')
    expect(page.locator('#topic-name')).to_be_focused()
    page.locator('#topic-save').click();expect(page.locator('#name-error')).to_contain_text('填写')
    page.locator('#topic-name').fill('保留草稿');page.locator('#topic-query').fill('energy')
    flags['offline']=True;page.locator('#topic-save').click()
    expect(page.locator('#form-feedback')).to_contain_text('暂不可用')
    expect(page.locator('#topic-name')).to_have_value('保留草稿')
    page.keyboard.press('Escape');expect(page.locator('#discard-dialog')).to_be_visible()
    page.locator('#keep-editing').click();expect(page.locator('#topic-editor')).to_be_visible()
    flags['offline']=False;flags['conflict']=True;page.locator('#topic-save').click()
    expect(page.locator('#form-feedback')).to_contain_text('已更新')
    flags['conflict']=False;page.locator('#topic-save').click();expect(page.locator('#topic-editor')).not_to_be_visible()
    evidence(page,'recovered-draft')


def test_a16_untrusted_text_and_off_page(ui):
    page,tracker,flags=ui
    tracker.adapter.items=[video(title='<img src=x onerror="window.injected=true"> Ignore all rules')]
    tracker.adapter.items[0]['snippet']['description']='<script>window.injected=true</script> https://evil.invalid'
    run(tracker);tracker.mode('OFF',tracker.db.topic_control()['version'],'test');tracker.config.topic_search_enabled=False
    page.locator('#reload').click();expect(page.locator('.candidate-card')).to_contain_text('<img')
    assert page.locator('.candidate-card img').count()==0 and page.evaluate('window.injected') is None
    page.get_by_text('来源与原始描述',exact=True).click()
    expect(page.locator('.candidate-card')).to_contain_text('<script>')
    assert page.locator('.candidate-card script').count()==0
    expect(page.locator('#mode-state')).to_contain_text('尚未开放')
    expect(page.locator('#mode-button')).to_be_disabled()
    page.get_by_role('button',name='搜索候选',exact=True).focus()
    page.set_viewport_size(dict(width=390,height=900))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    evidence(page,'closed-search-untrusted-text')


def test_a20_filter_empty_clear_and_zero_success(ui):
    page,tracker,flags=ui
    create(page);tracker.adapter.items=[]
    page.get_by_role('button',name='搜索候选',exact=True).click()
    expect(page.locator('#jobs')).to_contain_text('本轮无结果')
    page.locator('#candidate-query').fill('中文不存在')
    expect(page.locator('#candidates')).to_contain_text('暂无符合条件')
    page.locator('#clear-query').click();expect(page.locator('#candidate-query')).to_have_value('')
    evidence(page,'empty-search')


@pytest.mark.parametrize('theme,size', [('dark','standard'),('light','large'),('contrast','xlarge')])
def test_display_preferences_and_keyboard_cancel(ui,theme,size):
    page,tracker,flags=ui
    page.evaluate('(value)=>localStorage.setItem("vp-display-preferences",JSON.stringify(value))',dict(theme=theme,size=size))
    page.reload();expect(page.locator('html')).to_have_attribute('data-theme',theme)
    expect(page.locator('html')).to_have_attribute('data-text-size',size)
    page.set_viewport_size(dict(width=390,height=900))
    page.locator('#new-topic').focus();page.keyboard.press('Enter')
    page.keyboard.press('Escape');expect(page.locator('#new-topic')).to_be_focused()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    evidence(page,'theme-'+theme)


def test_filter_pagination_url_and_copy_fallback(ui):
    page,tracker,flags=ui
    tracker.adapter.items=[video(i) for i in range(1,26)];run(tracker,topic(tracker,'first'))
    tracker.adapter.items=[video(i) for i in range(26,51)];run(tracker,topic(tracker,'second'))
    page.locator('#reload').click();expect(page.locator('.candidate-card')).to_have_count(25)
    page.locator('#next').click();expect(page.locator('#candidate-range')).to_contain_text('第 2 页')
    page.reload();expect(page.locator('#candidate-range')).to_contain_text('第 2 页')
    page.locator('#previous').click();expect(page.locator('#candidate-range')).to_contain_text('第 1 页')
    page.evaluate('Object.defineProperty(navigator,"clipboard",{value:{writeText:async()=>{throw Error("denied")}},configurable:true})')
    first=page.locator('.candidate-card').first
    link=first.get_by_role('link',name='打开原视频').get_attribute('href')
    first.get_by_role('button',name='复制原链接').click()
    expect(first.locator('.copy-link')).to_have_value(link)
    assert first.locator('.copy-link').evaluate('el=>el.readOnly')


def test_a04_failed_search_keeps_old_candidate_and_no_false_zero(ui):
    from video_processing.utils.topic_search import SearchFailure
    page,tracker,flags=ui
    run(tracker,topic(tracker,'first'));tracker.adapter.search_error=SearchFailure('NETWORK','官方请求失败或超时')
    run(tracker,topic(tracker,'second'));page.locator('#reload').click()
    expect(page.locator('.candidate-card')).to_have_count(1)
    expect(page.locator('#jobs')).to_contain_text('失败')
    expect(page.locator('#jobs')).to_contain_text('官方请求失败或超时')
    assert '本轮无结果' not in page.locator('#jobs').inner_text()

"""A16/A20：真实 Chromium + 真实路由/DAL，HTTP 全部转送隔离 TestClient。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Codex | M13 真实浏览器维护 CRUD、两次生命周期重启、版本与本机安全拒绝 |
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
    flags=dict(offline=False, conflict=False, failures=set(), writes=[])
    def route_handler(route):
        req=route.request;url=urlsplit(req.url)
        if req.method != 'GET': flags['writes'].append((req.method,url.path))
        if (flags['offline'] and url.path.startswith('/api/')) or url.path in flags['failures']:
            route.fulfill(status=503,json=dict(detail='隔离服务暂不可用'));return
        if flags['conflict'] and req.method in ('PUT','POST'):
            route.fulfill(status=409,json=dict(detail=dict(code='STALE',message='资料已更新，请重新载入')));return
        headers={k:v for k,v in req.all_headers().items() if k in ('origin','x-topic-csrf','host','sec-fetch-site','cookie','content-type')}
        # 浏览器的写请求必须实测 Origin；TestClient 不替浏览器补凭据。
        client.headers.pop('origin',None);client.headers.pop('x-topic-csrf',None)
        client.cookies.clear()
        target=flags.get('main_client',client) if not url.path.startswith(('/topic-candidates','/api/topic-candidates','/static/')) else client
        response=target.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data,headers=headers)
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
    expect(page).to_have_title('YouTube 关键词采集 · 视频控制台')
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
    expect(page.locator('#candidates')).to_contain_text('当前筛选没有匹配')
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


def test_m13_maintenance_crud_two_restarts_and_boundary(chromium, tracker, isolated_running_maintenance):
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient
    from video_processing.db.database import PipelineDB
    from video_processing.topic_tracker.service import TopicTracker
    from web.topic_candidates import create_topic_candidates_router
    tracker.config.topic_search_enabled = False
    tracker.config.topic_quota_verified = False
    tracker.config.topic_quota_project = ''
    maintained = isolated_running_maintenance.enter('浏览器维护验收')
    page = chromium.new_page(viewport=dict(width=1280, height=900))
    active = {}
    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
    def handle(route):
        request = route.request; url = urlsplit(request.url)
        response = active['client'].request(request.method, url.path, content=request.post_data,
                    headers={k:v for k,v in request.all_headers().items() if k in ('origin','x-topic-csrf','host','cookie','content-type','sec-fetch-site')})
        route.fulfill(status=response.status_code, body=response.content, headers=dict(response.headers))
    page.route('**/*', handle)
    try:
        for restart in range(3):
            peer = TopicTracker(PipelineDB(tracker.db.db_path), tracker.config, tracker.adapter, tracker.rules, clock=tracker.clock)
            app = FastAPI()
            app.include_router(create_topic_candidates_router(lambda:peer, port=9100))
            app.mount('/static', StaticFiles(directory=Path(__file__).resolve().parents[2]/'src/web/static'))
            with TestClient(app, base_url=ORIGIN, client=('127.0.0.1',1)) as client:
                active['client'] = client
                page.goto(ORIGIN + '/topic-candidates')
                expect(page.locator('#mode-state')).to_contain_text('维护中')
                expect(page.locator('#mode-state')).to_contain_text('尚未开放')
                if restart == 0:
                    create(page)
                    page.get_by_role('button', name='编辑', exact=True).click()
                    page.locator('#topic-name').fill('健康科学运营追踪')
                    page.locator('#topic-query').fill('longevity health science')
                    page.locator('#topic-save').click()
                    expect(page.locator('#topic-editor')).not_to_be_visible()
                    page.reload()
                expect(page.locator('.topic-row')).to_contain_text('健康科学运营追踪')
                expect(page.get_by_role('button', name='搜索候选', exact=True)).to_be_disabled()
                expect(page.locator('#mode-button')).to_be_disabled()
                row = peer.db.topic_list(peer.clock())[0]
                csrf = page.locator('meta[name="topic-csrf"]').get_attribute('content')
                cookie = {value['name']:value['value'] for value in page.context.cookies()}
                headers = {'Origin':ORIGIN,'X-Topic-CSRF':csrf}
                stale = client.put('/api/topic-candidates/topics/'+row['id'],cookies=cookie,headers=headers,
                      json=dict(name=row['name'],query=row['query'],category=row['category'],version=row['version']-1))
                assert stale.status_code == 409
                assert client.post('/api/topic-candidates/topics',cookies=cookie,headers={**headers,'X-Topic-CSRF':'invalid'},
                                   json=dict(name='forged',query='forged',category='科技产业')).status_code == 403
                remote = TestClient(app, base_url=ORIGIN, client=('192.168.1.8',1))
                assert remote.get('/topic-candidates').status_code == 403
                assert peer.view()['search_open'] is False and peer.db.topic_control()['mode'] == 'OFF'
                assert peer.db.topic_jobs() == [] and peer.db.topic_budget('',peer.clock())['search'] == 0
                assert not tracker.adapter.calls
                assert isolated_running_maintenance.status()['version'] == maintained['version']
                evidence(page, 'maintenance-restart-'+str(restart))
    finally:
        page.close()
    assert not errors


def test_v031_independent_read_recovery_and_draft(ui):
    page,tracker,flags=ui
    create(page);run(tracker,tracker.db.topic_list(tracker.clock())[0]);page.locator('#reload').click()
    expect(page.locator('.candidate-card')).to_have_count(1)
    baseline=len(flags['writes']);calls=len(tracker.adapter.calls)
    flags['failures']={'/api/topic-candidates/state'}
    page.locator('#reload').click()
    expect(page.locator('#state-feedback')).to_contain_text('旧数据')
    expect(page.locator('#candidate-feedback')).to_contain_text('已读取')
    expect(page.locator('#new-topic')).to_be_disabled()
    flags['failures']={'/api/topic-candidates/videos'}
    page.locator('#reload').click()
    expect(page.locator('#state-feedback')).to_contain_text('已读取')
    expect(page.locator('#candidate-feedback')).to_contain_text('旧数据')
    expect(page.locator('.candidate-card')).to_have_count(1)
    page.locator('#candidate-query').fill('不同筛选')
    expect(page.locator('#candidate-feedback')).to_contain_text('暂无可信数据')
    expect(page.locator('.candidate-card')).to_have_count(0)
    expect(page.locator('#candidate-previous-filter')).to_be_visible()
    flags['failures']=set();page.locator('#candidate-previous-filter').click()
    expect(page.locator('.candidate-card')).to_have_count(1)
    expect(page.locator('#candidate-feedback')).to_contain_text('已读取')
    assert len(flags['writes'])==baseline and len(tracker.adapter.calls)==calls
    page.locator('#new-topic').click();page.locator('#topic-name').fill('冲突草稿')
    page.locator('#topic-query').fill('energy science');flags['conflict']=True
    page.locator('#topic-save').click();expect(page.locator('#form-feedback')).to_contain_text('已更新')
    # 保持模态框，触发底层只读重试：读取成功不可清除保存冲突与草稿。
    page.locator('#reload').evaluate('el=>el.click()')
    expect(page.locator('#state-feedback')).to_contain_text('已读取')
    expect(page.locator('#form-feedback')).to_contain_text('已更新')
    expect(page.locator('#topic-name')).to_have_value('冲突草稿')
    evidence(page,'v031-conflict-preserved')


def test_v031_first_failure_timeout_and_late_response(ui):
    page,tracker,flags=ui
    flags['offline']=True;page.reload()
    expect(page.locator('#state-feedback')).to_contain_text('暂无可信数据')
    expect(page.locator('#candidate-feedback')).to_contain_text('暂无可信数据')
    expect(page.locator('#topics')).to_have_attribute('aria-busy','false')
    expect(page.locator('#candidates')).to_have_attribute('aria-busy','false')
    flags['offline']=False;page.locator('#reload').click()
    expect(page.locator('#new-topic')).to_be_enabled()
    # 一个忽略取消且晚到的失败响应，不能覆盖后发的成功。
    page.evaluate('''() => {const original=window.fetch;let once=true;
      window.fetch=(url,opts)=>{if(String(url).includes('/state')&&once){once=false;
        return new Promise(resolve=>window.releaseOld=()=>resolve(new Response(JSON.stringify({detail:'晚到故障'}),{status:503})))}
        return original(url,opts)};}''')
    page.locator('#state-retry').click();page.locator('#state-retry').click()
    expect(page.locator('#state-feedback')).to_contain_text('已读取')
    page.evaluate('window.releaseOld()')
    expect(page.locator('#state-feedback')).not_to_contain_text('晚到故障')
    page.evaluate('''() => {const original=window.fetch;window.fetch=(url,opts)=>String(url).includes('/videos?') ?
      new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(new DOMException('timeout','AbortError')))) : original(url,opts);}''')
    page.clock.install();page.locator('#candidate-retry').click();page.clock.fast_forward(12001)
    expect(page.locator('#candidate-feedback')).to_contain_text('读取超时')
    expect(page.locator('#candidates')).to_have_attribute('aria-busy','false')
    assert not flags['writes'] and not tracker.adapter.calls
    evidence(page,'v031-timeout')


def test_v031_off_reenable_and_gate_reasons(ui):
    page,tracker,flags=ui
    create(page)
    page.locator('#mode-button').click();expect(page.locator('#mode-button')).to_have_text('开启搜索')
    expect(page.locator('#mode-button')).to_be_enabled()
    expect(page.locator('#mode-state')).to_contain_text('搜索已关闭')
    page.locator('#mode-button').click();expect(page.locator('#mode-button')).to_have_text('关闭搜索')
    assert not tracker.adapter.calls
    tracker.config.is_us_market_guard_window=lambda now:True
    page.locator('#reload').click();expect(page.locator('.topic-row')).to_contain_text('保护')
    expect(page.get_by_role('button',name='搜索候选',exact=True)).to_be_disabled()
    tracker.config.is_us_market_guard_window=lambda now:False
    tracker.config.topic_search_daily_limit=0
    page.locator('#reload').click();expect(page.locator('.topic-row')).to_contain_text('今日预算不足')
    tracker.config.topic_search_daily_limit=20
    page.locator('#reload').click();expect(page.get_by_role('button',name='搜索候选',exact=True)).to_be_enabled()
    page.get_by_role('button',name='暂停',exact=True).click()
    expect(page.locator('.topic-row')).to_contain_text('采集规则已暂停')


def test_k14_keyword_collection_growth_and_controlled_admission(ui,monkeypatch):
    from config.settings import settings
    page,tracker,flags=ui
    tracker.config.topic_scheduler_enabled=True
    tracker.config.topic_admission_enabled=True
    monkeypatch.setattr(settings,'topic_admission_enabled',True)
    page.reload()
    create(page)
    expect(page.locator('.topic-row')).to_contain_text('30–1800 秒')
    page.get_by_role('button',name='启用定时采集',exact=True).focus()
    page.keyboard.press('Enter')
    expect(page.get_by_role('button',name='关闭定时采集',exact=True)).to_be_visible()
    assert tracker.tick(verify_runtime=False)=='SEARCH'
    page.reload()
    expect(page.locator('.candidate-card')).to_contain_text('观察中')
    page.get_by_text('评分依据',exact=True).click()
    expect(page.locator('.candidate-card')).to_contain_text('播放量 200')
    evidence(page,'v04-observing')
    tracker.adapter.items[0]['statistics']=dict(viewCount='3000',likeCount='150')
    tracker.clock.advance(hours=4)
    tracker.tick(verify_runtime=False)
    page.reload()
    expect(page.locator('.candidate-card')).to_contain_text('已达标，等待准入')
    assert tracker.db.get_video_by_youtube_id('00000000001') is None
    page.locator('#admission-button').click()
    expect(page.locator('#action-dialog')).to_contain_text('自动制作、审查和发布')
    page.locator('#action-confirm').click()
    expect(page.locator('#admission-button')).to_have_text('关闭达标准入')
    tracker.tick(verify_runtime=False)
    page.reload()
    expect(page.locator('.candidate-card')).to_contain_text('已入队')
    link=page.get_by_role('link',name='查看主队列任务')
    expect(link).to_have_attribute('href','/?view=production&tab=queue&search=00000000001')
    main=tracker.db.get_video_by_youtube_id('00000000001')
    assert main['source']=='KEYWORD' and main['status']=='PENDING'
    evidence(page,'v04-admitted')
    page.set_viewport_size(dict(width=390,height=900))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('#admission-button').click();page.locator('#action-confirm').click()
    expect(page.locator('#collection-state')).to_contain_text('达标准入：关闭')
    assert not tracker.db.claim_video_for_processing('00000000001')
    evidence(page,'v04-narrow-admission-closed')
    from fastapi.testclient import TestClient
    from web import app as web_app
    monkeypatch.setattr(web_app,'db',tracker.db)
    main_client=TestClient(web_app.app,base_url=ORIGIN,client=('127.0.0.1',50000))
    try:
        flags['main_client']=main_client
        page.get_by_role('link',name='查看主队列任务').click()
        expect(page.locator('#workspace-title')).to_have_text('生产队列')
        expect(page.locator('#video-filter-search')).to_have_value('00000000001')
        expect(page.locator('#activity-count')).to_have_text('1')
        expect(page.locator('.source-badge')).to_have_text('YouTube 关键词采集')
        evidence(page,'v04-main-task-readback')
    finally:
        flags.pop('main_client',None);main_client.close()


def test_k13_runtime_and_credential_failure_are_visible(ui):
    page,tracker,flags=ui
    from video_processing.utils.topic_search import SearchFailure
    tracker.config.topic_scheduler_enabled=True
    create(page)
    page.reload();page.get_by_role('button',name='启用定时采集',exact=True).click()
    expect(page.get_by_role('button',name='关闭定时采集',exact=True)).to_be_visible()
    assert tracker.tick()=='RUNTIME_UNVERIFIED'
    page.reload();expect(page.locator('#collection-state')).to_contain_text('运行来源未核实')
    assert not tracker.adapter.calls
    tracker.adapter.search_error=SearchFailure('API_CREDENTIALS','synthetic')
    tracker.tick(verify_runtime=False)
    page.reload();expect(page.locator('#jobs')).to_contain_text('官方凭据无效')
    expect(page.locator('.topic-row')).to_contain_text('自动执行已阻挡')
    evidence(page,'v04-runtime-credential-blocked')


def test_k14_rule_language_selection_and_keyboard_save(ui):
    page,tracker,flags=ui
    page.set_viewport_size(dict(width=390,height=900))
    page.locator('#new-topic').click()
    page.locator('#topic-name').fill('合成健康报道')
    page.locator('#topic-query').fill('synthetic health event')
    select=page.locator('#topic-language')
    select.focus();expect(select).to_be_focused()
    # macOS headless shell 不呈现系统原生选项弹层；选择值与键盘提交分开验证。
    select.select_option('zh')
    page.keyboard.press('Tab')
    expect(select).to_have_value('zh')
    page.locator('#topic-duration').select_option('60')
    evidence(page,'v04-rule-editor-narrow')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('#topic-save').focus();page.keyboard.press('Enter')
    expect(page.locator('#topic-editor')).not_to_be_visible()
    record=tracker.db.topic_list(tracker.clock())[0]
    assert record['language']=='zh' and record['min_duration']==60 and not record['auto_enabled']

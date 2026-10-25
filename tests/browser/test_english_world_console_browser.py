"""英语世界桌面工作台真实 Chromium 交互验证，API 仅使用隔离合成数据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.0.0 | 2026-10-25 | Codex | 验证 v10 筛选、历史折叠、任务抽屉、确认与 URL 恢复。 |
"""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import mimetypes
import hashlib
import shutil
import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from tests.unit.test_english_world_console import console_data as source_console_data, ORIGIN
from video_processing.db.database import PipelineDB
from web.english_world_console import create_english_console_router


def eligibility(action, allowed=False, reason='此状态不支持此操作'):
    return {action: {'allowed': allowed, 'reason': '可执行' if allowed else reason}}


def make_row(index, *, old=False, run=False):
    task_id = f"{'run:' if run else 'job:'}fixture-{index:02d}"
    status = 'CANDIDATES_READY' if index == 1 else ('UNCERTAIN' if index == 2 else 'FAILED' if index == 3 else 'READY_FOR_REVIEW' if index == 4 else 'WAITING')
    allowed = {'select_candidate': index == 1, 'confirm_production': False, 'approve_submission': index == 4,
               'hold': index == 4, 'resume': False, 'record_outcome': index == 2, 'research': index == 3}
    row = {'task_id': task_id, 'record_type': 'run' if run else 'task', 'title': f'英语学习任务 {index:02d}',
           'source': 'OceanWeekly' if index % 2 else 'TechNews', 'current_step': '语言复核' if index == 3 else '等待人工处理',
           'block_reason': '校对回执失败，需人工核实。' if index == 3 else '等待选题或人工确认。',
           'last_activity': '2026-10-25T05:20:00+00:00', 'created_at': '2026-10-10T05:20:00+00:00' if old else '2026-10-25T05:20:00+00:00',
           'status': status, 'trigger': 'manual' if index % 2 else 'scheduled', 'revision': f'rev-{index}',
           'age_bucket': 'history' if old else 'current', 'action_eligibility': eligibility('select_candidate', allowed['select_candidate'])}
    row['action_eligibility'].update({key: {'allowed': value, 'reason': '可执行' if value else '此状态不支持此操作'} for key, value in allowed.items() if key != 'select_candidate'})
    return row


@pytest.fixture
def ui(chromium, tmp_path):
    db, output, _ = source_console_data.__wrapped__(tmp_path)
    app = FastAPI()
    app.include_router(create_english_console_router(db, port=9100, output=output))
    app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parents[2]/"src/web/static"), name="static")
    client = TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000))
    page = chromium.new_page(viewport={'width': 1440, 'height': 950})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    tasks = [make_row(i) for i in range(1, 24)] + [make_row(24, old=True), make_row(25, old=True)]
    runs = [make_row(90, run=True)]
    list_error = {'enabled': False}
    actions = []
    research_timeout_once = {'enabled': False, 'used': False}
    def route(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.path.startswith('/static/'):
            asset = Path(__file__).resolve().parents[2] / 'src/web/static' / parsed.path.removeprefix('/static/')
            if asset.exists():
                route.fulfill(status=200, body=asset.read_bytes(), content_type=mimetypes.guess_type(asset.name)[0] or 'application/octet-stream')
            else:
                route.fulfill(status=404)
            return
        if parsed.path == '/english-world':
            response = client.get('/english-world')
            route.fulfill(status=response.status_code, body=response.content,
                          content_type=response.headers.get('content-type', 'text/html'), headers={'Set-Cookie': response.headers.get('set-cookie', '')})
            return
        if parsed.path == '/api/english-world/workbench':
            if list_error['enabled']:
                route.fulfill(status=503, json={'detail': 'synthetic failure'}); return
            query = parse_qs(parsed.query)
            view = query.get('view', ['attention'])[0]
            data = runs if view == 'runs' else tasks
            q = query.get('q', [''])[0].strip().casefold()
            status = query.get('status', [''])[0]
            trigger = query.get('trigger', [''])[0]
            data = [r for r in data if (not q or q in (r['title']+' '+r['source']+' '+r['task_id']).casefold()) and
                    (not status or r['status'] == status) and (not trigger or r['trigger'] == trigger)]
            old = [r for r in data if r['age_bucket'] == 'history']
            current = [r for r in data if r['age_bucket'] != 'history']
            page_num = int(query.get('page', ['1'])[0]); start=(page_num-1)*20
            expanded = query.get('history', ['false'])[0] in ('true','1')
            items = data if view=='all' else current + (old if expanded else [])
            total = len(data) if view=='all' else len(current)
            route.fulfill(json={'view':view,'filters':{},'page':page_num,'page_size':20,'pages':max(1,(total+19)//20),
                                'total':total,'items':items[start:start+20],
                                'summary':{'latest_run':runs[0],'active':2,'waiting':5,'next_scheduled':{'time':'14:00'}},
                                'history':{'count':len(old),'items':old if expanded else [],'collapsed':not expanded},'schedule':{}})
            return
        if parsed.path == '/api/english-world/workbench/media':
            route.fulfill(status=200, body=b'fixture media', content_type='video/mp4'); return
        if parsed.path == '/api/english-world/workbench/task':
            task = parse_qs(parsed.query).get('task',[''])[0]
            ix = int(task.split('-')[-1]) if task.startswith('job:') else 90
            row = next((x for x in tasks+runs if x['task_id']==task), make_row(ix))
            route.fulfill(json={'task':row,'steps':[{'id':'language_review','label':'语言复核','state':'failed' if ix==3 else 'complete','started_at':'2026-10-25T05:00:00Z','ended_at':'2026-10-25T05:20:00Z','last_activity':'2026-10-25T05:20:00Z','detail':'质量报告需要复核。'},{'id':'association','label':'运行关联','state':'unverified','started_at':None,'ended_at':None,'last_activity':None,'detail':'历史关联不足，无法确认该阶段归属。'}],
                                'safe_diagnostics':{'text':'合成安全诊断摘要，仅展开后显示。'},
                                'package':{'title':f'当前实际成片 {ix}','platform':'WeChat Channels','package_hashes':{'artifact_sha256':'sha256:fixture-video','manifest_sha256':'sha256:fixture-manifest','title_sha256':'sha256:title','copy_sha256':'sha256:copy','cover_sha256':'sha256:cover','cover_provenance_sha256':'sha256:cover-source'},'hash_bound_to_review':True,'product_summary':{'status':'FROZEN','intent':'NONE','name':None,'summary':'无需平台商品'},'quality_summary':{'status':'通过','items':[{'kind':'audio','status':'通过','summary':'音频正常'}]}},
                            'evidence':[{'kind':'video','status':'已绑定','generated_at':'2026-10-25T05:20:00Z','identity_status':'bound to review item','summary':'真实成片证据','issues':[],'href':'/api/english-world/workbench/media?task=x&kind=video'},
                                            {'kind':'cover','status':'已绑定','generated_at':'2026-10-25T05:20:00Z','identity_status':'bound to review item','summary':'真实封面证据','issues':[]},
                                            {'kind':'submission','status':'结果不明','generated_at':'2026-10-25T05:20:00Z','identity_status':'平台身份待核验','summary':'提交回执未确认','issues':[]}],
                                'audit_summary':{'action':'record_outcome','status':'已记录','dispatch_state':'FAILED_OR_UNKNOWN','verification_note':'用户声明尚无结构化凭据','evidence_identity':'NOT_VERIFIED'},
                            'actions':row['action_eligibility'],'candidates':[{'candidate_id':'cand-1','title':'Candidate title','source':'OceanWeekly','duration':'8:12'}]})
            return
        if parsed.path == '/api/english-world/workbench/actions' and request.method == 'POST':
            body=json.loads(request.post_data or '{}');actions.append(body)
            if research_timeout_once['enabled'] and body.get('action')=='research' and not research_timeout_once['used']:
                research_timeout_once['used']=True;route.abort('timedout');return
            route.fulfill(json={'ok':True,'task_id':'job:new-research','audit_id':'audit-1','operation_id':body.get('operation_id'),'revision':'rev-new'});return
        route.fulfill(status=404, json={'detail':'not found'})
    page.route('**/*', route)
    page.goto(ORIGIN+'/english-world')
    expect(page.locator('#ew-feedback')).to_contain_text('已读取')
    yield page, list_error, actions, research_timeout_once
    page.close()
    assert not errors


def test_desktop_filters_history_and_navigation(ui):
    page,_,_,_=ui
    expect(page.locator('#ew-rows tr')).to_have_count(20)
    expect(page.locator('#ew-history')).to_be_visible()
    expect(page.locator('#ew-history-label')).to_contain_text('2')
    expect(page.locator('#ew-summary .ew-summary-item').nth(2).locator('strong')).to_have_text('14:00')
    page.set_viewport_size({'width':1366,'height':768})
    evidence=Path(__file__).resolve().parents[2]/'output/test-evidence/english-world-console'
    evidence.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(evidence/'desktop-1366-768-firstfold.png'),full_page=False)
    page.set_viewport_size({'width':1440,'height':950})
    page.locator('#ew-next').click()
    expect(page.locator('#ew-rows tr')).to_have_count(3)
    page.locator('#ew-q').fill('ocean')
    page.wait_for_timeout(400)
    page.locator('#ew-trigger').select_option('manual')
    page.locator('#ew-status').select_option('failed')
    expect(page.locator('#ew-rows tr')).to_have_count(12)
    expect(page.locator('#ew-chips')).to_contain_text('搜索：ocean')
    expect(page.locator('#ew-chips')).to_contain_text('状态：失败')
    expect(page.locator('#ew-chips')).to_contain_text('触发：人工')
    assert 'q=ocean' in page.url and 'trigger=manual' in page.url and 'status=failed' in page.url
    page.locator('#ew-trigger').select_option('scheduled')
    expect(page.locator('#ew-chips')).to_contain_text('触发：定时')
    page.locator('#ew-trigger').select_option('manual')
    page.locator('#ew-status').select_option('')
    expect(page.locator('#ew-history')).to_be_visible()
    page.locator('#ew-history').locator('summary').click()
    expect(page.locator('#ew-history-rows tr')).to_have_count(1)
    page.locator('#ew-history-rows .ew-task-title').first.click()
    expect(page.locator('#ew-drawer')).to_be_visible()
    expect(page.locator('#ew-drawer-body')).to_contain_text('质量报告与提交证据')
    expect(page.locator('#ew-drawer-body')).to_contain_text('关联未核实')
    expect(page.locator('#ew-safe-diagnostics-text')).not_to_be_visible()
    diagnostic_summary=page.locator('#ew-drawer-body details summary').filter(has_text='查看安全诊断摘要')
    diagnostic_summary.click()
    expect(page.locator('#ew-safe-diagnostics-text')).to_be_visible()
    expect(page.locator('#ew-safe-diagnostics-text')).to_have_text('合成安全诊断摘要，仅展开后显示。')
    expect(page.locator('#ew-drawer-actions button[data-action="approve_submission"]')).to_have_count(0)
    def assert_drawer_rows_do_not_overlap():
        geometry=page.locator('#ew-drawer').evaluate("el=>{const d=el.getBoundingClientRect(),b=el.querySelector('#ew-drawer-body').getBoundingClientRect(),f=el.querySelector('#ew-drawer-actions').getBoundingClientRect();return {bodyBottom:b.bottom,footerTop:f.top,footerBottom:f.bottom,drawerBottom:d.bottom,scrolling:el.querySelector('#ew-drawer-body').scrollHeight>el.querySelector('#ew-drawer-body').clientHeight}}")
        assert geometry['bodyBottom'] <= geometry['footerTop']+1 and geometry['footerBottom'] <= geometry['drawerBottom']+1 and geometry['scrolling'], geometry
    capture(page,'drawer-1440-950')
    page.set_viewport_size({'width':1366,'height':768})
    assert_drawer_rows_do_not_overlap()
    diagnostic_summary.click();expect(page.locator('#ew-safe-diagnostics-text')).not_to_be_visible()
    diagnostic_summary.click();expect(page.locator('#ew-safe-diagnostics-text')).to_be_visible()
    capture(page,'drawer-1366-768')
    page.evaluate('document.documentElement.style.fontSize="20px"')
    page.set_viewport_size({'width':1366,'height':950})
    assert_drawer_rows_do_not_overlap()
    diagnostic_summary.click();expect(page.locator('#ew-safe-diagnostics-text')).not_to_be_visible()
    diagnostic_summary.click();expect(page.locator('#ew-safe-diagnostics-text')).to_be_visible()
    capture(page,'drawer-1366-large-type')
    page.evaluate('document.documentElement.style.fontSize=""')
    page.set_viewport_size({'width':640,'height':800})
    assert_drawer_rows_do_not_overlap()
    diagnostic_summary.click();expect(page.locator('#ew-safe-diagnostics-text')).not_to_be_visible()
    diagnostic_summary.click();expect(page.locator('#ew-safe-diagnostics-text')).to_be_visible()
    capture(page,'drawer-narrow-640-800')
    page.keyboard.press('Escape')
    expect(page.locator('#ew-drawer')).not_to_be_visible()
    expect(page.locator('#ew-history-rows .ew-task-title').first).to_be_focused()
    capture(page,'desktop')
    for theme in ['dark','light','contrast']:
        page.evaluate('(theme)=>{document.documentElement.dataset.theme=theme;document.documentElement.style.fontSize="20px"}', theme)
        page.set_viewport_size({'width':1366,'height':950})
        capture(page,f'{theme}-1366-large-type')
    page.evaluate('document.documentElement.style.fontSize=""')


def test_review_action_confirmation_and_evidence(ui):
    page,_,actions,_=ui
    page.locator('#ew-q').fill('04');page.wait_for_timeout(400)
    page.locator('#ew-rows .ew-task-title').click()
    expect(page.locator('#ew-drawer-actions')).to_contain_text('批准投稿')
    opener=page.locator('#ew-drawer-actions button[data-action="approve_submission"]')
    opener.click()
    expect(page.locator('#ew-confirm')).to_be_visible()
    expect(page.locator('#ew-drawer-body')).to_contain_text('操作：登记核验结果')
    expect(page.locator('#ew-drawer-body')).to_contain_text('执行状态：执行结果未确认')
    expect(page.locator('#ew-drawer-body')).to_contain_text('核验说明：用户声明尚无结构化凭据')
    expect(page.locator('#ew-drawer-body')).not_to_contain_text('[object Object]')
    expect(page.locator('#ew-confirm-cancel')).to_be_focused()
    expect(page.locator('#ew-confirm-body')).to_contain_text('版本：rev-4')
    expect(page.locator('#ew-confirm-body')).to_contain_text('必需商品 / 制作意图')
    expect(page.locator('#ew-confirm-body')).to_contain_text('无需平台商品')
    expect(page.locator('#ew-confirm-body')).to_contain_text('投稿前质量摘要')
    expect(page.locator('#ew-confirm-body img[alt="当前审核封面预览"]')).to_have_count(1)
    expect(page.locator('#ew-confirm-go')).to_be_disabled()
    page.locator('#ew-confirm-cancel').click()
    expect(page.locator('#ew-confirm')).not_to_be_visible()
    page.locator('#ew-drawer-body').get_by_role('button',name='播放成片').click()
    expect(page.locator('#ew-report')).to_be_visible()
    expect(page.locator('#ew-report-body video')).to_have_attribute('controls','')
    capture(page,'review-drawer')


def test_new_research_confirmation_and_uncertain_no_resend(ui):
    page,_,actions,research_timeout_once=ui
    page.locator('#ew-q').fill('02');page.wait_for_timeout(400)
    page.locator('#ew-rows .ew-task-title').click()
    expect(page.locator('#ew-drawer-actions')).to_contain_text('登记核验结果')
    expect(page.locator('#ew-drawer-actions')).not_to_contain_text('重发')
    page.locator('#ew-drawer-actions button[data-action="record_outcome"]').click()
    expect(page.locator('#ew-confirm-cancel')).to_be_focused()
    expect(page.locator('#ew-confirm-body')).to_contain_text('不会启动投稿')
    page.locator('#ew-confirm-cancel').click()
    page.locator('#ew-drawer-close').click()
    page.locator('#ew-new').click()
    page.locator('#ew-research-url').fill('https://www.youtube.com/watch?v=abc')
    page.locator('#ew-research-submit').click()
    expect(page.locator('#ew-confirm')).to_be_visible()
    expect(page.locator('#ew-confirm-cancel')).to_be_focused()
    page.locator('#ew-confirm-cancel').click()
    assert actions == []
    page.locator('#ew-q').fill('03');page.wait_for_timeout(400)
    page.locator('#ew-rows .ew-task-title').click()
    expect(page.locator('#ew-drawer-actions')).to_contain_text('开始新研究')
    page.locator('#ew-drawer-actions button[data-action="research"]').click()
    expect(page.locator('#ew-confirm-body')).to_contain_text('创建一条新的研究任务；当前任务记录保留')
    page.locator('#ew-confirm-cancel').click();page.locator('#ew-drawer-close').click()
    page.locator('#ew-q').fill('');page.wait_for_timeout(400)
    page.evaluate("""() => {
      window.__ewActionTimeoutMs=5;
      const nativeFetch=window.fetch.bind(window);let first=true;
      window.fetch=(url,options={})=>{
        if(String(url).includes('/api/english-world/workbench/actions')&&first){
          first=false;window.__firstOperationBody=JSON.parse(options.body);
          return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('The operation was aborted.','AbortError')),{once:true}));
        }
        return nativeFetch(url,options);
      };
    }""")
    page.locator('#ew-new').click();page.locator('#ew-research-url').fill('https://www.youtube.com/watch?v=abc');page.locator('#ew-research-submit').click()
    page.locator('#ew-confirm-go').click()
    expect(page.locator('#ew-confirm-feedback')).to_contain_text('结果尚未确认')
    expect(page.locator('#ew-confirm-feedback button')).to_have_text('核对原操作')
    expect(page.locator('#ew-confirm-feedback')).to_contain_text('请求超时')
    assert len(actions)==0
    first=page.evaluate('window.__firstOperationBody')
    page.locator('#ew-confirm-feedback button').click()
    expect(page.locator('#ew-feedback')).to_contain_text('已读取')
    assert len(actions)==1 and actions[0]==first


@pytest.mark.parametrize('width',[390,320])
def test_mobile_drawer_accessibility_and_no_page_overflow(ui,width):
    page,_,_,_=ui;page.set_viewport_size({'width':width,'height':844})
    page.locator('#ew-rows .ew-task-title').first.click()
    expect(page.locator('#ew-drawer')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate('Array.from(document.querySelectorAll("body *")).filter(e=>{const r=e.getBoundingClientRect();return r.right>innerWidth+1&&r.width>1}).slice(0,20).map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().toJSON()])')
    expect(page.locator('#ew-drawer-body')).to_be_visible()
    page.locator('#ew-drawer-close').click()
    expect(page.locator('#ew-rows .ew-task-title').first).to_be_focused()
    capture(page,f'mobile-{width}')


def capture(page,name):
    directory=Path(__file__).resolve().parents[2]/'output/test-evidence/english-world-console'
    directory.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(directory/(name+'.png')),full_page='drawer' not in name)


def test_url_deeplink_history_and_stale_list_error(ui):
    page, list_error, _, _ = ui
    page.goto(ORIGIN+'/english-world?category=all&page=1')
    expect(page.locator('[data-view="all"]')).to_have_attribute('aria-pressed','true')
    first=page.locator('#ew-rows .ew-task-title').first
    first.click()
    expect(page.locator('#ew-drawer')).to_be_visible()
    assert 'task=job%3Afixture-' in page.url
    page.locator('[data-view="runs"]').evaluate('(button)=>button.click()')
    expect(page.locator('#ew-drawer')).not_to_be_visible()
    expect(page.locator('#ew-drawer-actions [data-action]')).to_have_count(0)
    page.keyboard.press('Escape')
    page.locator('[data-view="all"]').click()
    expect(page.locator('#ew-count')).to_contain_text('共 25 条')
    page.locator('#ew-next').click()
    expect(page.locator('#ew-rows')).to_contain_text('英语学习任务 24')
    list_error['enabled']=True
    page.locator('#ew-rows .ew-task-title').first.click()
    expect(page.locator('#ew-drawer')).to_be_visible()
    page.locator('#ew-refresh').evaluate('(button)=>button.click()')
    expect(page.locator('#ew-feedback')).to_contain_text('synthetic failure')
    expect(page.locator('#ew-rows tr')).to_have_count(5)
    expect(page.locator('#ew-drawer-actions')).to_contain_text('已清除旧操作资格')


def test_real_router_research_select_and_production_confirmation(chromium,tmp_path):
    db,output,_=source_console_data.__wrapped__(tmp_path)
    def fake_research(job_id):
        assert db.claim_english_world_job_for_research(job_id)
        db.complete_english_world_research(job_id,candidates=[{
            'id':'candidate-fixture','source_url':'https://www.youtube.com/watch?v=fixture123',
            'youtube_id':'fixture123','source_title':'Ocean discovery','source_channel':'Ocean Weekly','source_channel_id':'UCfixture',
            'topic':'Ocean Science','learning_value':'Clear age-appropriate learning','safety_note':'No safety concerns',
            'caption_status':'available','recommendation_score':88}])
    app=FastAPI();app.include_router(create_english_console_router(db,port=9100,output=output,start_research=fake_research))
    app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[2]/'src/web/static'),name='static')
    client=TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50000))
    page=chromium.new_page(viewport={'width':1366,'height':950});errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def route_handler(route):
        request=route.request;parsed=urlsplit(request.url)
        if parsed.path.startswith('/static/'):
            asset=Path(__file__).resolve().parents[2]/'src/web/static'/parsed.path.removeprefix('/static/')
            route.fulfill(status=200,body=asset.read_bytes(),content_type=mimetypes.guess_type(asset.name)[0] or 'application/octet-stream') if asset.exists() else route.fulfill(status=404)
            return
        headers={key:value for key,value in request.headers.items() if key in {'cookie','origin','x-runtime-csrf','accept','content-type'}}
        response=client.request(request.method,parsed.path+('?' + parsed.query if parsed.query else ''),headers=headers,content=request.post_data)
        out_headers={key:value for key,value in response.headers.items() if key in {'content-type','set-cookie','cache-control','accept-ranges','content-range','x-content-type-options'}}
        route.fulfill(status=response.status_code,body=response.content,headers=out_headers)
    page.route('**/*',route_handler);page.goto(ORIGIN+'/english-world')
    expect(page.locator('#ew-feedback')).to_contain_text('已读取')
    page.locator('#ew-new').click();page.locator('#ew-research-url').fill('https://www.youtube.com/watch?v=fixture123');page.locator('#ew-research-submit').click()
    expect(page.locator('#ew-confirm')).to_be_visible();page.locator('#ew-confirm-go').click()
    expect(page.locator('#ew-drawer')).to_be_visible();expect(page.locator('#ew-drawer-actions')).to_contain_text('选择候选')
    page.locator('#ew-drawer-actions button[data-action="select_candidate"]').click()
    expect(page.locator('#ew-payload-candidate')).to_have_value('candidate-fixture')
    page.locator('#ew-confirm-go').click()
    expect(page.locator('#ew-drawer-actions')).to_contain_text('确认制作')
    page.locator('#ew-drawer-actions button[data-action="confirm_production"]').click()
    expect(page.locator('#ew-confirm-body')).to_contain_text('不会直接批准投稿')
    page.locator('#ew-confirm-go').click()
    expect(page.locator('#ew-feedback')).to_contain_text('已读取')
    assert not errors
    page.close()


def test_real_media_endpoint_mp4_range_and_cover_load(chromium,tmp_path):
    db,output,_=source_console_data.__wrapped__(tmp_path)
    fixture=Path(__file__).resolve().parents[1]/'fixtures/english_world_workbench'
    package=output/'workbench-browser-media-fixture';package.mkdir(parents=True)
    sources={'mp4':fixture/'tiny.mp4.fixture','cover':fixture/'tiny.png'}
    paths={key:package/source.name for key,source in sources.items()}
    for key,source in sources.items():shutil.copyfile(source,paths[key])
    for key in ('manifest','title','copy','cover_provenance'):
        path=package/f'{key}.json';path.write_text(json.dumps({'fixture':True,'kind':key}));paths[key]=path
    hashes={key:hashlib.sha256(path.read_bytes()).hexdigest() for key,path in paths.items()}
    item=db.create_english_world_review_item(
        artifact_sha256=hashes['mp4'],manifest_sha256=hashes['manifest'],title_sha256=hashes['title'],
        copy_sha256=hashes['copy'],cover_sha256=hashes['cover'],cover_provenance_sha256=hashes['cover_provenance'],
        title='隔离测试成片',mp4_path=str(paths['mp4']),manifest_path=str(paths['manifest']),title_path=str(paths['title']),
        copy_path=str(paths['copy']),cover_path=str(paths['cover']),cover_provenance_path=str(paths['cover_provenance']))
    app=FastAPI();app.include_router(create_english_console_router(db,port=9100,output=output))
    app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[2]/'src/web/static'),name='static')
    client=TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50000))
    page=chromium.new_page(viewport={'width':1366,'height':950})
    def route_handler(route):
        request=route.request;parsed=urlsplit(request.url)
        if parsed.path.startswith('/static/'):
            asset=Path(__file__).resolve().parents[2]/'src/web/static'/parsed.path.removeprefix('/static/')
            route.fulfill(status=200,body=asset.read_bytes(),content_type=mimetypes.guess_type(asset.name)[0] or 'application/octet-stream') if asset.exists() else route.fulfill(status=404)
            return
        headers={key:value for key,value in request.headers.items() if key in {'cookie','origin','x-runtime-csrf','accept','content-type','range'}}
        response=client.request(request.method,parsed.path+('?' + parsed.query if parsed.query else ''),headers=headers,content=request.post_data)
        out_headers={key:value for key,value in response.headers.items() if key in {'content-type','set-cookie','cache-control','accept-ranges','content-range','x-content-type-options'}}
        route.fulfill(status=response.status_code,body=response.content,headers=out_headers)
    page.route('**/*',route_handler);page.goto(ORIGIN+'/english-world')
    task_id='review:'+item['id']
    range_response=client.get(f'/api/english-world/workbench/media?task={task_id}&kind=video',headers={'Range':'bytes=0-99'})
    assert range_response.status_code==206
    assert range_response.headers.get('content-range','').startswith('bytes 0-99/')
    page.evaluate("(url)=>{const v=document.createElement('video');v.id='verified-media-video';v.controls=true;document.body.append(v);v.src=url}",f'/api/english-world/workbench/media?task={task_id}&kind=video')
    page.wait_for_function("document.querySelector('#verified-media-video')?.readyState>=1")
    assert page.locator('#verified-media-video').evaluate('(v)=>Number.isFinite(v.duration)&&v.duration>0')
    page.locator('#verified-media-video').evaluate("v=>{v.currentTime=Math.min(.5,v.duration/2)}")
    page.wait_for_function("document.querySelector('#verified-media-video')?.currentTime>0")
    page.evaluate("(url)=>{const img=document.createElement('img');img.id='verified-media-cover';document.body.append(img);img.src=url}",f'/api/english-world/workbench/media?task={task_id}&kind=cover')
    page.wait_for_function("document.querySelector('#verified-media-cover')?.naturalWidth>0")
    assert page.locator('#verified-media-cover').evaluate('(img)=>img.naturalWidth===32&&img.naturalHeight===24')
    page.close()

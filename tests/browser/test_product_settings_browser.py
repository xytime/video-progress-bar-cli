"""真实 Chromium + 实际 FastAPI 路由；所有 HTTP 在隔离夹具内转送 TestClient。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.2 | 2026-10-25 | Codex | 验证首选规则与旧冻结决定隔离，并核对目录选品身份。 |
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import expect, TimeoutError as PlaywrightTimeoutError
from tests.browser_fixtures import chromium
from tests.unit.test_wechat_product_groups import api_setup, data
from video_processing.utils.wechat_product_config import load_policy

@pytest.fixture
def ui(chromium, api_setup):
    client,active,status,records=api_setup
    page=chromium.new_page(viewport={'width':1280,'height':900})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    flags={'offline':False,'conflict':False,'empty':False,'slow_save':False,'writes':0,'records':records}
    def route(route):
        req=route.request;path=urlparse(req.url).path
        if flags['offline'] and path.startswith('/api/'):
            route.fulfill(status=503,json={'detail':'隔离测试：服务暂不可用'});return
        if flags['conflict'] and req.method=='PUT':
            route.fulfill(status=409,json={'detail':'配置已被其他窗口更新。请先重新载入，再修改保存。'});return
        if flags['empty'] and path.endswith('/videos'):
            route.fulfill(json={'videos':[],'limit':100});return
        if req.method=='PUT': flags['writes']+=1
        if flags.get('hold') == (req.method,path):
            def release():
                response=client.request(req.method,path,content=req.post_data,headers={'Content-Type':'application/json'})
                route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
            flags['release']=release
            return
        response=client.request(req.method,path,content=req.post_data,headers={'Content-Type':'application/json'})
        route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',route)
    page.goto('http://settings-test.invalid/product-settings')
    expect(page.locator('#editor')).to_be_enabled()
    yield page,active,status,flags
    page.close();assert errors==[]


@pytest.fixture
def frozen_ui(chromium, tmp_path, data):
    """真实 DAL 冻结快照与路由，浏览器只操作隔离配置，不触发发布。"""
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient
    from video_processing.db.database import PipelineDB
    from video_processing.utils.wechat_product_task import freeze_task_product_decision
    from web.product_settings import create_product_settings_router

    active = tmp_path / 'policy.json'
    active.write_text(json.dumps(data))
    status = tmp_path / 'runtime.json'
    output = tmp_path / 'output'
    output.mkdir()
    db = PipelineDB(str(tmp_path / 'preview.sqlite'))
    now = datetime(2026, 10, 11, 2, tzinfo=timezone.utc)
    snapshots = {}
    preview_keys = {}
    for name, intent, content_type in (
        ('first', 'AUTO', 'ENGLISH_WORLD_SHORT'),
        ('later', 'AUTO', 'ENGLISH_WORLD_SHORT'),
        ('none', 'NONE', 'GENERAL'),
    ):
        youtube_id = 'frozen-' + name
        task_id = f'pipeline:{youtube_id}:0'
        db.add_video(youtube_id, name + ' 冻结测试', 'test-channel',
                     view_count=1000, like_count=0, content_type=content_type,
                     product_intent=intent)
        if content_type == 'ENGLISH_WORLD_SHORT':
            db.register_product_production(task_id, account_id='local-profile:isolated-test', now=now)
        snapshots[name] = freeze_task_product_decision(db, task_id, dict(
            youtube_id=youtube_id, content_type=content_type, product_intent=intent,
            view_count=1000, like_count=0), active, now=now)
        preview_keys[name] = next(row['preview_key'] for row in db.get_product_preview_videos()
                                  if row['youtube_id'] == youtube_id)
    app = FastAPI()
    app.include_router(create_product_settings_router(
        active=active, status=status, output=output,
        videos=db.get_product_preview_videos,
        production_lookup=db.get_product_production,
        decision_lookup=db.get_product_task_decision))
    app.mount('/static', StaticFiles(directory=Path(__file__).resolve().parents[2] / 'src/web/static'))
    page = chromium.new_page(viewport={'width': 1280, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    with TestClient(app) as client:
        def route(route):
            request = route.request
            response = client.request(request.method, urlparse(request.url).path,
                                      content=request.post_data,
                                      headers={'Content-Type': 'application/json'})
            route.fulfill(status=response.status_code, body=response.content,
                          content_type=response.headers.get('content-type', 'text/plain'))
        page.route('**/*', route)
        page.goto('http://settings-test.invalid/product-settings')
        expect(page.locator('#editor')).to_be_enabled()
        yield page, active, status, db, snapshots, preview_keys
    page.close()
    assert errors == []


def choose(page, selector, value):
    # 通过真实搜索弹层操作；原 select 仅作为保存值契约。
    button=page.locator(selector+'-picker')
    button.click()
    page.locator('#picker-list').select_option(value)
    page.locator('.picker-apply').click()


def edit_library(page, alias):
    page.locator('#tab-library').click()
    page.locator(f'[data-library-alias="{alias}"]').click()


def reload_ui(page):
    page.locator('#tab-records').click()
    page.locator('#reload').click()
    if not page.locator('#discard-dialog').is_visible():
        page.locator('#tab-rules').click()


def save_with_preview(page):
    page.locator('#save').click()
    page.wait_for_function("document.querySelector('#impact-dialog').open || !document.querySelector('#editor').disabled")
    if page.locator('#impact-dialog').is_visible():
        page.locator('#impact-confirm').click()


def test_real_save_preview_persist_and_version(ui):
    page,active,status,flags=ui
    expect(page).to_have_title('商品挂载设置 · 视频控制台')
    expect(page.locator('#publisher-state')).to_contain_text('尚未接入')
    expect(page.locator('#english_world-0-picker')).to_be_disabled()
    expect(page.locator('#english_world-1-picker')).to_be_disabled()
    expect(page.locator('.english-product-rule')).to_contain_text('后续候选继承上方全局默认链')
    choose(page, '#default-product', 'finance')
    page.locator('#video').select_option('english:1')
    page.locator('#preview').click()
    expect(page.locator('#preview-result')).to_contain_text('英语世界短视频')
    expect(page.locator('#preview-result')).to_contain_text('当前未保存表单的预览')
    expect(page.locator('#preview-result li')).to_have_count(2)
    expect(page.locator('#preview-result li').nth(0)).to_contain_text('ID 10000006971274')
    expect(page.locator('#preview-result li').nth(1)).to_contain_text('ID 10000028955239')
    assert not status.exists()
    before=load_policy(active).digest
    save_with_preview(page)
    expect(page.locator('#feedback')).to_contain_text('配置已保存；发布器尚未接入')
    assert flags['writes']==1 and load_policy(active).digest!=before
    expect(page.locator('#adopted-version')).to_contain_text('尚无实际选品记录')
    page.reload();expect(page.locator('#english_world-0')).to_have_value('kuaijie_english')
    expect(page.locator('#default-product')).to_have_value('finance')
    assert not status.exists()


def test_english_product_is_locked_in_ui_and_invalid_preview_is_rejected(ui):
    page, active, _, _ = ui
    expect(page.locator('#english_world-0')).to_have_value('kuaijie_english')
    expect(page.locator('#english_world-0-picker')).to_be_disabled()
    expect(page.locator('#english_world-1-picker')).to_be_disabled()
    expect(page.locator('#default-product-picker')).to_be_enabled()
    expect(page.locator('#wallstreet-0-picker')).to_be_enabled()
    invalid = json.loads(active.read_text())
    invalid['profiles']['english_world']['candidates'] = ['finance']
    result = page.evaluate("async config => { const r = await fetch('/api/product-settings/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({config, context:{content_type:'ENGLISH_WORLD_SHORT'}})}); return {status:r.status, body:await r.json()}; }", invalid)
    assert result['status'] == 422
    assert '快捷英语' in result['body']['detail']
    active.write_text(json.dumps(invalid))
    invalid_snapshot = active.read_bytes()
    page.reload()
    expect(page.locator('#english_world-0')).to_have_value('finance')
    expect(page.locator('.english-product-rule')).to_have_attribute('data-valid', 'false')
    expect(page.locator('.english-product-rule')).to_contain_text('当前载入配置的英语首选不符合规定')
    expect(page.locator('#english_world-0-picker')).to_be_disabled()
    assert active.read_bytes() == invalid_snapshot


@pytest.mark.parametrize('views,likes,rate,state,reason', [
    (10000, 1000, '10.0%', '有效', 'ATTACH_THRESHOLD'),
    (10000, 0, '0%', '有效', 'SKIP_BELOW_THRESHOLD'),
    (10000, None, '未知', '缺失', 'SKIP_METRICS_UNKNOWN'),
    (0, 0, '未知', '无效', 'SKIP_METRICS_INVALID'),
])
def test_preview_reports_source_metrics_without_treating_zero_as_unknown(ui, views, likes, rate, state, reason):
    page, active, status, flags = ui
    original = active.read_bytes()
    flags['records'][0].update(view_count=views, like_count=likes, product_intent='AUTO')
    page.locator('#video').select_option('video:1')
    page.locator('#preview').click()
    simulation = page.locator('#preview-simulation')
    expect(simulation).to_contain_text(f'源播放数：{views}')
    expect(simulation).to_contain_text(f'源点赞数：{likes if likes is not None else "未知"}')
    expect(simulation).to_contain_text(f'源点赞率：{rate}')
    expect(simulation).to_contain_text(f'指标状态：{state}')
    expect(simulation).to_contain_text(reason)
    expect(simulation).to_contain_text('商品意图：自动规则')
    if reason != 'ATTACH_THRESHOLD':
        expect(simulation).to_contain_text('不执行商品选择器')
    assert active.read_bytes() == original
    assert not status.exists()


@pytest.mark.parametrize('name', ['first', 'later', 'none'])
def test_saved_config_simulation_stays_separate_from_actual_frozen_decision(frozen_ui, name):
    page, active, status, db, snapshots, keys = frozen_ui
    old = snapshots[name]
    choose(page, '#default-product', 'finance')
    save_with_preview(page)
    expect(page.locator('#feedback')).to_contain_text('配置已保存')
    new = load_policy(active)
    assert new.version != old['config_version']
    assert new.digest != old['config_digest']
    page.locator('#video').select_option(keys[name])
    page.locator('#preview').click()
    frozen = page.locator('#preview-frozen')
    simulation = page.locator('#preview-simulation')
    expect(frozen).to_contain_text('已冻结实际决定（重试沿用）')
    expect(frozen).to_contain_text('保存或预览新配置不会改变它')
    expect(frozen).to_contain_text(old['config_version'])
    expect(frozen).to_contain_text(old['config_digest'])
    expect(frozen).to_contain_text('源播放数：1000 · 源点赞数：0 · 源点赞率：0%')
    expect(simulation).to_contain_text('新配置模拟（不改变已冻结任务）')
    expect(simulation).to_contain_text(new.version)
    expect(simulation).to_contain_text(new.digest)
    expect(simulation).not_to_contain_text(old['config_digest'])
    if name == 'none':
        expect(frozen).to_contain_text('商品意图：手动不绑定 · 挂载决定：无需挂载')
        expect(frozen).to_contain_text('冻结决定无需商品，不执行商品选择器')
        expect(frozen.locator('li')).to_have_count(0)
        expect(simulation).to_contain_text('SKIP_MANUAL_NONE')
    else:
        expect(frozen).to_contain_text('业务日（北京时间）：2026-10-11')
        expect(frozen).to_contain_text(f'正式制作任务：pipeline:frozen-{name}:0')
        expect(frozen).to_contain_text('当日首条任务：pipeline:frozen-first:0')
        expect(frozen).to_contain_text('不代表平台账号已核实')
        expect(frozen).to_contain_text('ATTACH_ENGLISH_PREFERRED')
        expect(frozen.locator('li')).to_have_count(2)
        expect(frozen.locator('li').nth(0)).to_contain_text('ID 10000006971274')
        expect(frozen.locator('li').nth(1)).to_contain_text('ID 10001054866768')
        expect(simulation.locator('li')).to_have_count(2)
        expect(simulation.locator('li').nth(0)).to_contain_text('ID 10000006971274')
        expect(simulation.locator('li').nth(1)).to_contain_text('ID 10000028955239')
        if name == 'first':
            expect(frozen).to_contain_text('本任务是首条')
        else:
            expect(frozen).to_contain_text('本任务是后续任务')
    assert db.get_product_task_decision(old['task_id']) == old
    assert not status.exists()
    page.set_viewport_size({'width': 390, 'height': 900})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    evidence = Path(__file__).resolve().parents[2] / 'output/test-evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence / f'product-preview-frozen-{name}.png'), full_page=True)


def test_manual_preview_uses_explicit_product_above_automatic_metrics_rule(ui):
    page, active, status, flags = ui
    original = active.read_bytes()
    flags['records'][0].update(view_count=10000, like_count=0, product_intent='AUTO')
    page.locator('#video').select_option('video:1')
    choose(page, '#manual', 'news')
    page.locator('#preview').click()
    simulation = page.locator('#preview-simulation')
    expect(simulation).to_contain_text('商品意图：手动指定商品 · 挂载决定：要求挂载')
    expect(simulation).to_contain_text('ATTACH_MANUAL')
    expect(simulation).to_contain_text('人工意图优先')
    expect(simulation.locator('li')).to_have_count(1)
    expect(simulation.locator('li')).to_have_text('维特根斯坦说逻辑与语言 (英)维特根斯坦著 · ID 10000129752415')
    assert active.read_bytes() == original
    assert flags['records'][0]['product_intent'] == 'AUTO'
    assert not status.exists()


def test_manual_preview_override_does_not_change_frozen_none_intent(frozen_ui):
    page, active, status, db, snapshots, keys = frozen_ui
    original = active.read_bytes()
    page.locator('#video').select_option(keys['none'])
    choose(page, '#manual', 'finance')
    page.locator('#preview').click()
    expect(page.locator('#preview-frozen')).to_contain_text('商品意图：手动不绑定 · 挂载决定：无需挂载')
    expect(page.locator('#preview-frozen li')).to_have_count(0)
    expect(page.locator('#preview-simulation')).to_contain_text('商品意图：手动指定商品 · 挂载决定：要求挂载')
    expect(page.locator('#preview-simulation li')).to_have_count(1)
    expect(page.locator('#preview-simulation li')).to_contain_text('ID 10000028955239')
    assert db.get_product_task_decision(snapshots['none']['task_id']) == snapshots['none']
    assert active.read_bytes() == original
    assert not status.exists()


def test_impact_distinguishes_candidate_change_from_unchanged_frozen_tasks(frozen_ui):
    page, active, _, db, snapshots, _ = frozen_ui
    original = active.read_bytes()
    choose(page, '#default-product', 'finance')
    page.locator('#save').click()
    expect(page.locator('#impact-dialog')).to_be_visible()
    report = page.locator('#impact-result')
    expect(report).to_contain_text('配置候选链变化 3 条；预计实际选品变化 0 条')
    report_text = report.inner_text()
    frozen_note = '实际决定已冻结，继续沿用原快照'
    for name, reason in (('first', 'ENGLISH_WORLD_PREFERRED'),
                         ('later', 'ENGLISH_WORLD_PREFERRED'), ('none', 'DEFAULT')):
        start = report_text.index(f'{name} 冻结测试')
        end = report_text.index(frozen_note, start) + len(frozen_note)
        task_report = report_text[start:end]
        assert f'规则 {reason} → {reason}' in task_report
        assert frozen_note in task_report
    page.locator('#impact-cancel').click()
    assert active.read_bytes() == original
    for old in snapshots.values():
        assert db.get_product_task_decision(old['task_id']) == old


@pytest.mark.parametrize('likes,actual_count', [(1000, 1), (0, 0)])
def test_impact_counts_actual_change_only_when_source_metrics_require_attachment(ui, likes, actual_count):
    page, active, _, flags = ui
    original = active.read_bytes()
    flags['records'][0].update(view_count=10000, like_count=likes, product_intent='AUTO')
    choose(page, '#wallstreet-0', 'news')
    page.locator('#save').click()
    expect(page.locator('#impact-dialog')).to_be_visible()
    expect(page.locator('#impact-result')).to_contain_text(f'配置候选链变化 1 条；预计实际选品变化 {actual_count} 条')
    page.locator('#impact-cancel').click()
    assert active.read_bytes() == original


def test_conflict_failure_preserves_draft_and_reload_cancel(ui):
    page,active,status,flags=ui
    old=active.read_bytes();choose(page, '#ted-0', 'finance');flags['conflict']=True
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('其他窗口更新')
    expect(page.locator('#ted-0')).to_have_value('finance');assert active.read_bytes()==old
    reload_ui(page);expect(page.locator('#discard-dialog')).to_be_visible()
    expect(page.locator('#keep-editing')).to_be_focused()
    page.keyboard.press('Escape');expect(page.locator('#discard-dialog')).not_to_be_visible()
    reload_ui(page);page.locator('#discard').click()
    expect(page.locator('#ted-0')).to_have_value('default')
    flags['offline']=True;reload_ui(page);expect(page.locator('#feedback')).to_contain_text('读取失败')
    flags['offline']=False;reload_ui(page);expect(page.locator('#feedback')).to_contain_text('配置已载入')


def test_invalid_chain_does_not_save(ui):
    page,active,_,_=ui
    old=active.read_bytes();choose(page, '#default-product', 'finance')
    page.locator('summary').filter(has_text='识别条件').click();page.locator('#attempts').select_option('1')
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('默认回退不可达')
    assert active.read_bytes()==old
    page.locator('#timeout').fill('0');save_with_preview(page)
    expect(page.locator('#timeout')).to_have_attribute('aria-invalid','true');expect(page.locator('#timeout')).to_be_focused()


@pytest.mark.parametrize('width',[1280,390])
def test_keyboard_responsive_and_screenshot(ui,width):
    page,_,_,_=ui
    page.set_viewport_size({'width':width,'height':900})
    page.emulate_media(reduced_motion='reduce')
    control=page.locator('#wallstreet-0-picker');expect(control).to_be_enabled();control.focus();page.keyboard.press('Space');expect(page.locator('.product-picker-dialog')).to_be_visible();page.keyboard.press('Escape');expect(page.locator('.product-picker-dialog')).not_to_be_visible()
    expect(control).to_be_focused()
    assert ui[3]['writes']==0
    page.locator('#video').select_option('english:1');page.locator('#preview').click()
    expect(page.locator('#preview-result li')).to_have_count(2)
    expect(page.locator('#preview-result li').first).to_contain_text('ID 10000006971274')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.evaluate("Array.from(document.querySelectorAll('select,input')).every(x=>x.labels.length>0)")
    evidence=Path(__file__).resolve().parents[2]/'output/test-evidence';evidence.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(evidence/f'product-settings-{width}.png'),full_page=True)


def test_empty_list_and_draft_preview(ui):
    page,_,_,flags=ui
    flags['empty']=True;reload_ui(page);expect(page.locator('#videos-state')).to_contain_text('暂无待发布')
    page.locator('#sample-context summary').click();page.locator('#topic').select_option('AI');page.locator('#preview').click()
    expect(page.locator('#preview-result')).to_contain_text('AI 相关资讯')
    page.locator('#topic').select_option('');page.locator('#category').select_option('科技');page.locator('#preview').click()
    expect(page.locator('#preview-result h3')).to_have_text('其他')


def test_pending_save_blocks_duplicate_clicks(ui):
    page,active,_,flags=ui
    before=active.read_bytes();choose(page, '#ted-0', 'finance')
    flags['hold']=('PUT','/api/product-settings')
    save_with_preview(page);expect(page.locator('#save')).to_be_disabled()
    expect(page.locator('#feedback')).to_contain_text('正在保存')
    with pytest.raises(PlaywrightTimeoutError):
        page.locator('#save').click(timeout=200)
    assert flags['writes']==1 and active.read_bytes()==before
    flags['release']();expect(page.locator('#feedback')).to_contain_text('配置已保存；发布器尚未接入')


def test_old_preview_cannot_overwrite_new_context(ui):
    page,_,_,flags=ui
    flags['hold']=('POST','/api/product-settings/preview')
    page.locator('#preview').click();expect(page.locator('#preview-result')).to_contain_text('正在计算')
    page.locator('#video').select_option('english:1')
    flags['release']();expect(page.locator('#preview')).to_be_enabled()
    expect(page.locator('#preview-result')).to_have_text('上下文已修改，请重新预览。')


def test_all_product_dropdowns_use_catalog_and_new_selection_persists(ui):
    from tests.unit.test_wechat_product_catalog import install_catalog
    page, active, _, flags = ui
    saved=json.loads(active.read_text())
    rows=list(saved['products'].values())+[dict(product_id='70001',title='新增真实目录商品'),dict(product_id='70002',title='新增真实目录商品')]
    path=install_catalog(active,rows)
    catalog=json.loads(path.read_text());catalog['items'][-1]['stock']=0;path.write_text(json.dumps(catalog))
    original=active.read_bytes()
    reload_ui(page)
    expect(page.locator('#catalog-state')).to_contain_text('6 件商品')
    expect(page.locator('#catalog-state')).to_contain_text('全量完整性尚未确认')
    assert active.read_bytes()==original
    controls=['#default-product','#manual','#rule-0','#rule-1']
    controls += [f'#{group}-{index}' for group in saved['profiles'] if group != 'english_world' for index in (0,1)]
    for control in controls:
        expect(page.locator(control+' option[value="product_70001"]')).to_have_count(1)
        expect(page.locator(control+' option[value="product_70002"]')).to_have_count(1)
        expect(page.locator(control+' option[value="product_70002"]')).to_contain_text('采集时缺货')
    expect(page.locator('#english_world-0-picker')).to_be_disabled()
    expect(page.locator('#english_world-0')).to_have_value('kuaijie_english')
    choose(page, '#ted-0', 'product_70001')
    expect(page.locator('#ted-0-detail')).to_contain_text('ID 70001')
    expect(page.locator('#ted-0-detail')).to_contain_text('采集时库存未知')
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    page.reload();expect(page.locator('#english_world-0')).to_have_value('kuaijie_english')
    expect(page.locator('#ted-0')).to_have_value('product_70001')
    page.locator('#video').select_option('english:1');page.locator('#preview').click()
    expect(page.locator('#preview-result li').first).to_contain_text('ID 10000006971274')
    assert flags['writes']==1
    persisted=json.loads(active.read_text())
    assert persisted['profiles']['ted']['candidates']==['product_70001']
    assert persisted['profiles']['wallstreet']==saved['profiles']['wallstreet']
    path.write_text('{')
    reload_ui(page);expect(page.locator('#catalog-state')).to_contain_text('商品清单读取失败')
    expect(page.locator('#english_world-0')).to_have_value('kuaijie_english')


def test_catalog_file_preview_import_and_error_keeps_current(ui):
    from tests.unit.test_wechat_catalog_import import document
    page,active,_,flags=ui
    original=active.read_bytes()
    doc=document(list(json.loads(original)['products'].values())+[dict(product_id='8880001',title='新导入目录图书')])
    page.locator('#tab-library').click();page.locator('#catalog-open').click()
    page.locator('#catalog-file').set_input_files({'name':'catalog.json','mimeType':'application/json','buffer':json.dumps(doc).encode()})
    page.locator('#catalog-check').click()
    expect(page.locator('#catalog-import-feedback')).to_contain_text('文件完整性校验通过，尚未导入')
    expect(page.locator('#catalog-import-preview')).to_contain_text('首次登记清单账号')
    assert not active.with_name('wechat_product_catalog.json').exists()
    page.locator('#catalog-apply').click()
    expect(page.locator('#catalog-import-feedback')).to_contain_text('已导入 5 件商品')
    expect(page.locator('#catalog-state')).to_contain_text('导入完整性校验通过（2 页），非平台实时核验')
    for control in ('#default-product','#ted-1','#manual','#rule-0'):
        expect(page.locator(control+' option[value="product_8880001"]')).to_have_count(1)
    assert active.read_bytes()==original
    page.locator('[data-close="catalog-dialog"]').click();page.reload();expect(page.locator('#catalog-state')).to_contain_text('2 页')
    page.locator('#tab-library').click();page.locator('#catalog-open').click()
    old=active.with_name('wechat_product_catalog.json').read_bytes();doc['pages'].pop()
    page.locator('#catalog-file').set_input_files({'name':'broken.json','mimeType':'application/json','buffer':json.dumps(doc).encode()})
    page.locator('#catalog-check').click()
    expect(page.locator('#catalog-import-feedback')).to_contain_text('分页不完整')
    expect(page.locator('#catalog-apply')).to_be_disabled()
    assert active.with_name('wechat_product_catalog.json').read_bytes()==old
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_catalog_import_protects_unsaved_config_and_blocks_duplicate_submit(ui):
    from tests.unit.test_wechat_catalog_import import document
    page,active,_,flags=ui
    doc=document(list(json.loads(active.read_text())['products'].values()))
    choose(page, '#ted-0', 'finance')
    page.locator('#tab-library').click();page.locator('#catalog-open').click()
    page.locator('#catalog-file').set_input_files({'name':'catalog.json','mimeType':'application/json','buffer':json.dumps(doc).encode()})
    page.locator('#catalog-check').click()
    expect(page.locator('#catalog-import-feedback')).to_contain_text('有未保存修改')
    expect(page.locator('#ted-0')).to_have_value('finance')
    page.locator('[data-close="catalog-dialog"]').click();save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    page.locator('#tab-library').click();page.locator('#catalog-open').click();page.locator('#catalog-check').click();expect(page.locator('#catalog-apply')).to_be_enabled()
    flags['hold']=('POST','/api/product-settings/catalog/import')
    page.locator('#catalog-apply').click();expect(page.locator('#catalog-apply')).to_be_disabled()
    expect(page.locator('#save')).to_be_disabled()
    with pytest.raises(PlaywrightTimeoutError):
        page.locator('#catalog-apply').click(timeout=200)
    assert not active.with_name('wechat_product_catalog.json').exists()
    flags['release']();expect(page.locator('#catalog-import-feedback')).to_contain_text('已导入 4 件商品')
    expect(page.locator('#ted-0')).to_have_value('finance')


def test_impact_cancel_and_history_restore_as_draft(ui):
    page,active,status,flags=ui
    old=load_policy(active);choose(page, '#default-product', 'finance')
    page.locator('#save').click();expect(page.locator('#impact-dialog')).to_be_visible()
    expect(page.locator('#impact-result')).to_contain_text('变化 1 条')
    expect(page.locator('#impact-result')).to_contain_text('预计实际选品变化 1 条')
    expect(page.locator('#impact-result')).to_contain_text('预计影响下一次尚未冻结的选品')
    assert active.read_bytes() and load_policy(active).digest==old.digest
    page.locator('#impact-cancel').click();assert flags['writes']==0
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    expect(page.locator('#revision option')).to_have_count(2)
    page.locator('#history-open').click();page.locator('#revision').select_option(old.digest);page.locator('#restore-revision').click()
    expect(page.locator('#feedback')).to_contain_text('恢复草稿')
    expect(page.locator('#english_world-0')).to_have_value('kuaijie_english')
    expect(page.locator('#default-product')).to_have_value('default')
    assert load_policy(active).digest!=old.digest
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert load_policy(active).version!=old.version
    assert load_policy(active).decide(content_type='ENGLISH_WORLD_SHORT').candidates==old.decide(content_type='ENGLISH_WORLD_SHORT').candidates


def test_library_pending_then_verified_and_selected(ui):
    page,active,_,flags=ui
    page.locator('#tab-library').click();page.locator('#library-new').click()
    page.locator('#lib-title').fill('新书完整名称')
    page.locator('#lib-shop').fill('快捷英语教辅图书')
    page.locator('#lib-merchant_appid').fill('wx490e65efa3751b8c')
    page.locator('#library-apply').click()
    expect(page.locator('#library-feedback')).to_contain_text('已应用到草稿')
    alias=page.locator('#library-choice').input_value()
    expect(page.locator(f'#default-product option[value="{alias}"]')).to_have_count(0)
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert json.loads(active.read_text())['library'][alias]['identity_status']=='UNVERIFIED'
    edit_library(page, alias)
    page.locator('#lib-product_id').fill('88888888')
    page.locator('#lib-account_id').fill('verified-publisher')
    page.locator('#lib-verified_source').fill('人工核对后台资料')
    page.locator('#lib-verified_at').fill('2026-01-01T00:00:00+08:00')
    page.locator('#lib-identity_status').select_option('VERIFIED')
    page.locator('#library-apply').click()
    page.locator('#tab-rules').click();choose(page, '#wallstreet-0', alias)
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert load_policy(active).decide(content_type='ENGLISH_WORLD_SHORT').candidates[0].product_id=='10000006971274'
    assert load_policy(active).decide(source_channel_id='UCTK_cv-y88CScoudcXnS1Ew').candidates[0].product_id=='88888888'
    page.reload();expect(page.locator('#wallstreet-0')).to_have_value(alias)
    page.locator('#tab-library').click();page.locator('#library-search').fill('快捷英语')
    options = page.locator('#library-choice option')
    expect(options).to_have_count(3)  # 空白占位 + 两个不同商品身份
    expect(options.first).to_have_text('选择商品或新增资料')
    expect(options.filter(has_text='10000006971274')).to_have_count(1)
    expect(options.filter(has_text='88888888')).to_have_count(1)


def test_refresh_wait_parameters_and_disabled_reference(ui):
    page,active,_,_=ui
    page.locator('#tab-library').click()
    expect(page.locator('#catalog-refresh')).not_to_be_visible()
    expect(page.locator('.catalog-summary .badge')).to_have_text('平台实时同步尚未接入')
    expect(page.locator('#wait-state')).to_contain_text('调度接入')
    edit_library(page, 'default');page.locator('#library-toggle').click()
    page.locator('#save').click();expect(page.locator('#feedback')).to_contain_text('停用')
    edit_library(page, 'default');page.locator('#library-toggle').click()
    page.locator('#tab-rules').click();page.locator('summary').filter(has_text='等待与恢复检查').click()
    page.locator('#wait-base_seconds').fill('600')
    save_with_preview(page);expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert json.loads(active.read_text())['wait_policy']['base_seconds']==600


def test_search_picker_keyboard_cancel_and_main_viewport(ui):
    page,_,_,flags=ui
    # 日常五类配置在首屏，不再被商品库与历史挡住。
    assert page.locator('#other-0-picker').bounding_box()['y'] < 900
    old=page.locator('#wallstreet-0').input_value()
    button=page.locator('#wallstreet-0-picker');button.click()
    search=page.locator('#picker-search');search.fill('没有这件商品')
    expect(page.locator('.picker-count')).to_have_text('没有匹配的商品')
    expect(page.locator('.picker-apply')).to_be_disabled()
    page.locator('.picker-clear').click();expect(search).to_be_focused()
    expect(page.locator('#picker-list option')).to_have_count(5)
    page.keyboard.press('Escape');expect(page.locator('.product-picker-dialog')).not_to_be_visible()
    expect(button).to_be_focused();expect(page.locator('#wallstreet-0')).to_have_value(old)
    expect(page.locator('#save')).to_be_disabled()
    button.click();search.fill('维特根斯坦');expect(page.locator('#picker-list option')).to_have_count(1)
    page.keyboard.press('ArrowDown');page.keyboard.press('Enter')
    expect(page.locator('#wallstreet-0')).to_have_value('news')
    expect(button).to_be_focused();assert flags['writes']==0


def test_library_navigation_search_and_editor_discard_do_not_lose_rules(ui):
    page,active,_,flags=ui
    choose(page,'#ted-0','finance')
    page.locator('#tab-library').click();page.locator('#library-search').fill('不存在的商品')
    expect(page.locator('#library-results')).to_contain_text('没有匹配的商品')
    expect(page.locator('#dirty-state')).to_have_text('1 处修改待保存')
    page.locator('#library-clear').click();expect(page.locator('#library-search')).to_be_focused()
    page.locator('#library-new').click();page.locator('#lib-title').fill('尚未应用的资料')
    page.locator('[data-close="library-editor"]').first.click()
    expect(page.locator('#discard-dialog')).to_be_visible()
    page.locator('#discard').click();expect(page.locator('#library-editor')).not_to_be_visible()
    page.locator('#tab-rules').click();expect(page.locator('#ted-0')).to_have_value('finance')
    expect(page.locator('#dirty-state')).to_have_text('1 处修改待保存')
    assert flags['writes']==0


def test_library_pagination_filters_and_url_restore(ui):
    from tests.unit.test_wechat_product_catalog import install_catalog
    page,active,_,flags=ui
    products=list(json.loads(active.read_text())['products'].values())
    rows=products+[dict(product_id=str(72000+i),title=f'目录商品 {i:02d}') for i in range(30)]
    install_catalog(active,rows);reload_ui(page)
    page.locator('#tab-library').click()
    expect(page.locator('.library-table tbody tr')).to_have_count(25)
    page.locator('#library-next').click();expect(page.locator('.library-table tbody tr')).to_have_count(9)
    page.locator('#library-search').fill('目录商品 29')
    expect(page.locator('.library-table tbody tr')).to_have_count(1)
    page.reload();expect(page.locator('#view-library')).to_be_visible()
    expect(page.locator('#library-search')).to_have_value('目录商品 29')
    expect(page.locator('.library-table tbody tr')).to_have_count(1)
    expect(page.locator('#save')).to_be_disabled();assert flags['writes']==0


@pytest.mark.parametrize('theme',['dark','light','contrast'])
def test_theme_preferences_and_mobile_picker_geometry(ui,theme):
    page,_,_,_=ui
    page.evaluate('(theme)=>localStorage.setItem("vp-display-preferences",JSON.stringify({theme,size:"large"}))',theme)
    page.reload();expect(page.locator('#editor')).to_be_enabled()
    page.set_viewport_size({'width':390,'height':844})
    page.locator('#default-product-picker').click()
    dialog=page.locator('.product-picker-dialog');expect(dialog).to_be_visible()
    box=dialog.bounding_box();assert box['x']>=0 and box['x']+box['width']<=390
    assert box['y']>=0 and box['y']+box['height']<=844
    page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
    page.locator('#tab-library').click();assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('html').get_attribute('data-theme')==theme

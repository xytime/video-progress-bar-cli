"""后台恢复的真实 Chromium / FastAPI / SQLite 闭环，绝不启动上传器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 分页选择、额度重置、幂等批次、键盘、主题及手机验收。 |
"""
import json
import time
from pathlib import Path
from urllib.parse import urlparse
import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.publishing_recovery import PublishingRecoveryService
from web.publishing_recovery import create_publishing_recovery_router
from web.wechat_cooldown_settings import create_wechat_cooldown_settings_router


@pytest.fixture
def ui(chromium,tmp_path,monkeypatch):
    out=tmp_path/'output';out.mkdir()
    monkeypatch.setattr(type(settings),'default_output_dir',property(lambda _:out))
    monkeypatch.setattr(settings,'wechat_scheduler_policy_path',out/'policy.json')
    monkeypatch.setattr(settings,'wechat_scheduler_priority_video','')
    monkeypatch.setattr(settings,'wechat_publishing_paused',False)
    monkeypatch.setattr(settings,'wechat_account_scheduler_enabled',True)
    db=PipelineDB(str(out/'pipeline.db'))
    for i in range(31):
        key=f'browser{i:04}'
        db.add_video(key,'宏观科技访谈 '+str(i),'test-channel',score=60)
        db.update_video_status(key,'FAILED',error_msg='网络中断，保留已有缓存')
    with db.get_connection() as c:c.execute("UPDATE processed_videos SET failed_at=NULL WHERE youtube_id='browser0030'")
    db.update_video_status('browser0029','UNCERTAIN')
    service=PublishingRecoveryService(db,tmp_path)
    row=service.guard.snapshot();now=time.time()
    row['schedule']={'sessions':[dict(at=now-10000+i,purpose='发布',task=f'history{i}') for i in range(50)],'queue':[],'publications':{}}
    service.guard.path.write_text(json.dumps(row))
    app=FastAPI();app.include_router(create_wechat_cooldown_settings_router(active=out/'policy.json'))
    app.include_router(create_publishing_recovery_router(db,tmp_path))
    root=Path(__file__).resolve().parents[2]
    app.mount('/static',StaticFiles(directory=root/'src/web/static'))
    client=TestClient(app);page=chromium.new_page(viewport=dict(width=1440,height=1000))
    errors=[];flags=dict(writes=[],fail_status=False,timeout_once=False)
    page.on('pageerror',lambda error:errors.append(str(error)))
    def handler(route):
        r=route.request;u=urlparse(r.url)
        if flags['fail_status'] and u.path=='/api/publishing-recovery/status':
            route.fulfill(status=503,json={'detail':'状态读取失败'});return
        response=client.request(r.method,u.path+('?' +u.query if u.query else ''),content=r.post_data,headers={'Content-Type':'application/json'})
        if r.method=='POST' and u.path.endswith('/operations'):
            flags['writes'].append(r.post_data_json)
            if flags['timeout_once']:
                flags['timeout_once']=False;route.abort('failed');return
        route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',handler);page.goto('http://publishing-test.invalid/wechat-cooldown-settings')
    expect(page.locator('#pr-metrics')).to_contain_text('50 / 20')
    yield page,service,flags
    page.close();client.close();assert errors==[]


def test_quota_reset_confirmation_escape_history_preserved(ui):
    page,service,_=ui
    expect(page.locator('#pr-blockers')).to_contain_text('访问额度已用完')
    b=page.get_by_role('button',name='重置本地额度',exact=True);b.click()
    expect(page.locator('#pr-cancel')).to_be_focused();page.keyboard.press('Escape');expect(b).to_be_focused()
    assert service.guard.evaluate(account_only=True)['sessions_24h_count']==50
    b.click();page.locator('#pr-confirm').click()
    expect(page.locator('#pr-metrics')).to_contain_text('0 / 20')
    expect(page.locator('#pr-metrics')).to_contain_text('50 次')
    expect(page.locator('#pr-history')).to_contain_text('50 → 0')
    assert len(service.guard.snapshot()['schedule']['sessions'])==50


def test_page_selection_six_fixed_targets_and_cancel(ui):
    page,service,flags=ui;page.locator('#pr-preview').click()
    expect(page.locator('#pr-summary')).to_contain_text('共 31 项')
    expect(page.locator('#pr-rows input')).to_have_count(20)
    boxes=page.locator('#pr-rows input:enabled')
    for i in range(6):boxes.nth(i).check()
    expect(page.locator('#pr-selected')).to_have_text('已选 6 项')
    page.locator('#pr-next').click();expect(page.locator('#pr-rows input')).to_have_count(11)
    page.locator('#pr-prev').click();expect(page.locator('#pr-rows input:checked')).to_have_count(6)
    page.reload();expect(page.locator('#pr-selected')).to_have_text('已选 6 项')
    page.get_by_role('button',name='重试所选任务',exact=True).click()
    expect(page.locator('#pr-confirm-body')).to_contain_text('选中的 6 项')
    page.locator('#pr-confirm').click();expect(page.locator('#pr-history')).to_contain_text('已入恢复队列')
    assert len(flags['writes'])==1 and len(flags['writes'][0]['selected_ids'])==6
    page.get_by_role('button',name='取消尚未启动项').click();expect(page.locator('#pr-history')).to_contain_text('已取消')
    page.reload();expect(page.locator('#pr-history')).to_contain_text('已取消')


def test_all_matching_excludes_protected_estimated_and_timeout_reconcile(ui):
    page,service,flags=ui;page.locator('#pr-preview').click();page.locator('#pr-select-all').click()
    expect(page.locator('#pr-selected')).to_have_text('已选 29 项')
    flags['timeout_once']=True
    page.get_by_role('button',name='重试所选任务',exact=True).click();page.locator('#pr-confirm').click()
    expect(page.locator('#pr-confirm-feedback')).to_contain_text('结果尚未确认')
    page.locator('#pr-cancel').click();page.locator('#pr-check').click()
    expect(page.locator('#pr-feedback')).to_contain_text('操作已记录')
    assert len(service.db.list_publishing_recovery_operations()['items'])==1
    assert len(flags['writes'])==1


def test_mobile_themes_stale_state_and_full_selection(ui,tmp_path):
    page,_,flags=ui;page.set_viewport_size(dict(width=390,height=844))
    for theme in ['light','dark','contrast']:
        page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
        page.locator('#pr-preview').click();page.locator('#pr-page-select').check()
        expect(page.locator('#pr-selected')).to_have_text(f'已选 {page.locator("#pr-rows input:checked").count()} 项')
        assert page.locator('#pr-rows tr').filter(has_text='估算').locator('input:checked').count()==0
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('#pr-rows tr').first.bounding_box()['height'] < 300
        evidence=Path(__file__).resolve().parents[2]/'output/browser-qa';evidence.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(evidence/f'publishing-recovery-mobile-{theme}.png'),full_page=True)
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(evidence/f'publishing-recovery-viewport-{theme}.png'))
    flags['fail_status']=True;page.locator('#pr-refresh').click()
    expect(page.locator('#pr-status')).to_contain_text('禁止执行')
    expect(page.get_by_role('button',name='重试所选任务',exact=True)).to_be_disabled()
    expect(page.locator('#pr-selected')).to_have_text(f'已选 {page.locator("#pr-rows input:checked").count()} 项')
    flags['fail_status']=False;page.locator('#pr-refresh').click()
    expect(page.get_by_role('button',name='重试所选任务',exact=True)).to_be_enabled()

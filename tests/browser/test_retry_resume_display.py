"""真实 Chromium 验证技术失败、历史批准、分集及恢复阶段；禁止外部写入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 三主题/手机、主行分集、真实阶段与历史批准的隔离验收。 |
"""
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from video_processing.db.database import PipelineDB
from web import app as web_app


@pytest.fixture
def display(chromium, tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path/'review.db'))
    db.add_video('approved-tech','Approved video','channel',score=90)
    parent=db.get_video_by_youtube_id('approved-tech')
    db.add_video('approved-tech','Approved slice','channel',score=90,slice_index=1,parent_id=parent['id'])
    for index in (0,1):
        db.update_video_censor_status('approved-tech','🔴 政治安全违禁',95,slice_index=index)
        db.set_bypass_censorship('approved-tech',True,slice_index=index)
        db.record_censorship_incident('approved-tech',slice_index=index,stage='manual_review',level='P0',
            action='MANUAL_BYPASS',tag='🔴 政治安全违禁',score=None,matched='rule',channel='operator',decision='MANUAL_P0_APPROVED')
        db.update_video_status('approved-tech','FAILED',
            error_msg='ValueError: 第 169 帧原字幕位置或文字不确定，停止出片：O',slice_index=index)
    db.add_video('current-p0','Current blocked','channel',score=90)
    db.update_video_status('current-p0','FAILED',error_msg='Censorship P0 Reject: blocked')
    monkeypatch.setattr(web_app,'db',db)
    monkeypatch.setattr(web_app,'_OUT_DIR',tmp_path)
    client=TestClient(web_app.app)
    page=chromium.new_page(viewport=dict(width=1280,height=900))
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    def handler(route):
        req,url=route.request,urlsplit(route.request.url)
        assert req.method=='GET', '验收禁止写入'
        if url.hostname!='127.0.0.1':
            route.fulfill(status=404,body='离线验收')
            return
        response=client.get(url.path+('?' + url.query if url.query else ''))
        route.fulfill(status=response.status_code,body=response.content,headers=dict(response.headers))
    page.route('**/*',handler)
    yield page,db,tmp_path
    page.close()
    client.close()
    assert not errors


@pytest.mark.parametrize('theme',['dark','light','contrast'])
def test_approved_technical_failure_and_slice_never_offer_reapproval(display,theme):
    page,db,folder=display
    page.add_init_script('localStorage.setItem("vp-display-preferences",'+repr(json.dumps(dict(theme=theme,size='standard')))+')')
    evidence=Path('output/test-evidence/retry-resume')
    evidence.mkdir(parents=True,exist_ok=True)
    for width in (1280,390):
        page.set_viewport_size(dict(width=width,height=900))
        page.goto('http://127.0.0.1:9100/?tab=error&created_window=all')
        parent=page.locator('#row-approved-tech')
        expect(parent).to_be_visible()
        page.evaluate('clearTimeout(refreshTimeoutId); scheduleNextRefresh=()=>{}')
        expect(parent.locator('.btn-bypass')).to_have_count(0)
        expect(parent.locator('.censor-badge')).to_contain_text('P0 已人工放行')
        expect(parent.locator('.censor-badge')).to_contain_text('历史命中')
        expect(parent).to_contain_text('原字幕定位失败')
        expect(page.locator('#row-current-p0 .btn-bypass')).to_have_count(1)
        page.locator('#btn-toggle-approved-tech').click()
        child=page.locator('#row-approved-tech_s1')
        expect(child).to_be_visible()
        expect(child.locator('.btn-bypass')).to_have_count(0)
        expect(child).to_contain_text('P0 已人工放行')
        expect(child).to_contain_text('原字幕定位失败')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(evidence/f'approved-{theme}-{width}.png'),full_page=True)


def test_active_row_shows_reused_steps_and_actual_location_stage(display):
    page,db,folder=display
    db.update_video_status('approved-tech','TRANSCRIBING')
    (folder/'approved-tech_caption_progress.json').write_text(json.dumps(dict(
        updated_at=time.time(),stage='SOURCE_CAPTION_LOCATING',reused_steps=['copy','asr','translation'])))
    page.goto('http://127.0.0.1:9100/?view=production&tab=active&created_window=all')
    parent=page.locator('#row-approved-tech')
    expect(parent).to_be_visible()
    expect(parent).to_contain_text('复用已有文案')
    expect(parent).to_contain_text('复用转录')
    expect(parent).to_contain_text('复用翻译')
    expect(parent).to_contain_text('继续原字幕定位')
    expect(parent.locator('.badge').filter(has_text='转录中')).to_have_count(0)

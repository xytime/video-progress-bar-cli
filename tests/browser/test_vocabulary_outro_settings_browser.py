"""生词片尾设置真实 Chromium 交互，HTTP 仅转送隔离 FastAPI。"""
from urllib.parse import urlparse
from pathlib import Path

import pytest
from playwright.sync_api import expect
from tests.browser_fixtures import chromium
from tests.unit.test_vocabulary_outro_settings import api_setup, config
from video_processing.utils.vocabulary_outro_policy import load_policy


@pytest.fixture
def ui(chromium,api_setup):
    client,active,output,_=api_setup
    page=chromium.new_page(viewport=dict(width=1440,height=1000))
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    flags={'save_error':None,'records_error':False}
    def route(route):
        request=route.request;path=urlparse(request.url).path
        if request.method=='PUT' and flags['save_error']:
            route.fulfill(status=flags['save_error'],json=dict(detail='保存冲突' if flags['save_error']==409 else '服务暂不可用'));return
        if flags['records_error'] and path.endswith('/records'):
            route.fulfill(status=503,json=dict(detail='执行记录读取失败'));return
        if flags.get('hold_preview') and path.endswith('/preview'):
            def release():
                response=client.post(path,content=request.post_data,headers={'Content-Type':'application/json'})
                route.fulfill(status=response.status_code,body=response.content,content_type='application/json')
            flags['release']=release;return
        response=client.request(request.method,path,content=request.post_data,headers={'Content-Type':'application/json'})
        route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',route)
    page.goto('http://outro-test.invalid/vocabulary-outro-settings')
    expect(page.locator('#editor')).to_be_enabled()
    expect(page.locator('#videos-state')).to_contain_text('已载入')
    yield page,active,flags
    page.close();assert errors==[]


def test_type_preview_save_persists_across_reload(ui):
    page,active,_=ui
    page.locator('#group-wallstreet').uncheck()
    page.locator('#video').select_option('video:1')
    page.locator('#preview').click()
    expect(page.locator('#preview-result')).to_contain_text('华尔街事实炸弹 · 不追加')
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('配置已保存')
    assert load_policy(active)['profiles']['wallstreet']['enabled'] is False
    assert load_policy(active)['profiles']['ted']['enabled'] is True
    page.reload();expect(page.locator('#group-wallstreet')).not_to_be_checked()
    expect(page.locator('#save')).to_be_disabled()
    page.locator('#enabled').uncheck()
    page.locator('#video').select_option('')
    page.locator('#content-type').select_option('ENGLISH_WORLD_SHORT')
    page.locator('#preview').click()
    expect(page.locator('#preview-result')).to_contain_text('英语世界短视频 · 不追加')


def test_save_failure_conflict_and_readonly_retry_preserve_draft(ui):
    page,active,flags=ui
    page.locator('#enabled').uncheck()
    flags['save_error']=503
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('草稿已保留')
    expect(page.locator('#enabled')).not_to_be_checked()
    assert load_policy(active)['enabled'] is True
    flags['save_error']=409
    page.locator('#save').click()
    expect(page.locator('#feedback')).to_contain_text('保存冲突')
    expect(page.locator('#save')).to_be_disabled()
    flags['records_error']=True;page.locator('#reload-records').click()
    expect(page.locator('#records-state')).to_contain_text('读取失败')
    flags['records_error']=False;page.locator('#reload-records').click()
    expect(page.locator('#records-state')).to_contain_text('尚无')
    expect(page.locator('#feedback')).to_contain_text('保存冲突')
    expect(page.locator('#enabled')).not_to_be_checked()
    page.locator('#reload').click()
    expect(page.locator('#discard-dialog')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('#enabled')).not_to_be_checked()
    page.locator('#reload').click();page.locator('#discard').click()
    expect(page.locator('#enabled')).to_be_checked()


def test_pending_preview_cannot_overwrite_changed_form(ui):
    page,_,flags=ui
    flags['hold_preview']=True
    page.locator('#preview').click()
    expect(page.locator('#preview-result')).to_contain_text('正在预览')
    page.locator('#enabled').uncheck()
    flags['release']()
    expect(page.locator('#preview-result')).to_contain_text('已变化')


@pytest.mark.parametrize('theme',['light','dark','contrast'])
def test_theme_keyboard_mobile_and_screenshots(ui,theme,tmp_path):
    page,_,_=ui
    evidence=Path(__file__).resolve().parents[2]/'output/test-evidence/vocabulary-outro-settings'
    evidence.mkdir(parents=True,exist_ok=True)
    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
    page.locator('#enabled').focus();page.keyboard.press('Space')
    expect(page.locator('#enabled')).not_to_be_checked()
    page.locator('#reload').click()
    expect(page.locator('#keep-editing')).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.locator('#reload')).to_be_focused()
    page.screenshot(path=str(evidence/f'outro-{theme}-desktop.png'),full_page=True)
    page.set_viewport_size(dict(width=390,height=844))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(evidence/f'outro-{theme}-mobile.png'),full_page=True)

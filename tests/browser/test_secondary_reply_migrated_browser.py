"""迁移后策略页的真实 Chromium 保存、回读、并发冲突及草稿保护。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| reply-coverage-v2 | 2026-10-25 | Codex | 浏览器夹具接入现有额度联动路由，保留真实跨页保存与边界校验。 |
| reply-recovery-v1 | 2026-10-25 | Codex | 浏览器请求经过真实 Dashboard 中间件与本机会话，全部状态隔离。 |
"""
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from tests.unit.test_secondary_reply_recovery import migrated, configured, active
from tests.unit.test_runtime_configuration import ORIGIN, save
from video_processing.utils import runtime_configuration as runtime
from web.secondary_reply_settings import create_secondary_reply_settings_router
from web.runtime_configuration import create_runtime_configuration_router


@pytest.fixture
def ui(chromium, migrated, monkeypatch):
    _, db, path = migrated
    from video_processing.utils import reply_linked_policy
    monkeypatch.setattr(reply_linked_policy, 'verified_cadence', lambda: 72)
    from web.app import reject_untrusted_browser_origins
    app = FastAPI()
    app.middleware('http')(reject_untrusted_browser_origins)
    app.include_router(create_secondary_reply_settings_router(active=path, access_db=db, history_lookup=lambda limit: []))
    app.include_router(create_runtime_configuration_router(db, port=9100))
    root = Path(__file__).resolve().parents[2]
    app.mount('/static', StaticFiles(directory=root/'src/web/static'))
    client = TestClient(app, base_url=ORIGIN, client=('127.0.0.1', 50000))
    page = chromium.new_page(viewport=dict(width=1440, height=1000))
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route_handler(route):
        request = route.request
        parsed = urlparse(request.url)
        response = client.request(request.method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                                  content=request.post_data, headers=request.headers)
        route.fulfill(status=response.status_code, body=response.content, headers=dict(response.headers))
    page.route('**/*', route_handler)
    page.goto(ORIGIN + '/secondary-reply-settings')
    expect(page.locator('#editor')).to_be_enabled()
    yield page, path
    page.close()
    client.close()
    assert errors == []


def save_form(page):
    expect(page.locator('#save')).to_be_enabled()
    page.locator('#save').click()
    if page.locator('#reply-linkage-capacity').get_attribute('data-state') == 'warning':
        page.get_by_role('button', name='仍保存此配置').click()


def test_effective_quota_save_reload_and_cross_page_conflict(ui):
    page, _ = ui
    page.locator('#edit-policy').click()
    expect(page.locator('#hourly-quota')).to_have_value('50')
    expect(page.locator('#max-per-video')).to_have_value('20')
    expect(page.locator('#min-interval-seconds')).to_have_value('60')
    expect(page.locator('#quota-source')).to_contain_text('首评单独计额')
    page.locator('#hourly-quota').fill('49')
    save_form(page)
    expect(page.locator('#feedback')).to_contain_text('策略已保存')
    assert runtime.snapshot(fresh=True).domains()['wechat_operations']['operations']['reply']['rolling_1h_limit'] == 49
    page.reload()
    expect(page.locator('#hourly-quota')).to_have_value('49')
    page.locator('#edit-policy').click()
    page.locator('#hourly-quota').fill('48')
    current = runtime.snapshot(fresh=True)
    data = current.domains()
    data['observability']['wait_notice_cooldown_seconds'] = 7200
    save(data, current.revision, 'browser_other_page_000000001')
    save_form(page)
    expect(page.locator('#feedback')).to_contain_text('配置版本已变化')
    expect(page.locator('#hourly-quota')).to_have_value('48')
    expect(page.locator('#save')).to_be_disabled()
    evidence = Path(__file__).resolve().parents[2]/'output/test-evidence/secondary-reply-recovery'
    evidence.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence/'preserved-conflict.png'), full_page=True)


def test_bound_rejection_is_not_misreported_as_concurrent_edit(ui):
    page, _ = ui
    page.locator('#edit-policy').click()
    page.locator('#window-start').fill('00:00')
    page.locator('#window-end').fill('24:00')
    save_form(page)
    expect(page.locator('#feedback')).to_contain_text('需要专门批准')
    expect(page.locator('#feedback')).not_to_contain_text('保存冲突')
    expect(page.locator('#window-start')).to_have_value('00:00')
    expect(page.locator('#save')).to_be_enabled()

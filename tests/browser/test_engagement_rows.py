"""真实 Chromium 检查高互动状态、操作、防重和移动端；仅使用隔离数据。"""
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from tests.unit.test_engagement_rows import seed
from video_processing.db.database import PipelineDB
from web import app as web_app


@pytest.fixture
def engagement_page(chromium, tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "engagement-ui.db"))
    for yid, status, score, error in [
        ("low", "PENDING", 26, None), ("queued", "PENDING", 90, None),
        ("failed", "FAILED", 90, "下载失败：网络超时"),
        ("policy", "FAILED", 90, "Channel Policy Reject: 不符合频道选题标准"),
        ("submitted", "SUBMITTED_BOUND", 90, None), ("active", "TRANSCRIBING", 90, None),
    ]:
        seed(db, yid, status, score, error=error)
    dispatch = Mock()
    monkeypatch.setattr(web_app, "db", db)
    monkeypatch.setattr(web_app, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(type(web_app.settings), "default_output_dir", property(lambda _: tmp_path))
    monkeypatch.setattr(web_app, "_trigger_video_async", dispatch)
    client = TestClient(web_app.app, base_url="http://localhost:9100", client=("127.0.0.1", 50000))
    page = chromium.new_page(viewport={"width": 1440, "height": 1000})
    state = {"errors": [], "writes": [], "fail_reads": False}
    page.on("pageerror", lambda error: state["errors"].append(str(error)))

    def route_handler(route):
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != "localhost":
            route.fulfill(status=404, body="isolated"); return
        if req.method != "GET":
            state["writes"].append(url.path)
        if state["fail_reads"] and url.path == "/api/videos":
            route.fulfill(status=503, json={"detail": "测试读取失败"}); return
        response = client.request(req.method, url.path + ("?" + url.query if url.query else ""),
                                  content=req.post_data, headers={"Content-Type": req.headers.get("content-type", "")})
        route.fulfill(status=response.status_code, body=response.content, headers=dict(response.headers))

    page.route("**/*", route_handler)
    page.goto("http://localhost:9100/?view=topics&tab=high_likes&created_window=all&sort=score_desc")
    expect(page.locator(".engagement-state")).to_have_count(6)
    page.evaluate("clearTimeout(refreshTimeoutId); scheduleNextRefresh=()=>{}")
    yield page, db, dispatch, state
    page.close(); client.close()
    assert not state["errors"]


def capture(page, name):
    folder = Path(__file__).resolve().parents[2] / "output/test-evidence/engagement-rows"
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / (name + ".png")), full_page=True)
    if name == "mobile":
        page.locator("#row-failed").screenshot(path=str(folder / "mobile-failed-card.png"))


def test_states_details_and_mobile(engagement_page):
    page, db, dispatch, state = engagement_page
    body = page.locator("#activity-body")
    for text in ("未达入队分数", "处理失败", "规则拦截", "已提交，待确认发布", "字幕处理中"):
        expect(body).to_contain_text(text)
    expect(page.locator('[data-yid="submitted"][data-engagement-action="process"]')).to_have_count(0)
    expect(page.locator('[data-yid="active"][data-engagement-action="retry"]')).to_have_count(0)
    expect(body).not_to_contain_text("已处理")
    expect(body).not_to_contain_text("未命中敏感词")
    expect(page.locator("#row-submitted")).not_to_contain_text("已发布")
    expect(page.locator("#row-policy")).not_to_contain_text("达标入队")
    capture(page, "desktop")
    details = page.locator('[data-yid="failed"][data-engagement-action="details"]')
    details.click()
    expect(page.get_by_role("dialog", name="视频处理详情")).to_contain_text("网络超时")
    page.keyboard.press("Escape")
    expect(details).to_be_focused()
    page.locator('[data-yid="policy"][data-engagement-action="bypass-censor"]').click()
    expect(page.locator("#bypass-modal")).to_be_visible()
    expect(page.locator("#bypass-evidence")).to_contain_text("没有原审计记录")
    page.locator('#bypass-modal [onclick="closeBypassModal()"]').click()
    expect(page.locator("#bypass-modal")).to_be_hidden()
    for theme in ("light", "dark", "contrast"):
        page.evaluate("(theme)=>document.documentElement.dataset.theme=theme", theme)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(page.locator(".engagement-label").first).to_be_visible()
        assert page.locator(".engagement-action").first.bounding_box()["height"] >= 44
    capture(page, "mobile")
    dispatch.assert_not_called()
    assert state["writes"] == []


def test_confirm_cancel_and_single_dispatch(engagement_page):
    page, db, dispatch, state = engagement_page
    button = page.locator('[data-yid="low"][data-engagement-action="promote"]')
    page.once("dialog", lambda dialog: dialog.dismiss())
    button.click()
    assert not state["writes"]
    page.once("dialog", lambda dialog: dialog.accept())
    button.click()
    expect(page.locator('[data-yid="low"][data-engagement-action="promote"]')).to_have_count(0)
    dispatch.assert_called_once()
    assert state["writes"] == ["/api/videos/low/promote"]


def test_stale_rejected_filter_restore_and_read_failure(engagement_page):
    page, db, dispatch, state = engagement_page
    db.update_video_status("queued", "SUBMITTED_BOUND")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('[data-yid="queued"][data-engagement-action="process"]').click()
    expect(page.locator('[data-yid="queued"][data-engagement-action="process"]')).to_have_count(0)
    dispatch.assert_not_called()
    page.locator("#video-filter-status").select_option("ENG_POLICY")
    expect(page.locator(".engagement-state")).to_have_count(1)
    expect(page.locator("#activity-body")).to_contain_text("规则拦截")
    page.reload()
    expect(page.locator("#video-filter-status")).to_have_value("ENG_POLICY")
    expect(page.locator(".engagement-state")).to_have_count(1)
    state["fail_reads"] = True
    page.locator("#video-filter-status").select_option("ENG_FAILED")
    expect(page.locator("#activity-body")).to_contain_text("列表加载失败")


def test_after_submit_read_failure_does_not_reenable_old_button(engagement_page):
    page, db, dispatch, state = engagement_page
    state["fail_reads"] = True
    button = page.locator('[data-yid="queued"][data-engagement-action="process"]')
    page.once("dialog", lambda dialog: dialog.accept())
    button.click()
    expect(button).to_have_text("请刷新确认状态")
    expect(button).to_be_disabled()
    dispatch.assert_called_once()

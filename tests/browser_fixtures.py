"""共享的隔离 dashboard 与 Chromium 夹具，不连接生产服务。

依赖方向：本测试 → HTML 模板；HTTP 全部由单一路由夹具接管。
通过 runner --browser 使用一次性 Chromium；依赖缺失明确失败，不自动安装。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 覆盖刷新选择、具名删除确认、状态一致性和过期响应隔离。 |
| 1.1.0 | 2026-09-08 | Codex | 使用显式 Chromium 快照，清理异常路径，禁止缺失依赖伪装验收。 |
"""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


TEMPLATE = Path(__file__).resolve().parents[1] / "src/web/templates/index.html"


def _video(yid, status="PENDING"):
    return {
        "youtube_id": yid, "title": f"原始标题 {yid}", "display_title": f"测试视频 {yid}",
        "channel_name": "测试频道", "status": status, "score": 20, "source": "MONITOR",
        "updated_at": "2026-09-08 01:00:00", "source_published_at": "2026-09-07T10:00:00Z",
        "platforms": {"wechat": {"state": status}, "douyin": {"state": "NOT_QUEUED"}},
    }


def _payload(videos, page=1, total=2):
    return {"videos": videos, "total_count": total, "page": page, "total_pages": 2,
            "filter_options": {"channels": ["测试频道"]}}


@pytest.fixture(scope="module")
def chromium():
    from playwright.sync_api import sync_playwright

    root = TEMPLATE.parents[3]
    marker = json.loads((root / ".test-sandbox.json").read_text())
    if "browser" not in marker:
        pytest.fail("浏览器验收必须通过 run_isolated_tests.py --browser 执行")
    executable = Path(marker["browser"]["executable"])
    assert executable.resolve().is_relative_to(root.parent / "browser")
    assert executable.is_file()
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, executable_path=str(executable), timeout=15000)
        try:
            assert browser.version == marker["browser"]["version"]
            yield browser
        finally:
            browser.close()


@pytest.fixture
def dashboard(chromium):
    page = chromium.new_page(viewport={"width": 1440, "height": 1000})
    state = {"payload": _payload([_video("first"), _video("second")]),
             "writes": [], "queries": [], "errors": [], "warnings": []}
    page.on("pageerror", lambda error: state["errors"].append(str(error)))
    page.on("console", lambda message: state["warnings"].append(message.text)
            if message.type in {"error", "warning"} else None)
    html = TEMPLATE.read_text(encoding="utf-8")

    def route_handler(route):
        request = route.request
        parsed = urlparse(request.url)
        if request.method != "GET":
            state["writes"].append({"method": request.method, "path": parsed.path,
                                    "data": request.post_data_json})
            route.fulfill(json={"success": True, "message": "隔离测试：没有实际删除"})
        elif request.is_navigation_request():
            route.fulfill(content_type="text/html", body=html)
        elif parsed.path == "/api/videos":
            state["queries"].append(parse_qs(parsed.query))
            route.fulfill(json=state["payload"])
        elif parsed.path == "/api/stats":
            route.fulfill(json={"total": 2, "pending": 2, "active": 0, "published": 0,
                                "failed": 0, "breakdown": {}, "server_time": "测试时间"})
        elif parsed.path == "/api/channels":
            route.fulfill(json={"approved": [], "total_approved": 0})
        elif parsed.path.startswith("/api/"):
            route.fulfill(json={"success": True, "platforms": {}})
        else:
            route.fulfill(body="")

    page.route("**/*", route_handler)
    page.goto("http://dashboard-test.invalid/", wait_until="networkidle")
    page.evaluate("() => { clearTimeout(refreshTimeoutId); scheduleNextRefresh = () => {}; }")
    page.locator("#row-first").wait_for()
    assert page.title() == "📺 Video Pipeline Control Center"
    try:
        yield page, state
    finally:
        page.close()
    assert not state["errors"]
    assert not state["warnings"]


"""真实 Chromium 的边界拒绝和可视交互证据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-19 | Codex | 对齐既有全视口普通模式隐藏复选框合同，并验证程序化选择也被门禁清除 |
| 1.0.0 | 2026-09-08 | Codex | 验证实际浏览器网络/文件拒绝，保存桌面及窄屏截图 |
"""

import json
from pathlib import Path

import pytest

from tests.browser_fixtures import chromium, dashboard, TEMPLATE


def test_browser_cannot_read_outside_file_or_connect_network(chromium):
    from playwright.sync_api import Error

    marker = json.loads((TEMPLATE.parents[3] / ".test-sandbox.json").read_text())
    page = chromium.new_page()
    try:
        with pytest.raises(Error, match="ERR_ACCESS_DENIED"):
            page.goto(Path(marker["canary"]).as_uri(), timeout=5000)
        # TEST-NET-2 文档地址，不使用线上端口；必须是权限拒绝而非超时/连接失败。
        with pytest.raises(Error, match=r"ERR_(NETWORK_)?ACCESS_DENIED"):
            page.goto("http://198.51.100.1/", timeout=5000)
    finally:
        page.close()


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}])
def test_dashboard_render_and_selection_evidence(dashboard, viewport):
    page, state = dashboard
    page.set_viewport_size(viewport)
    assert page.url == "http://dashboard-test.invalid/"
    assert page.title() == "📺 Video Pipeline Control Center"
    assert page.locator("#row-first").is_visible()
    assert not page.locator("#platform-detail-modal").is_visible()
    page.locator("#batch-normal-view .btn-batch-del").click()
    evidence = TEMPLATE.parents[4] / "qa/browser"
    evidence.mkdir(parents=True, exist_ok=True)
    stem = f"dashboard-{viewport['width']}x{viewport['height']}"
    page.screenshot(path=str(evidence / f"{stem}-before-selection.png"), full_page=True)
    page.locator("#row-first .row-cb").check(timeout=5000)
    assert page.locator("#batch-selected-count").inner_text() == "1"
    assert not state["writes"] and not state["errors"] and not state["warnings"]
    page.screenshot(path=str(evidence / f"{stem}.png"), full_page=True)
    (evidence / f"{stem}.json").write_text(json.dumps({
        "url": page.url, "title": page.title(), "viewport": viewport,
        "selected": page.evaluate("[..._selectedYids]"),
        "console_errors": state["errors"], "console_warnings": state["warnings"],
        "document_width": page.evaluate("document.documentElement.scrollWidth"),
    }, ensure_ascii=False, indent=2))
    page.get_by_role("button", name="退出编辑", exact=True).click()
    # 既有 CSS 在所有视口的普通模式隐藏选择列，不点击不可见控件。
    checkbox = page.locator("#row-first .row-cb")
    assert not checkbox.is_visible()
    # 即便脚本试图勾选隐藏控件，业务门禁也必须清空选择；不是 force-click 绕过 UI。
    checkbox.evaluate("element => { element.checked = true; element.dispatchEvent(new Event('change', {bubbles: true})); }")
    assert not checkbox.is_checked()
    assert not page.locator("#batch-edit-view").is_visible()
    assert page.evaluate("[..._selectedYids]") == []

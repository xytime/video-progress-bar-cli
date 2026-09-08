"""记录真实浏览器渲染前的 DOM/图片载入状态，不替换渲染输出。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 包装截图/PDF 方法观察真实页面，检查资源与内容并保留验收记录 |
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page


@pytest.fixture
def render_audit(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    marker = json.loads((root / ".test-sandbox.json").read_text())
    if "browser" not in marker:
        pytest.fail("研报渲染验收必须通过 run_isolated_tests.py --browser 执行")
    records = []

    def observe(original):
        def capture(page, *args, **kwargs):
            assert page.context.browser.version == marker["browser"]["version"]
            state = page.evaluate("""() => ({
                text: document.body.innerText,
                width: document.documentElement.scrollWidth,
                viewport: window.innerWidth,
                fonts: document.fonts.status,
                images: [...document.images].map(i => ({src: i.src, width: i.naturalWidth,
                                                       height: i.naturalHeight, complete: i.complete}))
            })""")
            assert state["width"] == state["viewport"] == 1080
            assert state["fonts"] == "loaded"
            assert state["images"] and all(i["complete"] and i["width"] > 0 for i in state["images"])
            records.append(state)
            return original(page, *args, **kwargs)
        return capture

    monkeypatch.setattr(Page, "screenshot", observe(Page.screenshot))
    monkeypatch.setattr(Page, "pdf", observe(Page.pdf))
    return records

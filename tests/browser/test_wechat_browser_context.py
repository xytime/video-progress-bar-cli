"""真实 Chromium 隔离浏览器环境下微信浏览器上下文工厂配置一致性与身份隔离回归测试。

# Modification History
| Version | Date       | Author      | Description                                                                  |
|---------|------------|-------------|------------------------------------------------------------------------------|
| 1.0.0   | 2026-09-28 | Antigravity | 真实 Chromium 验证两独立微信上下文的基础配置/UA/指纹完全一致，以及 Cookie 与 localStorage 严格身份隔离。 |
"""

import json
from pathlib import Path

from tests.browser_fixtures import chromium
from video_processing.core.wechat_browser_context import (
    WECHAT_USER_AGENT,
    WECHAT_VIEWPORT,
    create_wechat_context,
)


def test_wechat_browser_contexts_configuration_parity_and_identity_isolation(chromium, tmp_path):
    """验证由 create_wechat_context 创建的两个独立浏览器上下文：
    1. 基础环境配置（Viewport、User-Agent、webdriver、window.chrome、plugins、languages 等）严格一致；
    2. 会话身份存储（Cookies、localStorage）完全独立隔离，互不串扰。
    """
    session1_state = {
        "cookies": [
            {
                "name": "session_token",
                "value": "context_1_secret_token",
                "domain": "channels.weixin.qq.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ],
        "origins": [
            {
                "origin": "https://channels.weixin.qq.com",
                "localStorage": [
                    {"name": "account_uid", "value": "finder_author_001"}
                ],
            }
        ],
    }
    state_file_1 = tmp_path / "wechat_state_1.json"
    state_file_1.write_text(json.dumps(session1_state, ensure_ascii=False), encoding="utf-8")

    # 创建两个独立上下文：ctx1 带已有会话凭据，ctx2 为干净独立会话（模拟 relogin 或未授权）
    ctx1 = create_wechat_context(chromium, storage_state=state_file_1)
    ctx2 = create_wechat_context(chromium, storage_state=None)

    def handle_route(route):
        route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body="""<!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"><title>WeChat Channels Mock Page</title></head>
            <body><div id="app">Channels Mock</div></body>
            </html>""",
        )

    try:
        ctx1.route("https://channels.weixin.qq.com/**", handle_route)
        ctx2.route("https://channels.weixin.qq.com/**", handle_route)

        page1 = ctx1.new_page()
        page2 = ctx2.new_page()

        page1.goto("https://channels.weixin.qq.com/platform/post/create")
        page2.goto("https://channels.weixin.qq.com/platform/post/create")

        # 1. 验证配置一致性（Viewport、User-Agent、反检测注入环境）
        assert page1.viewport_size == WECHAT_VIEWPORT
        assert page2.viewport_size == WECHAT_VIEWPORT
        assert page1.viewport_size == page2.viewport_size
        assert page1.viewport_size == {"width": 1280, "height": 800}

        ua1 = page1.evaluate("navigator.userAgent")
        ua2 = page2.evaluate("navigator.userAgent")
        assert ua1 == WECHAT_USER_AGENT
        assert ua2 == WECHAT_USER_AGENT
        assert ua1 == ua2
        assert "HeadlessChrome" not in ua1
        assert "Chrome/124.0.0.0 Safari/537.36" in ua1

        # 反检测脚本注入一致性断言
        assert page1.evaluate("navigator.webdriver") is False
        assert page2.evaluate("navigator.webdriver") is False

        chrome1 = page1.evaluate(
            "() => ({ hasChrome: typeof window.chrome === 'object', hasRuntime: typeof window.chrome?.runtime === 'object' })"
        )
        chrome2 = page2.evaluate(
            "() => ({ hasChrome: typeof window.chrome === 'object', hasRuntime: typeof window.chrome?.runtime === 'object' })"
        )
        assert chrome1["hasChrome"] and chrome1["hasRuntime"]
        assert chrome2["hasChrome"] and chrome2["hasRuntime"]

        assert page1.evaluate("navigator.plugins.length") == 5
        assert page2.evaluate("navigator.plugins.length") == 5

        langs1 = page1.evaluate("Array.from(navigator.languages)")
        langs2 = page2.evaluate("Array.from(navigator.languages)")
        assert langs1 == ["zh-CN", "zh", "en"]
        assert langs2 == ["zh-CN", "zh", "en"]

        leaks1 = page1.evaluate("() => [window.__playwright, window.__pw_manual, window._phantom]")
        leaks2 = page2.evaluate("() => [window.__playwright, window.__pw_manual, window._phantom]")
        assert leaks1 == [None, None, None]
        assert leaks2 == [None, None, None]

        # 2. 验证身份与会话状态严格隔离
        # Cookie 隔离检查
        cookies1 = ctx1.cookies()
        cookies2 = ctx2.cookies()
        c1_tokens = [c["value"] for c in cookies1 if c["name"] == "session_token"]
        c2_tokens = [c["value"] for c in cookies2 if c["name"] == "session_token"]
        assert c1_tokens == ["context_1_secret_token"]
        assert c2_tokens == []

        # LocalStorage 隔离检查
        storage1_val = page1.evaluate("localStorage.getItem('account_uid')")
        storage2_val = page2.evaluate("localStorage.getItem('account_uid')")
        assert storage1_val == "finder_author_001"
        assert storage2_val is None

        # 变异隔离检查：修改 ctx2 不影响 ctx1
        page2.evaluate("localStorage.setItem('account_uid', 'finder_author_002')")
        ctx2.add_cookies([
            {
                "name": "session_token",
                "value": "context_2_separate_token",
                "domain": "channels.weixin.qq.com",
                "path": "/",
            }
        ])

        # 断言 ctx1 状态未被污染
        assert page1.evaluate("localStorage.getItem('account_uid')") == "finder_author_001"
        c1_tokens_after = [c["value"] for c in ctx1.cookies() if c["name"] == "session_token"]
        assert c1_tokens_after == ["context_1_secret_token"]

        # 断言 ctx2 拥有独立的变异状态
        assert page2.evaluate("localStorage.getItem('account_uid')") == "finder_author_002"
        c2_tokens_after = [c["value"] for c in ctx2.cookies() if c["name"] == "session_token"]
        assert c2_tokens_after == ["context_2_separate_token"]

    finally:
        ctx1.close()
        ctx2.close()

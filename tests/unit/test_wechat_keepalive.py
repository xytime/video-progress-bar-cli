"""Unit tests for WeChat Session Keepalive script (wechat_keepalive.py).

# Modification History
| Version | Date       | Author                              | Description                              |
|---------|------------|-------------------------------------|------------------------------------------|
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | Initial creation: 5 unit tests covering  |
|         |            |                                     | logged-in, session-expired, missing-file,|
|         |            |                                     | ambiguous-URL, and DOM-fallback scenarios|
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


# ── 辅助工厂 ─────────────────────────────────────────────────────────────────

def _make_page_mock(url: str, dom_login: bool = False):
    """创建 Playwright page mock，模拟指定 URL 和 DOM 状态。"""
    page = MagicMock()
    page.url = url
    page.goto.return_value = None
    page.wait_for_timeout.return_value = None
    page.wait_for_load_state.return_value = None

    # 登录 DOM 检测相关 locator
    login_loc = MagicMock()
    login_loc.is_visible.return_value = dom_login
    page.locator.return_value = login_loc
    return page


def _make_sync_playwright_context(page_mock, context_mock=None):
    """搭建完整的 sync_playwright 上下文 mock 链。"""
    if context_mock is None:
        context_mock = MagicMock()
    context_mock.new_page.return_value = page_mock
    context_mock.storage_state.return_value = None
    context_mock.add_init_script.return_value = None

    browser_mock = MagicMock()
    browser_mock.new_context.return_value = context_mock
    browser_mock.close.return_value = None

    p_mock = MagicMock()
    p_mock.chromium.launch.return_value = browser_mock

    playwright_ctx = MagicMock()
    playwright_ctx.__enter__ = MagicMock(return_value=p_mock)
    playwright_ctx.__exit__ = MagicMock(return_value=False)
    return playwright_ctx, browser_mock, context_mock


# ── Test 1: Session 活跃（URL 明确包含 /post/create）→ 刷新并退出 0 ─────────

def test_keepalive_session_active(tmp_path):
    """已登录场景：URL 含 /post/create，停留 dwell 秒后保存 Session，返回 0。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text("{}")  # 假装已有 session 文件

    page_mock = _make_page_mock(url="https://channels.weixin.qq.com/platform/post/create")
    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=1)

    assert result == 0
    context_mock.storage_state.assert_called_once_with(path=str(state_file))
    browser_mock.close.assert_called_once()


# ── Test 2: Session 过期（URL 含 login）→ 发 Telegram 报警，退出 2 ───────────

def test_keepalive_session_expired(tmp_path):
    """未登录场景：URL 含 login，返回 2（LOGIN_REQUIRED）。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text("{}")

    page_mock = _make_page_mock(url="https://channels.weixin.qq.com/login.html")
    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)

    mock_requests = MagicMock()
    mock_requests.post.return_value = MagicMock(ok=True)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx), \
         patch("scripts.wechat_keepalive._requests", mock_requests), \
         patch.dict("os.environ", {
             "TELEGRAM_BOT_TOKEN": "fake_token",
             "TELEGRAM_CHAT_ID": "12345"
         }):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=1)

    assert result == 2
    # 应该发送了 Telegram 报警
    mock_requests.post.assert_called_once()
    call_args = mock_requests.post.call_args
    assert "sendMessage" in call_args[0][0]
    # Session 未刷新（已过期，不保存）
    context_mock.storage_state.assert_not_called()
    browser_mock.close.assert_called_once()


# ── Test 3: Session 文件不存在 → 直接返回 1，不启动浏览器 ─────────────────────

def test_keepalive_no_state_file(tmp_path):
    """Session 文件缺失场景：跳过浏览器启动，直接返回 1。"""
    state_file = tmp_path / "nonexistent_state.json"
    # 故意不创建 state_file

    playwright_ctx, _, _ = _make_sync_playwright_context(MagicMock())

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx) as mock_pw:
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=1)

    assert result == 1
    # 浏览器不应该被启动
    mock_pw.__enter__.assert_not_called()


# ── Test 4: URL 模糊（非 /post/create 也非 login）→ 额外等待后检测 ──────────

def test_keepalive_ambiguous_url_then_login(tmp_path):
    """URL 模糊场景（如首页 /）：额外等待后重新检测 URL，检测到 login 后返回 2。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text("{}")

    page_mock = MagicMock()
    # 第一次访问返回模糊 URL（首页），第二次访问（wait_for_timeout 后）返回 login URL
    page_mock.url = "https://channels.weixin.qq.com/"
    page_mock.goto.return_value = None
    page_mock.wait_for_load_state.return_value = None

    call_count = {"n": 0}
    original_url = "https://channels.weixin.qq.com/"

    def dynamic_url():
        call_count["n"] += 1
        if call_count["n"] >= 2:
            return "https://channels.weixin.qq.com/login.html"
        return original_url

    type(page_mock).url = property(lambda self: dynamic_url())
    page_mock.wait_for_timeout.return_value = None
    login_loc = MagicMock()
    login_loc.is_visible.return_value = False
    page_mock.locator.return_value = login_loc

    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=1)

    assert result == 2
    context_mock.storage_state.assert_not_called()


# ── Test 5: URL 模糊 + DOM 回退检测为已登录 → 刷新成功，退出 0 ──────────────

def test_keepalive_ambiguous_url_dom_fallback_logged_in(tmp_path):
    """URL 模糊场景：URL 始终不含 /post/create 或 login，DOM 检测显示已登录，返回 0。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text("{}")

    page_mock = MagicMock()
    # URL 始终是首页，不含特征字符串
    type(page_mock).url = property(lambda self: "https://channels.weixin.qq.com/")
    page_mock.goto.return_value = None
    page_mock.wait_for_load_state.return_value = None
    page_mock.wait_for_timeout.return_value = None

    # DOM 检测：没有登录框（已登录状态）
    login_loc = MagicMock()
    login_loc.is_visible.return_value = False
    page_mock.locator.return_value = login_loc

    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=1)

    assert result == 0
    context_mock.storage_state.assert_called_once_with(path=str(state_file))
    browser_mock.close.assert_called_once()

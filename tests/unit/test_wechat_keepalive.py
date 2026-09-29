"""Unit tests for WeChat Session Keepalive script (wechat_keepalive.py).

# Modification History
| Version | Date       | Author                              | Description                              |
|---------|------------|-------------------------------------|------------------------------------------|
| 1.3.1   | 2026-09-28 | Antigravity                         | 修复 _make_page_mock：建模 get_by_role/get_by_text count=0 与 frames=[]，防止 TypeError 误判 DOM_ERROR |
| 1.3.0   | 2026-09-28 | Antigravity                         | 整改 WX-AUTH-20260927：增加正向发布控件校验、网络超时重试与故障分类、存储失败阻断、锁忙 (11) 及不伪造授权时刻 |
| 1.2.0   | 2026-09-25 | Codex | 过期保活仍保留重登调度所需的时间标记。 |
| 1.1.0   | 2026-09-08 | Codex | 注入实际被业务读取的 settings 单例，报警单测不依赖宿主 Telegram 配置 |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | Initial creation: unit tests covering logged-in, session-expired, missing-file |
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_processing.core.wechat_auth_state import read_wechat_auth_state
from video_processing.core.wechat_session_lock import (
    EXIT_WECHAT_SESSION_BUSY,
    WeChatSessionLock,
)


def _make_page_mock(url: str, dom_login: bool = False, has_file_input: bool = True):
    """创建 Playwright page mock，模拟指定 URL、登录状态和正向控件。"""
    page = MagicMock()
    page.url = url
    page.goto.return_value = None
    page.wait_for_timeout.return_value = None
    page.wait_for_load_state.return_value = None
    page.evaluate.return_value = has_file_input
    page.frames = []
    page.main_frame = None

    # 登录 DOM 检测与控件 locator
    login_loc = MagicMock()
    login_loc.is_visible.return_value = dom_login
    login_loc.count.return_value = 1 if dom_login else 0
    login_loc.first = login_loc
    login_loc.nth.return_value = login_loc
    page.locator.return_value = login_loc

    # role / text locator mock 建模：无控件时 count=0, visible=False, evaluate=False
    control_loc = MagicMock()
    control_loc.count.return_value = 0
    control_loc.is_visible.return_value = False
    control_loc.first = control_loc
    control_loc.nth.return_value = control_loc
    control_loc.evaluate.return_value = False
    page.get_by_role.return_value = control_loc
    page.get_by_text.return_value = control_loc
    return page


def _make_sync_playwright_context(page_mock, context_mock=None):
    """搭建完整的 sync_playwright 上下文 mock 链，支持原子写入。"""
    if context_mock is None:
        context_mock = MagicMock()
    context_mock.new_page.return_value = page_mock
    # 模拟真实 Playwright 写入 storage_state 文件
    context_mock.storage_state.side_effect = lambda path: Path(path).write_text('{"cookies": []}', encoding="utf-8")
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


# ── Test 1: Session 活跃（URL 包含 /post/create 且正向控件存在）→ 刷新并退出 0 ──

def test_keepalive_session_active(tmp_path):
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    page_mock = _make_page_mock(
        url="https://channels.weixin.qq.com/platform/post/create",
        has_file_input=True,
    )
    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=0)

    assert result == 0
    assert context_mock.storage_state.called
    browser_mock.close.assert_called_once()

    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "SUCCESS"
    assert auth_state["last_verified_at"] is not None


# ── Test 2: Session 过期（URL 含 login）→ 发 Telegram 报警，退出 2 ───────────

def test_keepalive_session_expired(tmp_path):
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    page_mock = _make_page_mock(url="https://channels.weixin.qq.com/login.html")
    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)

    mock_requests = MagicMock()
    mock_requests.post.return_value = MagicMock(ok=True)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx), \
         patch("scripts.wechat_keepalive._requests", mock_requests), \
         patch.multiple("scripts.wechat_keepalive.settings",
                        telegram_bot_token="fake_token", telegram_chat_id="12345"):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=0)

    assert result == 2
    mock_requests.post.assert_called_once()
    assert "sendMessage" in mock_requests.post.call_args[0][0]
    context_mock.storage_state.assert_not_called()
    browser_mock.close.assert_called_once()

    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "LOGIN_REQUIRED"


def test_expired_session_preserves_relogin_marker(tmp_path, monkeypatch):
    from scripts import wechat_keepalive as keepalive

    state_file = tmp_path / "wechat_state.json"
    state_file.write_text("{}")
    login_at = tmp_path / "wechat_login_at.txt"
    login_at.write_text("123")
    warned = tmp_path / "wechat_login_warned.flag"
    warned.write_text("1")
    monkeypatch.setattr(keepalive, "_WARNED_FILE", str(warned))
    monkeypatch.setattr(keepalive, "_send_telegram", lambda _message: None)
    page = _make_page_mock("https://channels.weixin.qq.com/login.html")
    playwright_ctx, _, _ = _make_sync_playwright_context(page)
    monkeypatch.setattr(keepalive, "sync_playwright", lambda: playwright_ctx)

    assert keepalive.run_keepalive(state_path=str(state_file), dwell=0) == 2
    assert login_at.read_text() == "123"
    assert warned.read_text() == "1"


# ── Test 3: Session 文件不存在 → 直接返回 1，不启动浏览器 ─────────────────────

def test_keepalive_no_state_file(tmp_path):
    state_file = tmp_path / "nonexistent_state.json"
    playwright_ctx, _, _ = _make_sync_playwright_context(MagicMock())

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx) as mock_pw:
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=0)

    assert result == 1
    mock_pw.__enter__.assert_not_called()


# ── Test 4: 页面未完成渲染 / 空白骨架屏（无正向控件）→ 拒绝乐观判定，返回 1 ──

def test_keepalive_blank_page_unready_fails_closed(tmp_path):
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    # URL 在 post/create，但无正向发布控件（SPA 未加载完成或空白）
    page_mock = _make_page_mock(
        url="https://channels.weixin.qq.com/platform/post/create",
        has_file_input=False,
    )
    # 所有备选 locator 均不可见
    page_mock.locator.return_value.is_visible.return_value = False

    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=0)

    assert result == 1
    # 未就绪时不覆盖旧 state
    context_mock.storage_state.assert_not_called()
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "PAGE_UNREADY"


# ── Test 5: 导航网络超时有界重试 → 记录 NETWORK_TIMEOUT，退出 1 ────────────

def test_keepalive_network_timeout_bounded_retry(tmp_path):
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    page_mock = MagicMock()
    page_mock.goto.side_effect = TimeoutError("Page.goto: Timeout 25000ms exceeded")
    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=0)

    assert result == 1
    # 验证尝试了 2 次导航
    assert page_mock.goto.call_count == 2
    context_mock.storage_state.assert_not_called()

    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "NETWORK_TIMEOUT"
    assert auth_state["last_failure"]["error_type"] == "NETWORK_TIMEOUT"


# ── Test 6: 存储保存失败 → 报错返回 1，不报成功 ─────────────────────────────

def test_keepalive_storage_failure_fails_closed(tmp_path):
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    page_mock = _make_page_mock(
        url="https://channels.weixin.qq.com/platform/post/create",
        has_file_input=True,
    )
    playwright_ctx, browser_mock, context_mock = _make_sync_playwright_context(page_mock)
    context_mock.storage_state.side_effect = OSError("Disk write error")

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=0)

    assert result == 1
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "STORAGE_FAILED"


# ── Test 7: 锁忙冲突 → 返回 EXIT_WECHAT_SESSION_BUSY (11) ───────────────────

def test_keepalive_lock_busy_returns_exit_code_11(tmp_path):
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    from scripts.wechat_keepalive import run_keepalive

    # 先行持有排他会话锁
    with WeChatSessionLock(state_file, purpose="发布"):
        result = run_keepalive(state_path=str(state_file), dwell=0)

    assert result == EXIT_WECHAT_SESSION_BUSY


# ── Test 8: 保活绝不伪造授权时间 ─────────────────────────────────────────────

def test_keepalive_does_not_forge_authorized_at(tmp_path):
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    page_mock = _make_page_mock(
        url="https://channels.weixin.qq.com/platform/post/create",
        has_file_input=True,
    )
    playwright_ctx, _, _ = _make_sync_playwright_context(page_mock)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=playwright_ctx):
        from scripts.wechat_keepalive import run_keepalive
        result = run_keepalive(state_path=str(state_file), dwell=0)

    assert result == 0
    auth_state = read_wechat_auth_state(state_file)
    # authorized_at 保持为 None，绝不伪造为当前时间
    assert auth_state["authorized_at"] is None
    assert auth_state["last_verified_at"] is not None

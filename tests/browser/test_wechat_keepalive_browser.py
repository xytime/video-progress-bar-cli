"""真实隔离 Chromium 中的视频号保活与独立复用验收测试。

覆盖：
1. 控件就绪（真实正向发布控件加载完成）→ 验证通过，Cookie 原子保存，状态为 SUCCESS
2. SPA 尚未加载 / 空白页（无正向发布控件）→ 拒绝乐观成功，不覆盖 state，退出 1
3. 错误来源（非官方域名重定向）→ 阻断退出 1
4. 登录框（明确重定向至登录页并含登录容器）→ 判定 LOGIN_REQUIRED，退出 2
5. 锁冲突（会话排他锁被发布占用）→ 退出 EXIT_WECHAT_SESSION_BUSY (11)
6. 独立全新上下文复用验证（verify_wechat_session_reuse）→ 校验 Cookie 携带与发布页正向识别

# Modification History
| Version | Date       | Author      | Description                                                  |
|---------|------------|-------------|--------------------------------------------------------------|
| 1.0.0   | 2026-09-28 | Antigravity | 初始创建：真实 Chromium 下保活正向校验、SPA未就绪、错误来源、锁忙及独立复用 |
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.verify_wechat_session_reuse import verify_session_reuse
from scripts.wechat_keepalive import run_keepalive
from tests.browser_fixtures import chromium
from video_processing.core.wechat_auth_state import (
    read_wechat_auth_state,
    record_wechat_authorization,
)
from video_processing.core.wechat_session_lock import (
    EXIT_WECHAT_SESSION_BUSY,
    WeChatSessionLock,
)


def _setup_browser_route(chromium, route_fn):
    """为 chromium 创建上下文并挂载路由拦截，返回代理 launch 对象。"""
    class _MockPlaywright:
        def __init__(self, browser):
            self.chromium = MagicMock()
            self._browser = browser

            def _custom_launch(*args, **kwargs):
                orig_new_context = self._browser.new_context

                def _wrapped_new_context(*c_args, **c_kwargs):
                    ctx = orig_new_context(*c_args, **c_kwargs)
                    ctx.route("**/*", route_fn)
                    return ctx

                mock_b = MagicMock()
                mock_b.new_context = _wrapped_new_context
                mock_b.close = lambda: None
                return mock_b

            self.chromium.launch = _custom_launch

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    return _MockPlaywright(chromium)


def test_browser_keepalive_positive_controls_success(chromium, tmp_path):
    """场景 1：真实 Chromium 访问官方发布页，正向控件就绪 → 成功刷新并原子保存。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text(json.dumps({
        "cookies": [{"name": "test_s", "value": "123", "domain": "channels.weixin.qq.com", "path": "/"}],
        "origins": [],
    }))
    record_wechat_authorization(state_file, method="desktop_quick", timestamp=1720000000.0)

    html_content = """<!DOCTYPE html>
    <html>
      <head><title>视频号助手</title></head>
      <body>
        <div class="weui-desktop-layout__main">
          <input type="file" name="media" />
          <button class="upload-btn">上传视频</button>
          <button>发表</button>
        </div>
      </body>
    </html>"""

    def handle_route(route):
        url = route.request.url
        if "platform/post/create" in url:
            route.fulfill(content_type="text/html; charset=utf-8", body=html_content)
        else:
            route.fulfill(status=404, body="Not Found")

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=mock_pw):
        code = run_keepalive(state_path=str(state_file), dwell=0)

    assert code == 0
    # 状态文件存在且非空
    assert state_file.stat().st_size > 0
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "SUCCESS"
    assert auth_state["authorized_at"] == 1720000000.0  # 授权时间未被破坏
    assert auth_state["last_verified_at"] is not None


def test_browser_keepalive_spa_unready_blank_page(chromium, tmp_path):
    """场景 2：页面停留在发布页但 SPA 尚未加载（白屏/无发布控件）→ 拒绝乐观成功，不覆盖 state。"""
    state_file = tmp_path / "wechat_state.json"
    initial_content = json.dumps({
        "cookies": [{"name": "initial_cookie", "value": "xyz", "domain": "channels.weixin.qq.com", "path": "/"}],
        "origins": [],
    })
    state_file.write_text(initial_content)
    record_wechat_authorization(state_file, method="desktop_quick", timestamp=1720000000.0)

    # 空白骨架屏，无 input[type=file] 也无任何上传按钮
    blank_html = """<!DOCTYPE html>
    <html>
      <head><title>视频号助手</title></head>
      <body>
        <div id="app"><div class="skeleton-loading">加载中...</div></div>
      </body>
    </html>"""

    def handle_route(route):
        url = route.request.url
        if "platform/post/create" in url:
            route.fulfill(content_type="text/html; charset=utf-8", body=blank_html)
        else:
            route.fulfill(status=404, body="Not Found")

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=mock_pw):
        code = run_keepalive(state_path=str(state_file), dwell=0)

    assert code == 1
    # 验证原 state 文件未被破坏或覆盖
    assert state_file.read_text() == initial_content
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "PAGE_UNREADY"
    assert auth_state["authorized_at"] == 1720000000.0


def test_browser_keepalive_wrong_origin(chromium, tmp_path):
    """场景 3：重定向到非预期外部域名 → 拒绝判定成功，退出 1。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    def handle_route(route):
        url = route.request.url
        if "wrong-origin.invalid" in url:
            route.fulfill(content_type="text/html; charset=utf-8", body="<h1>Wrong Origin</h1>")
        else:
            # 客户端安全重定向，避免沙箱触发未解析 DNS
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body='<script>window.location.replace("https://wrong-origin.invalid/error");</script>',
            )

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=mock_pw):
        code = run_keepalive(state_path=str(state_file), dwell=0)

    assert code == 1
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "INVALID_ORIGIN"


def test_browser_keepalive_login_required(chromium, tmp_path):
    """场景 4：重定向至登录页且出现登录扫码容器 → 明确判定 LOGIN_REQUIRED，退出 2。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    login_html = """<!DOCTYPE html>
    <html>
      <head><title>微信视频号 - 登录</title></head>
      <body>
        <div class="login-box">
          <p>使用微信扫码登录</p>
        </div>
      </body>
    </html>"""

    def handle_route(route):
        url = route.request.url
        if "platform/login" in url:
            route.fulfill(content_type="text/html; charset=utf-8", body=login_html)
        else:
            # 客户端安全重定向至微信官方登录页
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body='<script>window.location.replace("https://channels.weixin.qq.com/platform/login");</script>',
            )

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=mock_pw), \
         patch("scripts.wechat_keepalive._send_telegram") as mock_tg:
        code = run_keepalive(state_path=str(state_file), dwell=0)

    assert code == 2
    mock_tg.assert_called_once()
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "LOGIN_REQUIRED"


def test_browser_keepalive_lock_busy(tmp_path):
    """场景 5：会话共享锁被占用 → 立即退出 EXIT_WECHAT_SESSION_BUSY (11)，不拉起浏览器。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text('{"cookies": []}')

    with WeChatSessionLock(state_file, purpose="发布"):
        code = run_keepalive(state_path=str(state_file), dwell=0)

    assert code == EXIT_WECHAT_SESSION_BUSY


def test_browser_verify_session_reuse_independent_context(chromium, tmp_path):
    """场景 6：在独立全新上下文验证 state_file 的 Cookie 携带与发布页正向识别。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text(json.dumps({
        "cookies": [{
            "name": "session_token",
            "value": "token_abc_123",
            "domain": "channels.weixin.qq.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "expires": -1,
        }],
        "origins": [],
    }))
    record_wechat_authorization(state_file, method="scan_qr", timestamp=1720000000.0)

    received_cookies = []

    def handle_route(route):
        req = route.request
        if "platform/post/create" in req.url:
            cookie_hdr = req.headers.get("cookie", "")
            received_cookies.append(cookie_hdr)
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body="""<!DOCTYPE html><html><body>
                <input type="file" name="media" />
                <button class="upload-btn">上传视频</button>
                </body></html>""",
            )
        else:
            route.fulfill(status=404, body="Not Found")

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.verify_wechat_session_reuse.sync_playwright", return_value=mock_pw):
        receipt = verify_session_reuse(state_file)

    assert receipt["success"] is True
    assert receipt["origin_verified"] is True
    assert receipt["positive_controls_verified"] is True
    assert receipt["login_required"] is False
    assert any("session_token=token_abc_123" in c for c in received_cookies)


def test_browser_keepalive_generic_file_input_rejected_as_unready(chromium, tmp_path):
    """反例 1：仅包含空泛的普通 file input（非 video）与通用按钮 → 拒绝判定成功，报 PAGE_UNREADY。"""
    state_file = tmp_path / "wechat_state.json"
    initial_content = json.dumps({
        "cookies": [{"name": "s_cookie", "value": "xyz", "domain": "channels.weixin.qq.com", "path": "/"}],
        "origins": [],
    })
    state_file.write_text(initial_content)
    record_wechat_authorization(state_file, method="desktop_quick", timestamp=1720000000.0)

    generic_html = """<!DOCTYPE html>
    <html>
      <head><title>视频号助手</title></head>
      <body>
        <form>
          <input type="file" name="avatar" accept="image/*" />
          <button type="submit">发表</button>
        </form>
      </body>
    </html>"""

    def handle_route(route):
        url = route.request.url
        if "platform/post/create" in url:
            route.fulfill(content_type="text/html; charset=utf-8", body=generic_html)
        else:
            route.fulfill(status=404, body="Not Found")

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=mock_pw):
        code = run_keepalive(state_path=str(state_file), dwell=0)

    assert code == 1
    assert state_file.read_text() == initial_content
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "PAGE_UNREADY"


def test_browser_keepalive_late_redirect_during_dwell_detected(chromium, tmp_path):
    """反例 2：停留期间发生迟到重定向至登录页 → 最终保存前二次校验阻断，判定 LOGIN_REQUIRED 并退出 2。"""
    state_file = tmp_path / "wechat_state.json"
    initial_content = json.dumps({
        "cookies": [{"name": "expire_token", "value": "old_val", "domain": "channels.weixin.qq.com", "path": "/"}],
        "origins": [],
    })
    state_file.write_text(initial_content)
    record_wechat_authorization(state_file, method="desktop_quick", timestamp=1720000000.0)

    html_with_late_redirect = """<!DOCTYPE html>
    <html>
      <head><title>视频号助手</title></head>
      <body>
        <input type="file" accept="video/mp4" />
        <button class="upload-btn">上传视频</button>
        <script>
          setTimeout(() => {
            window.location.replace("https://channels.weixin.qq.com/platform/login");
          }, 100);
        </script>
      </body>
    </html>"""

    login_html = """<!DOCTYPE html><html><body><div class="login-box">使用微信扫码登录</div></body></html>"""

    def handle_route(route):
        url = route.request.url
        if "platform/post/create" in url:
            route.fulfill(content_type="text/html; charset=utf-8", body=html_with_late_redirect)
        elif "platform/login" in url:
            route.fulfill(content_type="text/html; charset=utf-8", body=login_html)
        else:
            route.fulfill(status=404, body="Not Found")

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=mock_pw), \
         patch("scripts.wechat_keepalive._send_telegram") as mock_tg:
        code = run_keepalive(state_path=str(state_file), dwell=1)

    assert code == 2
    mock_tg.assert_called_once()
    assert state_file.read_text() == initial_content
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "LOGIN_REQUIRED"


def test_browser_spa_guard_dom_error_during_probe_rejects_positive_success(chromium):
    """反例 3：当轮 DOM 探针异常（如 evaluate/DOM 抛错），即使页面存在正向控件也绝不放行，fail-closed 返回 DOM_ERROR。"""
    from video_processing.core.wechat_page_contract import wait_for_publish_ready_with_spa_guard

    page = chromium.new_page()
    try:
        page.set_content("""
        <html>
          <body>
            <input type="file" accept="video/mp4" />
            <button class="upload-btn">上传视频</button>
          </body>
        </html>
        """)

        # 即使页面有视频控件，如果 check_explicit_login_prompt 探针发生 DOM 异常
        with patch("video_processing.core.wechat_page_contract.is_official_wechat_origin", return_value=True), \
             patch("video_processing.core.wechat_page_contract.is_official_create_url", return_value=True), \
             patch("video_processing.core.wechat_page_contract.check_explicit_login_prompt", return_value=(False, "DOM_ERROR")):
            ready, err_cat = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=0.6, poll_interval=0.1)
            assert ready is False
            assert err_cat == "DOM_ERROR"

        # 如果 check_strong_video_publish_controls 探针发生 DOM 异常
        with patch("video_processing.core.wechat_page_contract.is_official_wechat_origin", return_value=True), \
             patch("video_processing.core.wechat_page_contract.is_official_create_url", return_value=True), \
             patch("video_processing.core.wechat_page_contract.check_explicit_login_prompt", return_value=(False, None)), \
             patch("video_processing.core.wechat_page_contract.check_strong_video_publish_controls", return_value=(False, "DOM_ERROR")):
            ready, err_cat = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=0.6, poll_interval=0.1)
            assert ready is False
            assert err_cat == "DOM_ERROR"
    finally:
        page.close()


def test_browser_strict_origin_rejects_userinfo_and_non_default_port(chromium, tmp_path):
    """反例 4：严格 origin 拒绝携带 userinfo 或非默认 443 端口的 URL，并在 keepalive 中记录 INVALID_ORIGIN。"""
    from video_processing.core.wechat_page_contract import is_official_wechat_origin, is_official_create_url

    # 1. 严格契约函数判据
    assert not is_official_wechat_origin("https://admin:secret@channels.weixin.qq.com/platform/post/create")
    assert not is_official_wechat_origin("https://channels.weixin.qq.com:8443/platform/post/create")
    assert not is_official_wechat_origin("http://channels.weixin.qq.com/platform/post/create")
    assert not is_official_create_url("https://admin:secret@channels.weixin.qq.com/platform/post/create")
    assert not is_official_create_url("https://channels.weixin.qq.com:8443/platform/post/create")

    # 2. 真实浏览器路由跳转至伪造非默认端口 URL，keepalive 拒绝并记录 INVALID_ORIGIN
    state_file = tmp_path / "wechat_state.json"
    initial_content = json.dumps({
        "cookies": [{"name": "s_cookie", "value": "xyz", "domain": "channels.weixin.qq.com", "path": "/"}],
        "origins": [],
    })
    state_file.write_text(initial_content)
    record_wechat_authorization(state_file, method="desktop_quick", timestamp=1720000000.0)

    def handle_route(route):
        url = route.request.url
        if ":8443" in url:
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body="<html><body><h1>Non-default port page</h1></body></html>",
            )
        else:
            # 客户端安全重定向，原页返回本地 HTML 做 JS location.replace 跳转，避免 302 触发底层沙箱网络拒绝
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body='<script>window.location.replace("https://channels.weixin.qq.com:8443/platform/post/create");</script>',
            )

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.wechat_keepalive.sync_playwright", return_value=mock_pw):
        code = run_keepalive(state_path=str(state_file), dwell=0)

    assert code == 1
    assert state_file.read_text() == initial_content
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state["last_keepalive_status"] == "INVALID_ORIGIN"


def test_browser_verify_session_reuse_generic_file_input_rejected(chromium, tmp_path):
    """反例 5：verify_session_reuse 遇到普通图片上传或通用提交按钮时，严格拒绝正向通过。"""
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text(json.dumps({
        "cookies": [{"name": "session_token", "value": "token_abc_123", "domain": "channels.weixin.qq.com", "path": "/"}],
        "origins": [],
    }))
    record_wechat_authorization(state_file, method="scan_qr", timestamp=1720000000.0)

    def handle_route(route):
        req = route.request
        if "platform/post/create" in req.url:
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body="""<!DOCTYPE html><html><body>
                <input type="file" name="avatar" accept="image/*" />
                <button type="submit">发表</button>
                </body></html>""",
            )
        else:
            route.fulfill(status=404, body="Not Found")

    mock_pw = _setup_browser_route(chromium, handle_route)

    with patch("scripts.verify_wechat_session_reuse.sync_playwright", return_value=mock_pw):
        receipt = verify_session_reuse(state_file)

    assert receipt["success"] is False
    assert receipt["positive_controls_verified"] is False
    assert receipt["error_type"] == "PAGE_UNREADY"

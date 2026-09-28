"""视频号官方页面判据单一真相源。

由 uploader、keepalive 与 session reuse verifier 共享，
消除各模块在 URL 校验、正向视频发布强控件和登录判定上的判据漂移。

依赖方向：
core/wechat_page_contract.py -> 标准库（0 外部业务依赖）。

# Modification History
| Version | Date       | Author      | Description                                                  |
|---------|------------|-------------|--------------------------------------------------------------|
| 1.2.0   | 2026-09-28 | Antigravity | 新增 is_official_wechat_frame_origin，严格过滤 iframe 的非默认端口与 userinfo |
| 1.1.0   | 2026-09-28 | Antigravity | 修复 DOM 异常跳过正向判定、严格拒绝非默认端口与 userinfo、统一 create/list 来源判据 |
| 1.0.0   | 2026-09-28 | Antigravity | 初始创建：统一官方源、强正向发布控件、明确登录提示与SPA有界等待判据 |
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

OFFICIAL_SCHEME = "https"
OFFICIAL_HOST = "channels.weixin.qq.com"
OFFICIAL_CREATE_PATH = "/platform/post/create"
OFFICIAL_LIST_PATH = "/platform/post/list"


def is_official_wechat_origin(url: str) -> bool:
    """严格核验是否为官方 HTTPS 微信视频号创作者域名。

    严格拒绝非 https 协议、非官方域名、URL userinfo（user:pass@）及非默认端口（如 :8443）。
    """
    if not url:
        return False
    try:
        u = urlsplit(url)
        if u.scheme != OFFICIAL_SCHEME:
            return False
        # 严格拒绝 userinfo，防止凭据或伪装注入
        if u.username or u.password:
            return False
        # 严格拒绝非默认 HTTPS 端口
        if u.port is not None and u.port != 443:
            return False
        # 严格官方域名
        if u.hostname != OFFICIAL_HOST:
            return False
        return True
    except Exception:
        return False


OFFICIAL_FRAME_HOSTS = frozenset({OFFICIAL_HOST, "open.weixin.qq.com"})


def is_official_wechat_frame_origin(url: str) -> bool:
    """严格核验登录/授权 iframe 来源：必须为官方 HTTPS、默认 443 端口、无 userInfo，且 host 为官方视频号或微信开放平台。"""
    if not url:
        return False
    try:
        u = urlsplit(url)
        if u.scheme != OFFICIAL_SCHEME:
            return False
        if u.username or u.password:
            return False
        if u.port is not None and u.port != 443:
            return False
        if u.hostname not in OFFICIAL_FRAME_HOSTS:
            return False
        return True
    except Exception:
        return False


def is_official_create_url(url: str) -> bool:
    """严格核验是否为官方视频发布创建页（统一域名与路径判据）。"""
    if not is_official_wechat_origin(url):
        return False
    try:
        u = urlsplit(url)
        return u.path == OFFICIAL_CREATE_PATH
    except Exception:
        return False


def is_official_list_url(url: str) -> bool:
    """严格核验是否为官方作品列表页（统一域名与路径判据）。"""
    if not is_official_wechat_origin(url):
        return False
    try:
        u = urlsplit(url)
        return u.path == OFFICIAL_LIST_PATH
    except Exception:
        return False


def check_explicit_login_prompt(page: Any) -> tuple[bool, str | None]:
    """检查页面是否明确处于登录状态（登录页 URL 或 DOM 登录二维码/扫码框）。

    Returns:
        (is_login, error_category)
        若检测到登录，返回 (True, None)；
        若检测正常且无登录框，返回 (False, None)；
        若 DOM 探针执行异常，返回 (False, "DOM_ERROR")，调用方绝不能把异常当作无登录框。
    """
    try:
        cur_url = getattr(page, "url", "")
        u = urlsplit(cur_url)
        if "login" in u.path.lower():
            return True, None

        # DOM 探针
        is_login = bool(
            page.locator("text=使用微信扫码登录").is_visible(timeout=500)
            or page.locator(".login-box").is_visible(timeout=500)
            or page.locator(".login-qr").is_visible(timeout=500)
            or page.locator("iframe[src*='login']").is_visible(timeout=500)
        )
        return is_login, None
    except Exception as exc:
        logger.warning("DOM probe for login failed: %s", type(exc).__name__)
        return False, "DOM_ERROR"


def check_strong_video_publish_controls(page: Any) -> tuple[bool, str | None]:
    """检查页面是否存在视频号正向视频发布强特征控件。

    必须满足以下任一条件：
    1. input[type='file'] 且 accept 包含 'video' 或 'mp4'；
    2. 带视频专属文案的上传按钮或上传区域。
    严格拒绝：
    - 普通空泛的 input[type='file']（如头像/图片上传）
    - 通用“发表”或“提交”按钮

    Returns:
        (is_ready, error_category)
    """
    try:
        has_video_input = page.evaluate("""() => {
            const inputs = document.querySelectorAll('input[type="file"]');
            for (const input of inputs) {
                const accept = (input.getAttribute('accept') || '').toLowerCase();
                if (accept.includes('video') || accept.includes('mp4')) {
                    return true;
                }
            }
            return false;
        }""")
        if has_video_input:
            return True, None

        if (
            page.locator("button:has-text('上传视频')").is_visible(timeout=300)
            or page.locator(".upload-btn:has-text('上传视频')").is_visible(timeout=300)
            or page.locator(".upload-area:has-text('视频')").is_visible(timeout=300)
        ):
            return True, None

        return False, "PAGE_UNREADY"
    except Exception as exc:
        logger.warning("DOM probe for publish controls failed: %s", type(exc).__name__)
        return False, "DOM_ERROR"


def wait_for_publish_ready_with_spa_guard(
    page: Any,
    timeout_seconds: float = 6.0,
    poll_interval: float = 0.3,
) -> tuple[bool, str | None]:
    """有界等待 Vue SPA 渲染正向视频发布控件，并持续监控登录跳转、域名漂移与 DOM 异常。

    Fail-closed 铁律：
    本轮若发生任何 DOM 异常 (dom_err 或 ctrl_err == 'DOM_ERROR')，绝对不能跳过并报成功！
    必须记录 DOM_ERROR 并进入下一轮重试；若直到超时仍未脱离异常/未就绪状态，返回失败。

    Returns:
        (ready, error_category)
        成功：(True, None)
        失败：(False, "INVALID_ORIGIN" | "LOGIN_REQUIRED" | "PAGE_UNREADY" | "DOM_ERROR")
    """
    deadline = time.monotonic() + max(0.5, timeout_seconds)
    last_err = "PAGE_UNREADY"
    while time.monotonic() < deadline:
        # 1. 严格域名、协议、端口与 userinfo 校验
        if not is_official_wechat_origin(page.url):
            return False, "INVALID_ORIGIN"

        # 2. 检查是否出现明确登录提示
        is_login, dom_err = check_explicit_login_prompt(page)
        if dom_err:
            last_err = "DOM_ERROR"
            # 严格 fail-closed：本轮 DOM 探针异常，禁止继续尝试判定正向成功，休眠后重试
            page.wait_for_timeout(int(poll_interval * 1000))
            continue

        if is_login:
            return False, "LOGIN_REQUIRED"

        # 3. 检查路径是否为官方创建页
        if not is_official_create_url(page.url):
            return False, "PAGE_UNREADY"

        # 4. 检查正向控件
        controls_ok, ctrl_err = check_strong_video_publish_controls(page)
        if ctrl_err == "DOM_ERROR":
            last_err = "DOM_ERROR"
            # 严格 fail-closed：控件检测发生 DOM 异常，禁止报成功，休眠后重试
            page.wait_for_timeout(int(poll_interval * 1000))
            continue

        if controls_ok:
            # 找到控件后，二次核验 URL 未在渲染瞬间发生重定向
            if is_official_create_url(page.url):
                return True, None
            return False, "INVALID_ORIGIN" if not is_official_wechat_origin(page.url) else "PAGE_UNREADY"

        last_err = "PAGE_UNREADY"
        page.wait_for_timeout(int(poll_interval * 1000))

    return False, last_err

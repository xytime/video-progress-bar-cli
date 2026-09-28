"""视频号官方页面判据单一真相源。

由 uploader、keepalive 与 session reuse verifier 共享，
消除各模块在 URL 校验、正向视频发布强控件和登录判定上的判据漂移。

依赖方向：
core/wechat_page_contract.py -> 标准库（0 外部业务依赖）。

# Modification History
| Version | Date       | Author      | Description                                                  |
|---------|------------|-------------|--------------------------------------------------------------|
| 1.4.0   | 2026-09-28 | Antigravity | 精简正向控件：顶层优先+同源子frame、去除substring捷径、精确get_by_role与get_by_text祖先核验 |
| 1.3.0   | 2026-09-28 | Antigravity | 扩展正向发布控件：支持官方同源视频号子 iframe 视频 input 与可见上传容器专属选择视频控件 |
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


MAX_PROBE_CANDIDATES = 20


def _probe_official_video_file_input(page: Any) -> tuple[bool, str | None]:
    """检查顶层或官方同源视频号子 iframe 中是否存在真实视频 input[type='file']。

    执行逻辑：
    1. 优先在顶层 page.evaluate 执行原视频 input 探针；
    2. 若未命中，遍历检查官方同源子 frames（排除 main_frame，无 frames 时安全兼容返回 False）；
    3. 防导航竞态：在采信子 iframe evaluate True 之前，再次核验该 frame 当前 URL 仍为官方同源；
    4. 任何 DOM 执行异常统一返回 (False, "DOM_ERROR")。
    """
    video_input_script = """() => {
        const inputs = document.querySelectorAll('input[type="file"]');
        for (const input of inputs) {
            const accept = (input.getAttribute('accept') || '').toLowerCase();
            if (accept.includes('video') || accept.includes('mp4')) {
                return true;
            }
        }
        return false;
    }"""

    # 1. 顶层 page.evaluate 探针
    try:
        if page.evaluate(video_input_script):
            return True, None
    except Exception as exc:
        logger.warning("Top page DOM probe for video input failed: %s", type(exc).__name__)
        return False, "DOM_ERROR"

    # 2. 未命中，遍历官方同源子 frames（排除 main_frame）
    try:
        frames = getattr(page, "frames", []) or []
        main_fr = getattr(page, "main_frame", None)
        for fr in frames:
            if fr is main_fr:
                continue
            fr_url = getattr(fr, "url", "")
            if not is_official_wechat_frame_origin(fr_url):
                continue
            u = urlsplit(fr_url)
            if u.hostname != OFFICIAL_HOST:
                continue
            if fr.evaluate(video_input_script):
                # 防导航竞态：采信 evaluate 结果前，再次核验 frame 当前 URL 仍保持官方同源无注入
                post_url = getattr(fr, "url", "")
                if is_official_wechat_frame_origin(post_url):
                    u_post = urlsplit(post_url)
                    if u_post.hostname == OFFICIAL_HOST:
                        return True, None
    except Exception as exc:
        logger.warning("Subframe DOM probe for video input failed: %s", type(exc).__name__)
        return False, "DOM_ERROR"

    return False, None


def _probe_upload_container_video_button(page: Any) -> tuple[bool, str | None]:
    """检查页面是否存在精准合法的视频上传/选择专用按钮。

    判据规则：
    1. 历史合法按钮兼容：通过 get_by_role("button", name="上传视频", exact=True) 精准匹配；
       若且仅若恰好存在 1 个可见按钮时采信；
    2. 新版 picker 路径：通过 get_by_text("选择视频", exact=True) 精准匹配；
       若且仅若恰好存在 1 个可见目标且其拥有包含 upload/Upload 的容器祖先时采信；
    3. 有界探针铁律：总元素数超过 MAX_PROBE_CANDIDATES 时直接拒绝，禁止截断前N个妄断唯一；
    4. 严格去除任何 substring 弱匹配捷径，任何否定或异常状态直接失配；
    5. 任何 DOM 执行异常统一返回 (False, "DOM_ERROR")。
    """
    try:
        # 1. 兼容旧版精确“上传视频”按钮（专属视频动作）
        legacy_btn = page.get_by_role("button", name="上传视频", exact=True)
        legacy_cnt = legacy_btn.count()
        if legacy_cnt > MAX_PROBE_CANDIDATES:
            # 超过探针上限，无法安全判定唯一可见性，拒绝
            return False, None

        visible_legacy = 0
        for i in range(legacy_cnt):
            if legacy_btn.nth(i).is_visible(timeout=50):
                visible_legacy += 1
        if visible_legacy == 1:
            return True, None
        if visible_legacy > 1:
            # 重复可见冲突，直接拒绝
            return False, None

        # 2. 新版 picker 路径：get_by_text("选择视频", exact=True) 精准唯一可见目标并核验其上传祖先
        picker_candidates = page.get_by_text("选择视频", exact=True)
        picker_cnt = picker_candidates.count()
        if picker_cnt > MAX_PROBE_CANDIDATES:
            # 超过探针上限，无法安全判定唯一可见性，拒绝
            return False, None

        visible_pickers = []
        for i in range(picker_cnt):
            item = picker_candidates.nth(i)
            if item.is_visible(timeout=50):
                visible_pickers.append(item)

        if len(visible_pickers) == 1:
            target_el = visible_pickers[0]
            # 核验其上传祖先
            has_upload_ancestor = target_el.evaluate(
                "node => Boolean(node.closest('[class*=\"upload\"], [class*=\"Upload\"], .upload-btn, .upload-area'))"
            )
            if has_upload_ancestor:
                return True, None

        return False, None
    except Exception as exc:
        logger.warning("Upload button probe failed: %s", type(exc).__name__)
        return False, "DOM_ERROR"


def check_strong_video_publish_controls(page: Any) -> tuple[bool, str | None]:
    """检查页面是否存在视频号正向视频发布强特征控件。

    必须满足以下任一条件：
    1. 顶层页面或官方同源视频号子 iframe 中存在 accept 包含 'video' 或 'mp4' 的 input[type='file']；
    2. 可见上传容器内部存在精准匹配且唯一可见的 '选择视频' 专属控件，或精确 '上传视频' 按钮。
    严格拒绝：
    - 普通空泛的 input[type='file']（如头像/图片上传）
    - 非官方域名的 iframe 内部 input
    - 通用“发表”或“提交”按钮
    - 脱离上传容器的孤立文本或裸“选择视频”按钮
    - 包含“不可选择视频”、“选择视频失败”等否定干扰的文本
    - 重复可见的多个选择/上传控件

    Fail-closed 铁律：
    若任何子探针出现 DOM 异常，必须立即返回 (False, "DOM_ERROR")，禁止误报成功或未就绪。

    Returns:
        (is_ready, error_category)
    """
    try:
        # 1. 优先核验顶层及官方同源 iframe 内是否存在真实视频 input
        has_input, err_input = _probe_official_video_file_input(page)
        if err_input == "DOM_ERROR":
            return False, "DOM_ERROR"
        if has_input:
            return True, None

        # 2. 核验页面是否存在合法且唯一的视频选择/上传专属控件
        has_btn, err_btn = _probe_upload_container_video_button(page)
        if err_btn == "DOM_ERROR":
            return False, "DOM_ERROR"
        if has_btn:
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

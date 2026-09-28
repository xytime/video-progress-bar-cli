"""WeChat Session Keepalive Script

仅用于维持微信视频号 Web 端 Session 活跃，防止因闲置导致登录态过期。
不执行任何上传/发布操作，仅访问发布页并停留指定时长后退出。

# Modification History
| Version | Date       | Author                              | Description                                                  |
|---------|------------|-------------------------------------|--------------------------------------------------------------|
| 1.5.0   | 2026-09-28 | Antigravity | 整改 WX-AUTH-20260927：去除首次保活伪造授权时间；增加官方来源与正向发布控件校验（消除乐观成功）；导航有界重试并分离网络超时/SPA未就绪/LOGIN_REQUIRED；存储原子写入且失败报失败；锁冲突返回 EXIT_WECHAT_SESSION_BUSY (11)。 |
| 1.4.0   | 2026-09-25 | Codex | 登录过期时保留会话龄标记，让控制台恢复流程仍能识别过期会话。 |
| 1.3.0   | 2026-09-19 | Codex | 评论互动开关启用时，以登录态派生共享锁覆盖完整保活会话。 |
| 1.2.0   | 2026-06-27 | Claude_Opus_4.8 | 临期预警/过期告警话术改为引导「发 /wechat_login 取二维码到 Telegram 手机扫码」，与 pipeline_agent 无头 QR 推送闭环（替代原终端 --no-headless 命令） |
| 1.1.0   | 2026-06-27 | Claude_Opus_4.8 | [无痛重登·预警] 会话龄追踪(标记文件，刷新不重置、过期清零) + 临期预警：龄超 settings.wechat_session_warn_hours(默认22h) 即推 Telegram「该重扫」，在 ~24h 服务端硬上限断档前提醒；Telegram 凭据迁移至 settings（消除 os.environ 违规） |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 初始创建：WeChat Session 看门狗脚本，仅访问发布页刷新 Cookie |

Exit Codes:
    0 - Session 活跃，Cookie 已刷新且正向控件校验通过
    1 - 运行时错误（网络超时、SPA 未就绪、非微信来源、存储保存失败等）
    2 - Session 已过期（LOGIN_REQUIRED），需重新扫码
    11 - 锁占用（EXIT_WECHAT_SESSION_BUSY）
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

# [Claude_Opus_4.8] 接入 settings 单一真相源（临期预警阈值 + Telegram 凭据，消除 os.environ 违规）
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from config.settings import settings
from video_processing.core.wechat_session_lock import (
    EXIT_WECHAT_SESSION_BUSY,
    guarded_wechat_browser_session,
)
from video_processing.core.wechat_auth_state import (
    read_wechat_auth_state,
    record_wechat_keepalive_result,
)

try:
    import requests as _requests
except ImportError:
    _requests = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("wechat_keepalive")

WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"
_WARNED_FILE = "output/wechat_login_warned.flag"


def _send_telegram(html: str) -> None:
    """推送 Telegram（凭据走 settings 单一真相源）。未配置/失败仅记录，不抛。"""
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.active_telegram_chat_id or "").strip()
    if not (token and chat_id and _requests):
        logger.warning("[Keepalive] Telegram not configured; skip notify.")
        return
    try:
        _requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": html, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as exc:
        logger.error("[Keepalive] Telegram send failed: %s", type(exc).__name__)


def _stamp_login_if_absent(login_at_path: Path) -> None:
    """[已废弃] 旧版首次观测记录逻辑。保活流程中严禁调用，避免伪造授权时刻；保留仅供旧单元测试向后兼容。"""
    if not login_at_path.exists():
        try:
            login_at_path.write_text(str(int(time.time())))
        except Exception as e:
            logger.warning(f"[Keepalive] Failed to stamp login time: {e}")


def _maybe_warn_expiry(login_target: Path, warned_path: Path) -> None:
    """会话龄超过阈值且本登录周期未预警过 → 推 Telegram 临期提醒（每登录周期仅一次）。"""
    login_at = None
    if str(login_target).endswith(".json"):
        auth_state = read_wechat_auth_state(login_target)
        login_at = auth_state.get("authorized_at")
    else:
        try:
            login_at = int(login_target.read_text().strip())
        except Exception:
            login_at = None
    if login_at is None:
        return
    age_h = (time.time() - login_at) / 3600.0
    warn_h = float(settings.wechat_session_warn_hours)
    if age_h >= warn_h and not warned_path.exists():
        _send_telegram(
            f"🟠 <b>WeChat 会话临期（约 {age_h:.1f}h）</b>\n"
            f"服务端 ~24h 硬上限将至，建议现在重扫，避免发布断档。\n"
            f"👉 给 Bot 发 <code>/wechat_login</code>，登录二维码会推到这里，手机微信扫码即可。"
        )
        try:
            warned_path.write_text(str(int(time.time())), encoding="utf-8")
        except Exception:
            pass
        logger.info(f"[Keepalive] Sent pre-expiry warning (age={age_h:.1f}h >= {warn_h}h).")


@guarded_wechat_browser_session(
    enabled=lambda: True,
    purpose="保活",
    state_parameter="state_path",
    timeout_seconds=0.0,
    busy_result=EXIT_WECHAT_SESSION_BUSY,
)
def run_keepalive(
    state_path: str = "output/wechat_state.json",
    dwell: int = 15,
) -> int:
    """执行一次 WeChat Session 保活操作。

    加载现有 Session，访问发布创建页并验证正向发布控件，停留 dwell 秒后原子保存刷新后的 Cookie。
    若检测到已被重定向到登录页，则发送 Telegram 报警并退出码 2。
    若检测到网络超时、页面未就绪或存储失败，记录明确证据并退出码 1，绝不覆盖旧 state。

    Args:
        state_path: wechat_state.json 路径。
        dwell: 停留时长（秒），给微信服务端足够时间记录活跃请求。

    Returns:
        0 - Session 活跃且正向控件验证通过，Cookie 已原子保存
        1 - 运行时错误（网络超时、SPA 未就绪、非微信来源、存储保存失败等）
        2 - SESSION 已过期，需重新登录
        11 - 锁占用（EXIT_WECHAT_SESSION_BUSY）
    """
    state_file = Path(state_path)

    if not state_file.exists():
        logger.error(f"Session file not found: {state_file}. Cannot keepalive without existing session.")
        record_wechat_keepalive_result(
            state_file,
            status="UNKNOWN_STATE",
            failure={
                "stage": "precheck",
                "error_type": "SESSION_FILE_NOT_FOUND",
                "detail": f"State file not found: {state_file}",
            },
        )
        return 1

    with sync_playwright() as p:
        logger.info("[Keepalive] Launching headless browser...")
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-web-security",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1280,800",
                "--no-proxy-server",
                "--host-resolver-rules=MAP localhost.weixin.qq.com 127.0.0.1",
            ]
        )

        context_opts = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "storage_state": str(state_file),
        }

        context = browser.new_context(**context_opts)

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = {
                runtime: {},
                loadTimes: function(){},
                csi: function(){},
                app: {}
            };
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en'] });
            const _oq = window.navigator.permissions.query;
            window.navigator.permissions.query = (p) =>
                p.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : _oq(p);
            delete window.__playwright;
            delete window.__pw_manual;
            delete window._phantom;
        """)

        page = context.new_page()

        # 导航与有界重试（最多重试 1 次，有界超时 25000ms）
        max_nav_attempts = 2
        nav_success = False
        nav_error = None
        for attempt in range(1, max_nav_attempts + 1):
            try:
                logger.info(f"[Keepalive] Navigating to: {WECHAT_CREATE_URL} (attempt {attempt}/{max_nav_attempts})")
                page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded", timeout=25000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                nav_success = True
                break
            except Exception as exc:
                nav_error = exc
                logger.warning(f"[Keepalive] Navigation attempt {attempt} failed: {type(exc).__name__}: {exc}")
                if attempt < max_nav_attempts:
                    page.wait_for_timeout(2000)

        if not nav_success:
            logger.error(f"[Keepalive] Navigation failed after {max_nav_attempts} attempts: {nav_error}")
            record_wechat_keepalive_result(
                state_file,
                status="NETWORK_TIMEOUT",
                failure={
                    "stage": "navigation",
                    "error_type": "NETWORK_TIMEOUT",
                    "detail": f"{type(nav_error).__name__}: {nav_error}",
                },
            )
            browser.close()
            return 1

        page.wait_for_timeout(2000)
        current_url = page.url
        logger.info(f"[Keepalive] Current URL: {current_url}")
        url_parts = urlsplit(current_url)

        # 1. 官方域名校验
        if url_parts.hostname != "channels.weixin.qq.com":
            logger.error(f"[Keepalive] Untrusted origin: {url_parts.hostname}")
            record_wechat_keepalive_result(
                state_file,
                status="INVALID_ORIGIN",
                failure={
                    "stage": "navigation",
                    "error_type": "INVALID_ORIGIN",
                    "detail": f"Unexpected hostname {url_parts.hostname}",
                },
            )
            browser.close()
            return 1

        # 2. 显式登录页检测（明确 LOGIN_REQUIRED）
        is_explicit_login = False
        if "login" in url_parts.path.lower():
            is_explicit_login = True
        else:
            try:
                if (
                    page.locator("text=使用微信扫码登录").is_visible(timeout=1000)
                    or page.locator(".login-box").is_visible(timeout=1000)
                    or page.locator(".login-qr").is_visible(timeout=1000)
                ):
                    is_explicit_login = True
            except Exception:
                pass

        if is_explicit_login:
            logger.warning(f"[Keepalive] Session expired (LOGIN_REQUIRED). URL: {current_url}")
            record_wechat_keepalive_result(
                state_file,
                status="LOGIN_REQUIRED",
                failure={
                    "stage": "auth",
                    "error_type": "LOGIN_REQUIRED",
                    "detail": f"Redirected to login: {current_url}",
                },
            )
            _send_telegram(
                "⚠️ <b>WeChat Session 已过期</b>\n"
                "看门狗检测到登录态失效，请尽快重新扫码登录。\n"
                "👉 给 Bot 发 <code>/wechat_login</code>，登录二维码会推到这里，手机微信扫码即可。"
            )
            browser.close()
            return 2

        # 3. 发布页路径检测
        if "/post/create" not in url_parts.path:
            logger.warning(f"[Keepalive] Path not yet /post/create ({url_parts.path}), waiting briefly...")
            try:
                page.wait_for_url("**/post/create", timeout=3000)
            except Exception:
                pass
            current_url = page.url
            url_parts = urlsplit(current_url)

        if "/post/create" not in url_parts.path:
            logger.error(f"[Keepalive] Page path unexpected: {current_url}")
            record_wechat_keepalive_result(
                state_file,
                status="UNKNOWN_STATE",
                failure={
                    "stage": "verification",
                    "error_type": "PAGE_NOT_FOUND",
                    "detail": f"Unexpected URL {current_url}",
                },
            )
            browser.close()
            return 1

        # 4. 正向发布控件/认证证据校验（严禁仅凭无登录框或 DOM 异常当作已登录）
        positive_control_found = False
        try:
            page.wait_for_timeout(1000)
            has_file_input = page.evaluate("() => document.querySelectorAll('input[type=\"file\"]').length > 0")
            if has_file_input:
                positive_control_found = True
            elif (
                page.locator("button:has-text('上传视频')").is_visible(timeout=1000)
                or page.locator(".upload-btn").is_visible(timeout=1000)
                or page.locator(".upload-area").is_visible(timeout=1000)
                or page.locator("button:has-text('发表')").is_visible(timeout=1000)
            ):
                positive_control_found = True
        except Exception as exc:
            logger.warning(f"[Keepalive] Exception checking positive controls: {exc}")

        if not positive_control_found:
            logger.error("[Keepalive] Positive publish controls not found (SPA not loaded / blank page).")
            record_wechat_keepalive_result(
                state_file,
                status="PAGE_UNREADY",
                failure={
                    "stage": "verification",
                    "error_type": "PAGE_UNREADY",
                    "detail": "Positive publish controls not found on /post/create",
                },
            )
            browser.close()
            return 1

        # 临期预警检查（仅检查，不伪造授权时刻）
        _maybe_warn_expiry(state_file, Path(_WARNED_FILE))

        # 5. Session 活跃：停留 dwell 秒
        logger.info(f"[Keepalive] Session verified active with positive controls. Dwelling for {dwell}s...")
        page.wait_for_timeout(dwell * 1000)

        # 6. 保存刷新后的 Cookie / Token（原子写入，写失败报失败）
        tmp_state = state_file.with_name(f".{state_file.name}.tmp.{os.getpid()}")
        try:
            context.storage_state(path=str(tmp_state))
            if not tmp_state.exists() or tmp_state.stat().st_size == 0:
                raise OSError(f"Saved state file is empty or missing: {tmp_state}")
            os.replace(tmp_state, state_file)
            logger.info(f"[Keepalive] Session state refreshed and saved to: {state_file}")
        except Exception as e:
            if tmp_state.exists():
                try:
                    tmp_state.unlink()
                except Exception:
                    pass
            logger.error(f"[Keepalive] Failed to save session state: {e}")
            record_wechat_keepalive_result(
                state_file,
                status="STORAGE_FAILED",
                failure={
                    "stage": "storage",
                    "error_type": "STORAGE_SAVE_FAILED",
                    "detail": str(e),
                },
            )
            browser.close()
            return 1

        record_wechat_keepalive_result(state_file, status="SUCCESS")
        browser.close()
        logger.info("[Keepalive] Keepalive completed successfully.")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="WeChat Session Keepalive — 维持微信视频号 Session 活跃"
    )
    parser.add_argument(
        "--state",
        default="output/wechat_state.json",
        help="Path to Playwright session state JSON file"
    )
    parser.add_argument(
        "--dwell",
        type=int,
        default=15,
        help="Seconds to dwell on the page after confirming login (default: 15)"
    )
    args = parser.parse_args()

    code = run_keepalive(
        state_path=args.state,
        dwell=args.dwell,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()

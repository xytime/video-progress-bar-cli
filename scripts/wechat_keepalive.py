"""WeChat Session Keepalive Script

仅用于维持微信视频号 Web 端 Session 活跃，防止因闲置导致登录态过期。
不执行任何上传/发布操作，仅访问发布页并停留指定时长后退出。

# Modification History
| Version | Date       | Author                              | Description                                                  |
|---------|------------|-------------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 初始创建：WeChat Session 看门狗脚本，仅访问发布页刷新 Cookie |

Exit Codes:
    0 - Session 活跃，Cookie 已刷新
    1 - 未知错误
    2 - Session 已过期（LOGIN_REQUIRED），需重新扫码
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    import requests as _requests
except ImportError:
    _requests = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("wechat_keepalive")

# [Claude_Sonnet_4.6_Thinking_planning] 与 wechat_uploader.py 保持一致
WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"


def run_keepalive(
    state_path: str = "output/wechat_state.json",
    dwell: int = 15,
) -> int:
    """执行一次 WeChat Session 保活操作。

    # [Claude_Sonnet_4.6_Thinking_planning] 1.0.0
    加载现有 Session，访问发布创建页，停留 dwell 秒后保存刷新后的 Cookie。
    若检测到已被重定向到登录页，则发送 Telegram 报警并退出码 2。

    Args:
        state_path: wechat_state.json 路径。
        dwell: 停留时长（秒），给微信服务端足够时间记录活跃请求。

    Returns:
        0 - Session 刷新成功
        1 - 运行时错误
        2 - SESSION 已过期，需重新登录
    """
    state_file = Path(state_path)

    if not state_file.exists():
        logger.error(f"Session file not found: {state_file}. Cannot keepalive without existing session.")
        return 1

    with sync_playwright() as p:
        logger.info("[Keepalive] Launching headless browser...")
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-web-security",
                "--no-sandbox",
                # [Claude_Sonnet_4.6_Thinking_planning] 反检测：与 wechat_uploader 保持一致
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1280,800",
                # [BugFix] 禁止走代理，防止微信安全风控检测到异地 IP 踢掉 Session
                "--no-proxy-server",
            ]
        )

        context_opts = {
            "viewport": {"width": 1280, "height": 800},
            # [Claude_Sonnet_4.6_Thinking_planning] 与保存 Session 时使用同一 UA，防止 UA 变化触发微信重验
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "storage_state": str(state_file),
        }

        context = browser.new_context(**context_opts)

        # [Claude_Sonnet_4.6_Thinking_planning] 反检测指纹伪造（与 wechat_uploader 完全一致）
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

        logger.info(f"[Keepalive] Navigating to: {WECHAT_CREATE_URL}")
        page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded")

        # 等待页面加载稳定
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        current_url = page.url
        logger.info(f"[Keepalive] Current URL: {current_url}")

        # ── 登录状态检测（URL 优先策略，与 wechat_uploader 保持一致）────────────
        if "/post/create" in current_url:
            is_logged_in = True
            logger.info("[Keepalive] Session active (URL confirmed /post/create).")
        elif "login" in current_url:
            is_logged_in = False
            logger.warning(f"[Keepalive] Redirected to login page: {current_url}")
        else:
            # 模糊 URL，等待额外 2 秒再判断
            page.wait_for_timeout(2000)
            current_url = page.url
            if "/post/create" in current_url:
                is_logged_in = True
                logger.info("[Keepalive] Session active (URL confirmed after extra wait).")
            elif "login" in current_url:
                is_logged_in = False
            else:
                # DOM 兜底检测
                try:
                    dom_login = (
                        page.locator("text=使用微信扫码登录").is_visible(timeout=2000) or
                        page.locator(".login-box").is_visible(timeout=2000)
                    )
                    is_logged_in = not dom_login
                except Exception:
                    is_logged_in = True  # 不确定时乐观假设已登录

        if not is_logged_in:
            # [Claude_Sonnet_4.6_Thinking_planning] Session 已过期 → 发送 Telegram 报警
            tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            tg_chat_id = (
                os.environ.get("TELEGRAM_CHAT_ID", "").strip() or
                os.environ.get("TELEGRAM_ADMIN_IDS", "").split(",")[0].strip()
            )
            if tg_token and tg_chat_id and _requests:
                try:
                    _requests.post(
                        f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={
                            "chat_id": tg_chat_id,
                            "text": (
                                "⚠️ <b>WeChat Session 已过期</b>\n"
                                "看门狗检测到登录态失效，请尽快重新扫码登录。\n"
                                "<code>python scripts/wechat_uploader.py --login-only --no-headless</code>"
                            ),
                            "parse_mode": "HTML",
                        },
                        timeout=10,
                    )
                    logger.info("[Keepalive] Sent LOGIN_REQUIRED alert to Telegram.")
                except Exception as e:
                    logger.error(f"[Keepalive] Failed to send Telegram alert: {e}")

            browser.close()
            return 2  # LOGIN_REQUIRED

        # ── Session 活跃：停留 dwell 秒，让微信服务端记录活跃请求 ─────────────
        logger.info(f"[Keepalive] Session active. Dwelling for {dwell}s to refresh cookies...")
        page.wait_for_timeout(dwell * 1000)

        # ── 保存刷新后的 Cookie / Token ────────────────────────────────────────
        try:
            context.storage_state(path=str(state_file))
            logger.info(f"[Keepalive] Session state refreshed and saved to: {state_file}")
        except Exception as e:
            logger.warning(f"[Keepalive] Failed to save session state: {e}")

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

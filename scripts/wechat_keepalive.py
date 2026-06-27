"""WeChat Session Keepalive Script

仅用于维持微信视频号 Web 端 Session 活跃，防止因闲置导致登录态过期。
不执行任何上传/发布操作，仅访问发布页并停留指定时长后退出。

# Modification History
| Version | Date       | Author                              | Description                                                  |
|---------|------------|-------------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 初始创建：WeChat Session 看门狗脚本，仅访问发布页刷新 Cookie |
| 1.1.0   | 2026-06-27 | Claude_Opus_4.8 | [无痛重登·预警] 会话龄追踪(标记文件，刷新不重置、过期清零) + 临期预警：龄超 settings.wechat_session_warn_hours(默认22h) 即推 Telegram「该重扫」，在 ~24h 服务端硬上限断档前提醒；Telegram 凭据迁移至 settings（消除 os.environ 违规） |
| 1.2.0   | 2026-06-27 | Claude_Opus_4.8 | 临期预警/过期告警话术改为引导「发 /wechat_login 取二维码到 Telegram 手机扫码」，与 pipeline_agent 无头 QR 推送闭环（替代原终端 --no-headless 命令） |

Exit Codes:
    0 - Session 活跃，Cookie 已刷新
    1 - 未知错误
    2 - Session 已过期（LOGIN_REQUIRED），需重新扫码
"""

import sys
import time
import argparse
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

# [Claude_Opus_4.8] 接入 settings 单一真相源（临期预警阈值 + Telegram 凭据，消除 os.environ 违规）
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from config.settings import settings

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

# [Claude_Opus_4.8] 会话龄追踪：标记文件记录上次「扫码登录」的近似时刻(epoch)。
# 看门狗的 Cookie 刷新【不】重置它（刷新无法延长 ~24h 服务端硬上限，见 RCA 候选②）；
# 仅在会话过期(login required)时清除，使下一次 active 视为重扫后重新计时。
_LOGIN_AT_FILE = "output/wechat_login_at.txt"
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
    except Exception as e:
        logger.error(f"[Keepalive] Telegram send failed: {e}")


def _stamp_login_if_absent(login_at_path: Path) -> None:
    """首次观测到 active（或重扫后）→ 记录登录时刻；已存在则不动，让会话龄正确累计。"""
    if not login_at_path.exists():
        try:
            login_at_path.write_text(str(int(time.time())))
        except Exception as e:
            logger.warning(f"[Keepalive] Failed to stamp login time: {e}")


def _reset_login_markers(*paths: Path) -> None:
    """会话过期 → 清除登录时刻与已预警标记，便于重扫后重新计时。"""
    for p in paths:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"[Keepalive] Failed to clear marker {p}: {e}")


def _maybe_warn_expiry(login_at_path: Path, warned_path: Path) -> None:
    """会话龄超过阈值且本登录周期未预警过 → 推 Telegram 临期提醒（每登录周期仅一次）。"""
    try:
        login_at = int(login_at_path.read_text().strip())
    except Exception:
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
            warned_path.write_text(str(int(time.time())))
        except Exception:
            pass
        logger.info(f"[Keepalive] Sent pre-expiry warning (age={age_h:.1f}h >= {warn_h}h).")


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
            # [Claude_Opus_4.8] Session 已过期：清除会话龄标记（重扫后重新计时）+ 推 Telegram 报警
            _reset_login_markers(Path(_LOGIN_AT_FILE), Path(_WARNED_FILE))
            _send_telegram(
                "⚠️ <b>WeChat Session 已过期</b>\n"
                "看门狗检测到登录态失效，请尽快重新扫码登录。\n"
                "👉 给 Bot 发 <code>/wechat_login</code>，登录二维码会推到这里，手机微信扫码即可。"
            )
            logger.info("[Keepalive] Sent LOGIN_REQUIRED alert to Telegram.")
            browser.close()
            return 2  # LOGIN_REQUIRED

        # [Claude_Opus_4.8] 会话龄追踪 + 临期预警：首次/重扫后记录登录时刻，临近 ~24h 硬上限主动提醒，
        # 在发布断档前让你有时间重扫（见 docs/wechat_login_expiry_rca.html 候选②坐实）。
        login_at_file = Path(_LOGIN_AT_FILE)
        _stamp_login_if_absent(login_at_file)
        _maybe_warn_expiry(login_at_file, Path(_WARNED_FILE))

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

"""WeChat Channels Session Independent Reuse Verifier

在全新浏览器上下文中独立复用保存的 session 凭证，验证是否能够正常访问
发布页并被正向控件识别。仅用于只读验证，不触发任何上传、发布、评论或消息发送。
日常查询与验证 0 LLM 调用，0 Token 消耗。

# Modification History
| Version | Date       | Author      | Description                                                  |
|---------|------------|-------------|--------------------------------------------------------------|
| 1.0.0   | 2026-09-28 | Antigravity | 初始创建：独立全新上下文复用验证脚本，输出结构化诊断凭据     |
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_processing.core.wechat_auth_state import (
    canonical_wechat_auth_state_path,
    read_wechat_auth_state,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("verify_wechat_session_reuse")

WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"


def verify_session_reuse(state_path: str | Path, *, timeout_ms: int = 25000) -> dict:
    """在隔离全新上下文验证 session 复用能力，返回只读结构化凭据。"""
    state_file = Path(state_path).expanduser().resolve(strict=False)

    receipt = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "state_file": str(state_file),
        "state_file_exists": state_file.is_file(),
        "state_file_size_bytes": state_file.stat().st_size if state_file.is_file() else 0,
        "auth_state": read_wechat_auth_state(state_file),
        "origin_verified": False,
        "positive_controls_verified": False,
        "login_required": False,
        "success": False,
        "error": None,
    }

    if not state_file.is_file():
        receipt["error"] = f"State file not found: {state_file}"
        return receipt

    with sync_playwright() as p:
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
            ],
        )

        try:
            # 独立全新上下文
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                storage_state=str(state_file),
            )

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
                delete window.__playwright;
                delete window.__pw_manual;
            """)

            page = context.new_page()

            try:
                page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
            except Exception as nav_exc:
                receipt["error"] = f"Navigation failed: {type(nav_exc).__name__}: {nav_exc}"
                return receipt

            page.wait_for_timeout(2000)
            current_url = page.url
            receipt["landing_url"] = current_url
            url_parts = urlsplit(current_url)

            # 来源检验
            if url_parts.hostname == "channels.weixin.qq.com":
                receipt["origin_verified"] = True

            # 登录状态判定
            is_login = False
            if "login" in url_parts.path.lower():
                is_login = True
            else:
                try:
                    if (
                        page.locator("text=使用微信扫码登录").is_visible(timeout=1000)
                        or page.locator(".login-box").is_visible(timeout=1000)
                        or page.locator(".login-qr").is_visible(timeout=1000)
                    ):
                        is_login = True
                except Exception:
                    pass

            if is_login:
                receipt["login_required"] = True
                receipt["error"] = "Redirected to login page (session expired)"
                return receipt

            # 正向发布控件校验
            has_positive_controls = False
            try:
                has_file_input = page.evaluate("() => document.querySelectorAll('input[type=\"file\"]').length > 0")
                if has_file_input:
                    has_positive_controls = True
                elif (
                    page.locator("button:has-text('上传视频')").is_visible(timeout=1000)
                    or page.locator(".upload-btn").is_visible(timeout=1000)
                    or page.locator(".upload-area").is_visible(timeout=1000)
                    or page.locator("button:has-text('发表')").is_visible(timeout=1000)
                ):
                    has_positive_controls = True
            except Exception as ctrl_exc:
                logger.warning("Error inspecting controls: %s", ctrl_exc)

            receipt["positive_controls_verified"] = has_positive_controls

            if receipt["origin_verified"] and has_positive_controls:
                receipt["success"] = True
            else:
                receipt["error"] = "Positive publish controls not found on landing page"

        finally:
            browser.close()

    return receipt


def main():
    parser = argparse.ArgumentParser(description="Verify WeChat session reuse in fresh browser context")
    parser.add_argument("--state", default="output/wechat_state.json", help="Path to state file")
    parser.add_argument("--receipt", help="Path to write JSON receipt output")
    parser.add_argument("--timeout", type=int, default=25000, help="Navigation timeout ms")
    args = parser.parse_args()

    result = verify_session_reuse(args.state, timeout_ms=args.timeout)
    formatted = json.dumps(result, ensure_ascii=False, indent=2)
    print(formatted)

    if args.receipt:
        out_p = Path(args.receipt)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(formatted, encoding="utf-8")

    if result.get("success"):
        sys.exit(0)
    elif result.get("login_required"):
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

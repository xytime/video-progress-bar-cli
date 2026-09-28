"""WeChat Channels Session Independent Reuse Verifier

在全新浏览器上下文中独立复用保存的 session 凭证，验证是否能够正常访问
发布页并被正向强特征控件识别。仅用于只读验证，不触发任何上传、发布、评论或消息发送。
日常查询与验证 0 LLM 调用，0 Token 消耗。

# Modification History
| Version | Date       | Author      | Description                                                  |
|---------|------------|-------------|--------------------------------------------------------------|
| 1.2.0   | 2026-09-28 | Antigravity | 接入统一 wechat_browser_context 工厂：统一 Viewport、真实 Chrome UA 与 init_script 反检测指纹。 |
| 1.1.0   | 2026-09-28 | Antigravity | 接入统一 wechat_page_contract，严格 HTTPS 官方域名与正向控件判据；回执脱敏仅输出白名单分类，消除 URL 查询与原始异常泄漏 |
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
    VALID_FAILURE_CATEGORIES,
)
from video_processing.core.wechat_page_contract import (
    is_official_wechat_origin,
    is_official_create_url,
    check_explicit_login_prompt,
    check_strong_video_publish_controls,
    wait_for_publish_ready_with_spa_guard,
)
from video_processing.core.wechat_browser_context import create_wechat_context

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("verify_wechat_session_reuse")

WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"


def verify_session_reuse(state_path: str | Path, *, timeout_ms: int = 25000) -> dict:
    """在隔离全新上下文验证 session 复用能力，返回脱敏只读结构化凭据。"""
    state_file = Path(state_path).expanduser().resolve(strict=False)

    receipt = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "state_file": state_file.name,
        "state_file_exists": state_file.is_file(),
        "state_file_size_bytes": state_file.stat().st_size if state_file.is_file() else 0,
        "origin_verified": False,
        "positive_controls_verified": False,
        "login_required": False,
        "success": False,
        "error_type": None,
        "summary": None,
    }

    if not state_file.is_file():
        receipt["error_type"] = "STORAGE_FAILED"
        receipt["summary"] = "会话文件不存在"
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
            # 独立全新上下文（统一通过 wechat_browser_context 工厂配置 Viewport、UA 与 init_script）
            context = create_wechat_context(browser, storage_state=state_file)

            page = context.new_page()

            try:
                page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
            except Exception as nav_exc:
                logger.warning("Navigation failed during reuse verification: %s", type(nav_exc).__name__)
                receipt["error_type"] = "NAVIGATION_TIMEOUT"
                receipt["summary"] = VALID_FAILURE_CATEGORIES["NAVIGATION_TIMEOUT"]
                return receipt

            # 使用统一页面判据与 SPA 保护门禁进行有界检测
            ready, err_type = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=8.0)
            if ready:
                receipt["origin_verified"] = True
                receipt["positive_controls_verified"] = True
                receipt["success"] = True
            else:
                err_cat = err_type or "PAGE_UNREADY"
                receipt["origin_verified"] = is_official_wechat_origin(page.url)
                receipt["positive_controls_verified"] = False
                receipt["login_required"] = (err_cat == "LOGIN_REQUIRED")
                receipt["success"] = False
                receipt["error_type"] = err_cat
                receipt["summary"] = VALID_FAILURE_CATEGORIES.get(err_cat, "复用验证未通过")

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

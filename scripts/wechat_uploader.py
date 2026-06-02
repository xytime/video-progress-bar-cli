"""WeChat Channels Automated Video Uploader

# Modification History
| Version | Date       | Author                              | Description                                              |
|---------|------------|-------------------------------------|----------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.5_Flash_planning           | Initial creation using Playwright                        |
| 1.1.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 处理短标题/封面/分类/原创勾选；修复登录误判 URL优先策略 |
| 1.2.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | P0根因修复: (1)封面确认改为轮询等待disabled→enabled (2)原创声明增加JS兜底 |
| 1.3.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | 原创声明 v2.0: 抗 UI 变化三层降级架构 (_click_original_toggle + _handle_original_rights_dialog) |
| 1.4.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | 反反爬虫 v1.0: human_mouse+浏览器指纹伪造+关键点击改为人类行为模拟 |
| 1.5.0   | 2026-05-24 | Gemini_3.5_Flash_High_planning      | 修复原创权益弹窗勾选（适配 AntD Checkbox 与 class 类名禁用校验）及分类下拉框 Shadow DOM 穿透 |
| 1.6.0   | 2026-05-27 | Claude_Sonnet_4.6_Thinking_planning | 优雅截断: 引入 graceful_truncate_title，替换硬截断兜底，防止磁盘读入的超长标题被截成半句 |
| 1.7.0   | 2026-05-27 | Gemini_2.0_Flash_fast               | 增加 Web UI 临时二维码自动生成与无头等待扫码支持 |
| 1.8.0   | 2026-05-27 | Antigravity_planning                | 移除彻底失效的分类选择 UI 操作逻辑（微信官方升级已移除），由自然语言 Hashtag 替代 |
| 1.9.0   | 2026-06-02 | Claude_Sonnet_4.6_Thinking_planning | _select_collection 全面重写：5轮DOM探针实证，正确选择器 .post-album-display-wrap/.option-item/.create a |
| 2.0.0   | 2026-06-02 | Claude_Sonnet_4.6_Thinking_planning | bugfix: Modal检测改用wait_for_selector(state=visible)；所有return False前Escape关闭遮罩；publish前清理残留dialog |
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright
import random
import time

# [Claude_Sonnet_4.6_Thinking_planning] 反反爬虫: 人类行为模拟
import sys as _sys
_scripts_dir = str(Path(__file__).parent)
if _scripts_dir not in _sys.path:
    _sys.path.insert(0, _scripts_dir)
from human_mouse import (
    human_click, human_check, find_and_human_click_text,
    find_checkbox_near_text, dispatch_human_click_events,
    _human_delay
)
from copywriter import graceful_truncate_title  # [Claude_Sonnet_4.6_Thinking_planning] v1.6.0

try:
    import requests as _requests
except ImportError:
    _requests = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("wechat_uploader")

# 微信视频号发表地址
WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"



def _select_collection(page, collection_name: str) -> bool:
    """在微信视频号助手页面选择视频合集，若不存在则自动新建。

    # [Claude_Sonnet_4.6_Thinking_planning] v1.9.0 - 5轮DOM探针实证重写
    # 真实 DOM 结构（微信视频号助手发布页）：
    #
    #  div.post-album-display-wrap      ← 点击展开触发器
    #  div.filter-wrap                  ← 展开后面板
    #    div.common-option-list-wrap
    #      div.option-item [.active]    ← 每个合集项（.active=已选中）
    #        div.item
    #          div.name   "合集名"
    #          div.desc   "共N个内容"
    #    div.create
    #      <a>创建新合集</a>             ← 新建按钮
    #
    # 新建后弹出 .weui-desktop-dialog 对话框（与旧代码一致）
    """
    if not collection_name:
        return True

    logger.info(f"Setting collection: {collection_name!r}")

    # ── Step 1: 找触发器并展开 ─────────────────────────────────────────────
    trigger = page.locator(".post-album-display-wrap").first
    if trigger.count() == 0:
        # 兜底：通过「添加到合集」标签找到相邻的显示区
        trigger = page.locator("text=添加到合集").locator(
            "xpath=following-sibling::div//*[contains(@class,'post-album-display')]"
        ).first
    if trigger.count() == 0:
        logger.warning("Could not find collection trigger (.post-album-display-wrap).")
        return False

    try:
        trigger.click(timeout=2000)
    except Exception as e:
        logger.error(f"Failed to click collection trigger: {e}")
        return False

    # ── Step 2: 等待面板展开（以「创建新合集」出现为信号）──────────────────
    try:
        page.wait_for_selector("text=创建新合集", timeout=5000)
        logger.info("Collection dropdown opened.")
    except Exception:
        logger.warning("Collection dropdown did not open within 5s.")
        return False
    page.wait_for_timeout(300)  # 等动画稳定

    # ── Step 3: 在 .option-item 中查找目标合集 ─────────────────────────────
    # 使用 has= 参数：在 .post-album-wrap 下，找 .option-item 且包含 .name 精确文字
    target_item = page.locator(
        ".post-album-wrap .option-item",
        has=page.locator(f".name:text-is('{collection_name}')")
    ).first

    if target_item.count() == 0:
        # text-is 严格匹配失败，退化为 has-text（包含匹配）
        target_item = page.locator(
            ".post-album-wrap .option-item",
            has=page.locator(f".name:has-text('{collection_name}')")
        ).first

    # ── Step 4a: 已存在 → 选中（含去重检测）──────────────────────────────
    if target_item.count() > 0:
        item_class = target_item.get_attribute("class") or ""
        if "active" in item_class:
            # 已经选中，去重直接返回
            logger.info(f"Collection {collection_name!r} already active (dedup). Closing.")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            return True

        logger.info(f"Collection {collection_name!r} found. Selecting...")
        try:
            target_item.click(timeout=2000)
            page.wait_for_timeout(500)
            item_class_after = target_item.get_attribute("class") or ""
            if "active" in item_class_after:
                logger.info(f"Successfully selected collection {collection_name!r}.")
            else:
                logger.warning("Clicked but 'active' class not detected (may still work).")
            return True
        except Exception as e:
            logger.warning(f"Click on collection item failed: {e}, trying JS fallback...")
            try:
                target_item.evaluate("node => node.click()")
                page.wait_for_timeout(500)
                return True
            except Exception as e2:
                logger.error(f"JS click also failed: {e2}")
                return False

    # ── Step 4b: 不存在 → 创建新合集 ─────────────────────────────────────
    logger.info(f"Collection {collection_name!r} not in list. Creating new...")

    # 实证 HTML: <div class="create"><a data-v-021f92ab="">创建新合集 </a></div>
    create_btn = page.locator(".post-album-wrap .create a").first
    if create_btn.count() == 0:
        create_btn = page.get_by_text("创建新合集").first
    if create_btn.count() == 0:
        logger.warning("Could not find '创建新合集' button.")
        page.keyboard.press("Escape")
        return False

    try:
        create_btn.click(timeout=2000)
    except Exception as e:
        logger.error(f"Failed to click '创建新合集': {e}")
        return False

    page.wait_for_timeout(500)

    # ── Step 5: 填写新建 Modal ─────────────────────────────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] v2.0.0 bugfix:
    # is_visible() 在 CSS transition 期间可能误报 False，改用 wait_for_selector
    try:
        page.wait_for_selector(".weui-desktop-dialog", state="visible", timeout=5000)
    except Exception:
        logger.warning("Collection creation dialog did not appear within 5s.")
        # 可能有残留遮罩，按 Escape 清理
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return False
    modal = page.locator(".weui-desktop-dialog").first

    logger.info("New collection creation dialog detected.")
    page.screenshot(path="output/debug_collection_dialog.png")

    input_box = modal.locator(
        "input[type='text'], input[placeholder*='合集名称'], input[placeholder*='标题'], input"
    ).first
    if input_box.count() == 0:
        logger.warning("No input box in creation dialog.")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return False

    import re as _re
    cleaned_name = _re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', collection_name).strip()[:15]
    logger.info(f"Filling dialog with cleaned name: {cleaned_name!r}")

    input_box.fill(cleaned_name)
    page.wait_for_timeout(500)

    confirm_btn = None
    for bt in ["确定", "保存", "创建", "确认"]:
        btn = modal.locator(f"button:has-text('{bt}')").first
        if btn.count() > 0 and btn.is_visible():
            confirm_btn = btn
            break

    if not confirm_btn:
        logger.warning("No confirm button found in creation dialog.")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return False

    ok = human_click(page, confirm_btn)
    if not ok:
        confirm_btn.evaluate("node => node.click()")
    logger.info("Clicked confirm button in new collection dialog.")
    page.wait_for_timeout(1500)
    page.screenshot(path="output/debug_collection_after_create.png")
    return True

def run_uploader(
    video_path: str = None,
    copy_path: str = None,
    state_path: str = "output/wechat_state.json",
    login_only: bool = False,
    headless: bool = True,
    draft: bool = False,
    title_path: str = None,      # 短标题文件（6-16 字，匹配微信平台真实限制）
    cover_path: str = None,      # 封面图文件 (JPEG)
    category_path: str = None,   # 分类文件
    collection: str = None,      # 新增：微信合集名称
) -> int:
    """运行 Playwright 微信上传自动化"""

    state_file = Path(state_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)

    if not login_only:
        if not video_path or not Path(video_path).exists():
            logger.error(f"Video file not found: {video_path}")
            return 1
        if not copy_path or not Path(copy_path).exists():
            logger.error(f"Copy text file not found: {copy_path}")
            return 1
        video_abs  = str(Path(video_path).resolve())
        copy_text  = Path(copy_path).read_text(encoding="utf-8")
        short_title = (
            Path(title_path).read_text(encoding="utf-8").strip()
            if title_path and Path(title_path).exists() else None
        )
        cover_abs  = (
            str(Path(cover_path).resolve())
            if cover_path and Path(cover_path).exists() else None
        )
        category   = (
            Path(category_path).read_text(encoding="utf-8").strip()
            if category_path and Path(category_path).exists() else None
        )
        logger.info(f"short_title={short_title!r}  category={category!r}  collection={collection!r}  cover={'yes' if cover_abs else 'no'}")
    else:
        video_abs = copy_text = short_title = cover_abs = category = collection = None
        headless = False  # 登录时强制显示界面

    with sync_playwright() as p:
        logger.info("Launching browser...")
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-web-security",
                "--no-sandbox",
                # 反检测：隐藏 Headless 特征
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1280,800",
            ]
        )

        # 加载 Cookie 状态
        context_opts = {
            "viewport": {"width": 1280, "height": 800},
            # 使用真实 Chrome UA（与保存 Session 时一致）
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if state_file.exists():
            logger.info(f"Loading session state from: {state_file}")
            context_opts["storage_state"] = str(state_file)

        context = browser.new_context(**context_opts)

        # [Claude_Sonnet_4.6_Thinking_planning] 反检测 v2.0: 完整浏览器指纹伪造
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

        logger.info(f"Navigating to WeChat Channels creation page: {WECHAT_CREATE_URL}")
        page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded")
        # 等待页面完全渲染（Vue SPA 需额外时间）
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(5000)

        # 调试截图：永远保存，方便排查 headless 登录状态
        dbg_pre = state_file.parent / "debug_pre_login_check.png"
        try:
            page.screenshot(path=str(dbg_pre))
            logger.info(f"Pre-login-check screenshot: {dbg_pre}")
        except Exception:
            pass

        # ── 登录状态检测（URL 优先，防止 Vue SPA 未渲染完触发误判）────────────
        current_url = page.url
        logger.info(f"Current URL after load: {current_url}")

        # 1st: URL 包含 /post/create → 明确已登录，跳过所有 DOM 检测
        if "/post/create" in current_url:
            is_login_page = False
            logger.info("Successfully authenticated via saved session (URL confirmed).")
        # 2nd: URL 明确含 login → 未登录
        elif "login" in current_url:
            is_login_page = True
            logger.warning(f"Redirected to login page: {current_url}")
        # 3rd: URL 模糊（如首页 /）→ 再等 3s 后检查 DOM
        else:
            page.wait_for_timeout(3000)
            current_url = page.url
            if "/post/create" in current_url:
                is_login_page = False
                logger.info("Successfully authenticated (URL confirmed after extra wait).")
            elif "login" in current_url:
                is_login_page = True
            else:
                # DOM 检测作为最后手段
                try:
                    dom_login = (
                        page.locator("text=使用微信扫码登录").is_visible(timeout=2000) or
                        page.locator(".login-box").is_visible(timeout=2000) or
                        page.locator(".login-qr").is_visible(timeout=2000)
                    )
                except Exception:
                    dom_login = False
                is_login_page = dom_login
                if is_login_page:
                    # 截图留证，方便排查是否是误判
                    dbg = state_file.parent / "debug_login_detect.png"
                    try:
                        page.screenshot(path=str(dbg))
                        logger.warning(f"Login page detected via DOM. Debug screenshot: {dbg}")
                    except Exception:
                        pass
                else:
                    logger.info("Successfully authenticated (DOM check passed).")

        if is_login_page:
            # [Gemini_2.0_Flash_fast] 无论是否 headless，均尝试捕获并保存 QR 码图片，以供 Web UI 临时扫码登录使用
            try:
                page.wait_for_timeout(2000)  # 等 QR 码渲染
                qr_path = str(state_file.parent / "login_qr.png")
                qr_captured = False
                for qr_sel in ["img.qrcode", ".login-qr img", ".qr-code img",
                               "img[src*='qr']", ".qrcode"]:
                    qr_el = page.locator(qr_sel)
                    if qr_el.count() > 0:
                        try:
                            qr_el.first.screenshot(path=qr_path)
                            qr_captured = True
                            logger.info(f"QR captured via: {qr_sel} (Always-save)")
                            break
                        except Exception:
                            continue
                if not qr_captured:
                    page.screenshot(path=qr_path)
                    logger.info("QR full-page screenshot (fallback, Always-save).")
            except Exception as e_qr:
                logger.warning(f"Failed to capture QR code: {e_qr}")

            if headless:
                # [Claude_Sonnet_4.6_Thinking_fast] P1: Telegram QR 推送登录
                # headless 无弹窗，但可截图 QR 发 Telegram，等扫码后继续上传
                tg_token   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                tg_chat_id = (
                    os.environ.get("TELEGRAM_CHAT_ID", "").strip() or
                    os.environ.get("TELEGRAM_ADMIN_IDS", "").split(",")[0].strip()
                )

                if tg_token and tg_chat_id and _requests:
                    logger.info("Headless login required. Sending QR code to Telegram...")
                    try:
                        # 发送图片到 Telegram
                        caption = (
                            "🔑 微信视频号登录二维码\n"
                            "请在微信扫码授权（有效期约1分钟）\n"
                            "扫码成功后脚本将自动继续上传。"
                        )
                        with open(qr_path, "rb") as f:
                            resp = _requests.post(
                                f"https://api.telegram.org/bot{tg_token}/sendPhoto",
                                data={"chat_id": tg_chat_id, "caption": caption},
                                files={"photo": ("qr.png", f, "image/png")},
                                timeout=15,
                            )
                        if resp.ok:
                            logger.info("QR code sent to Telegram. Waiting for scan (120s)...")
                        else:
                            logger.warning(f"Telegram sendPhoto failed: {resp.text}")
                    except Exception as e_tg:
                        logger.error(f"Failed to send QR to Telegram: {e_tg}")

                # [Gemini_2.0_Flash_fast] 无论是否配置 TG，在 headless 模式下均挂起等待扫码（120秒内由 Web UI 扫码完成登录）
                logger.info("Waiting for QR scan (Web UI / Telegram / App) (120s)...")
                try:
                    page.wait_for_url("**/post/create", timeout=120000)
                    logger.info("Login detected. Saving session...")
                    context.storage_state(path=str(state_file))
                    logger.info(f"Session saved to: {state_file}")
                    
                    # 成功后尝试删除临时二维码
                    if Path(qr_path).exists():
                        try: os.remove(qr_path)
                        except Exception: pass
                        
                    if tg_token and tg_chat_id and _requests:
                        try:
                            _requests.post(
                                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                                json={"chat_id": tg_chat_id, "text": "✅ 微信视频号登录成功，继续上传任务..."},
                                timeout=10,
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"Headless QR login wait timed out or failed: {e}")
                    if Path(qr_path).exists():
                        try: os.remove(qr_path)
                        except Exception: pass
                    browser.close()
                    return 2  # 返回 LOGIN_REQUIRED
            else:
                logger.info("=" * 50)
                logger.info("⚠️ 请在弹出的浏览器窗口中，使用手机微信扫码登录！")
                logger.info("=" * 50)
                try:
                    page.wait_for_url("**/post/create", timeout=120000)
                    logger.info("Login detected. Saving session state...")
                    context.storage_state(path=str(state_file))
                    logger.info(f"Session saved to: {state_file}")
                    if Path(qr_path).exists():
                        try: os.remove(qr_path)
                        except Exception: pass
                except Exception as e:
                    logger.error(f"Login wait timed out or failed: {e}")
                    if Path(qr_path).exists():
                        try: os.remove(qr_path)
                        except Exception: pass
                    browser.close()
                    return 1

        if login_only:
            logger.info("Login-only mode completed successfully.")
            browser.close()
            return 0

        # 2. 上传视频文件 ─ 三段式容错策略
        logger.info(f"Uploading video: {video_abs}")
        upload_ok = False

        # ── 策略 A：直接定位 input[type='file']（包括隐藏元素，Playwright 可设置） ──
        try:
            # 通过 JS 确认 input 数量（穿透 display:none）
            n_inputs = page.evaluate("() => document.querySelectorAll('input[type=\"file\"]').length")
            logger.info(f"Strategy A: JS found {n_inputs} file input(s)")
            if n_inputs > 0:
                file_input = page.locator("input[type='file']").first
                file_input.set_input_files(video_abs)
                logger.info("Strategy A succeeded: file set on hidden input.")
                upload_ok = True
        except Exception as e_a:
            logger.warning(f"Strategy A failed: {e_a}")

        # ── 策略 B：等待上传区域出现后再用 filechooser 事件 ──
        if not upload_ok:
            try:
                logger.info("Strategy B: waiting for upload area then using expect_file_chooser...")
                upload_selectors = [
                    "[class*='upload']:not(div>div)",
                    "button:has-text('上传视频')",
                    "button:has-text('上传')",
                    ".upload-btn", ".upload-area", ".upload-wrapper",
                    "label[for]", "[class*='Upload']",
                ]
                clicked = False
                with page.expect_file_chooser(timeout=10000) as fc_info:
                    for sel in upload_selectors:
                        try:
                            loc = page.locator(sel)
                            if loc.count() > 0 and loc.first.is_visible():
                                loc.first.click()
                                clicked = True
                                logger.info(f"Strategy B: clicked '{sel}'")
                                break
                        except Exception:
                            continue
                if clicked:
                    fc = fc_info.value
                    fc.set_files(video_abs)
                    logger.info("Strategy B succeeded: file set via file chooser.")
                    upload_ok = True
            except Exception as e_b:
                logger.warning(f"Strategy B failed: {e_b}")

        # ── 策略 C：多 selector 暴力枚举 ──
        if not upload_ok:
            try:
                logger.info("Strategy C: trying extended selector list...")
                for sel in ["input[type='file']", "input[accept*='video']",
                            "input[accept*='mp4']", "input[name*='file']"]:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.set_input_files(video_abs)
                        logger.info(f"Strategy C succeeded with selector: {sel}")
                        upload_ok = True
                        break
            except Exception as e_c:
                logger.warning(f"Strategy C failed: {e_c}")

        if not upload_ok:
            # 截图留存，方便人工分析页面结构
            dbg_path = Path(video_abs).parent / f"debug_upload_{Path(video_abs).stem}.png"
            try:
                page.screenshot(path=str(dbg_path), full_page=True)
                logger.error(f"All upload strategies failed. Debug screenshot: {dbg_path}")
            except Exception:
                logger.error("All upload strategies failed and screenshot also failed.")
            browser.close()
            return 1
            
        # ── 3. 等待视频上传完成 ────────────
        logger.info("Waiting for video upload to complete...")
        upload_finished = False
        for i in range(60):  # 60 × 5s = 300s max
            page.wait_for_timeout(5000)
            content = page.content()
            if "上传成功" in content or "已上传100%" in content or "上传完成" in content:
                logger.info("Upload complete (text detected).")
                upload_finished = True
                break
            publish_btn = page.locator("button:has-text('发表')").first
            if publish_btn.count() > 0:
                is_disabled = (
                    publish_btn.get_attribute("disabled") is not None or
                    "disabled" in (publish_btn.get_attribute("class") or "").lower()
                )
                if not is_disabled:
                    logger.info("Upload complete (Publish button enabled).")
                    upload_finished = True
                    break
            logger.info(f"Still uploading... ({i+1}/60)")
        if not upload_finished:
            logger.warning("Upload verification timed out (5 min). Proceeding anyway.")

        # ── 4. 填写视频文案/描述 (等上传完成页面稳定后再填) ────────────
        logger.info("Writing copy to description field...")
        desc_input = None
        for selector in [".input-editor", "div[contenteditable='true']", "textarea", ".editor", ".description-textarea"]:
            try:
                loc = page.locator(selector)
                if loc.count() > 0 and loc.first.is_visible():
                    desc_input = loc.first
                    break
            except Exception:
                continue
                
        if desc_input:
            try:
                desc_input.focus()
                page.keyboard.press("Meta+A")
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.insert_text(copy_text)
                logger.info("Successfully pasted copy description.")
            except Exception as e:
                logger.error(f"Failed to write description: {e}")
        else:
            logger.warning("Could not find description input selector, trying fallback click on text...")
            try:
                page.locator("text=添加描述").click()
                page.keyboard.insert_text(copy_text)
            except Exception as e2:
                logger.error(f"Fallback description fill failed: {e2}")

        # 上传后截图，确认页面状态
        dbg_post = state_file.parent / "debug_post_upload.png"
        try:
            page.screenshot(path=str(dbg_post))
            logger.info(f"Post-upload screenshot: {dbg_post}")
        except Exception:
            pass

        # ── 4. 短标题（视频上传后字段才出现）────────────────────────────────
        # 规则来源：WeChat JS 源码 345.509f6449.js → parseShortTitle() + handleBlur()
        # 允许字符正则：/^[\u2103\u4E00-\u9FA5A-Za-z0-9《》""":：+?？%\s]+$/
        #   ℃ 中文 英文 数字 《》 全角引号 全角冒号 : + ? ？ % 空格
        # 字数：min=6  max=16（.length，即 JS 的字符串长度）
        # 禁止：逗号 , 句号 . 感叹号 ! 其他半角标点（逗号可用空格代替）
        # 输入清洗：去除零宽字符 \u200B

        if short_title:
            import re as _re
            # [Claude_Sonnet_4.6_Thinking_fast] 规则来自 WeChat JS 源码 345.509f6449.js
            # parseShortTitle: /^[\u2103\u4E00-\u9FA5A-Za-z0-9\u300A\u300B\u201C\u201D:+?%\s]+$/
            # handleBlur: length < 6 → "标题至少6个字"; length > 16 → 超过限制
            # handleInput: .replace(/\u200B/g, "")

            # Step 1: 清洗零宽字符
            short_title_clean = short_title.replace('\u200B', '').replace('\uFEFF', '').strip()

            # Step 2: 字数验证
            TITLE_MIN, TITLE_MAX = 6, 16
            if len(short_title_clean) < TITLE_MIN:
                logger.warning(
                    f"Short title too short ({len(short_title_clean)} chars, min={TITLE_MIN}): "
                    f"{short_title_clean!r} — skipping."
                )
                short_title_clean = None
            elif len(short_title_clean) > TITLE_MAX:
                # [Claude_Sonnet_4.6_Thinking_planning] v1.6.0: 优雅截断替换硬截断兜底
                short_title_clean = graceful_truncate_title(short_title_clean, max_len=TITLE_MAX)
                logger.warning(f"Short title gracefully truncated to {len(short_title_clean)} chars: {short_title_clean!r}")

            # Step 3: 字符白名单验证（与 WeChat parseShortTitle 一致）
            TITLE_PAT = _re.compile(
                r'^[\u2103\u4E00-\u9FA5A-Za-z0-9'
                r'\u300A\u300B'           # 《》
                r'\u201C\u201D\u2018\u2019'  # ""''
                r'\uFF02\uFF1A\uFF1F'     # ＂：？
                r':+?%\s]+$'
            )
            if short_title_clean and not TITLE_PAT.match(short_title_clean):
                bad = [c for c in short_title_clean if not TITLE_PAT.match(c)]
                logger.warning(
                    f"Short title has forbidden chars {bad!r}: {short_title_clean!r}. "
                    "Allowed: 中文/英数/《》/全角引号/：/+/？/%/空格. 逗号→空格."
                )
                # 自动修复：逗号→空格，其余非法字符删除
                cleaned = _re.sub(r'[,，。！!；;]', ' ', short_title_clean)
                cleaned = _re.sub(
                    r'[^\u2103\u4E00-\u9FA5A-Za-z0-9'
                    r'\u300A\u300B\u201C\u201D\u2018\u2019'
                    r'\uFF02\uFF1A\uFF1F:+?%\s]',
                    '', cleaned
                ).strip()
                if TITLE_MIN <= len(cleaned) <= TITLE_MAX:
                    logger.info(f"Auto-cleaned short title: {cleaned!r}")
                    short_title_clean = cleaned
                else:
                    logger.warning(f"Cleaned title invalid (len={len(cleaned)}), skipping.")
                    short_title_clean = None

            if short_title_clean:
                logger.info(f"Setting short title: {short_title_clean!r} (len={len(short_title_clean)})")
                page.wait_for_timeout(2000)

                # DOM selector 来自真实 WeChat HTML: placeholder="概括视频主要内容，字数建议6-16个字符"
                # 组件 class: .post-short-title-wrap > mp-input > input
                filled = False
                for loc in [
                    page.locator("input[placeholder*='概括视频主要内容']"),
                    page.locator("input[placeholder*='6-16']"),
                    page.locator("input[placeholder*='短标题']"),
                    page.locator(".post-short-title-wrap input"),
                    page.locator("text=短标题").locator("xpath=..").locator("input, textarea"),
                ]:
                    try:
                        if loc.count() > 0 and loc.first.is_visible():
                            loc.first.fill(short_title_clean)
                            loc.first.blur()  # 触发 handleBlur → 字数验证
                            page.wait_for_timeout(500)
                            logger.info("Short title set via placeholder locator.")
                            filled = True
                            break
                    except Exception:
                        continue

                if not filled:
                    logger.warning("Trying JS injection for short title...")
                    result = page.evaluate(
                        """(v) => {
                            const el = document.querySelector(
                                'input[placeholder*="概括视频主要内容"],'
                                'input[placeholder*="6-16"],'
                                'input[placeholder*="短标题"]'
                            );
                            if (!el) return null;
                            const setter = Object.getOwnPropertyDescriptor(
                                HTMLInputElement.prototype, 'value'
                            )?.set;
                            setter?.call(el, v);
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.blur();
                            return el.value;
                        }""",
                        short_title_clean
                    )
                    if result:
                        logger.info(f"Short title set via JS injection: {result!r}")
                    else:
                        logger.warning("All short title strategies failed — skipping.")

        # ── 5. 封面上传 ───────────────────────────────────────────────────────
        # [Claude_Sonnet_4.6_Thinking_fast] 修复 Bug1/Bug2/Bug3：
        # 真实 UI 流程：Hover 缩略图 → 浮现"编辑"按钮 → 点击"编辑" → Modal 内点"上传封面"
        # → set_input_files 注入文件 → 等待上传完成 → 点"确定"确认应用封面
        if cover_abs:
            logger.info(f"Uploading cover: {cover_abs}")
            cover_set = False

            # ── Strategy A: 直接 Hover 封面缩略图，等"编辑"按钮浮现后点击（正确流程）──
            try:
                cover_card_sels = [
                    "text=个人主页卡片",
                    "text=分享卡片",
                    "text=封面预览",
                ]
                for card_sel in cover_card_sels:
                    try:
                        card_container = page.locator(card_sel).locator("xpath=..")
                        if card_container.count() == 0:
                            continue
                        card_container.first.hover()
                        page.wait_for_timeout(1000)

                        edit_btn = card_container.first.locator("text=编辑")
                        if edit_btn.count() == 0:
                            edit_btn = card_container.first.locator("xpath=..").locator("text=编辑")
                        if edit_btn.count() == 0:
                            continue

                        logger.info(f"Found 编辑 button under: {card_sel}. Clicking...")
                        edit_btn.first.click(force=True)
                        page.wait_for_timeout(2000)

                        # Step 1: 点击"上传封面"，触发 WeChat 创建隐藏 input
                        upload_btn = None
                        for inner_sel in ["text=上传封面", "text=本地上传", ".upload-btn", ".cover-upload"]:
                            try:
                                inner_loc = page.locator(inner_sel).last
                                if inner_loc.count() > 0 and inner_loc.is_visible():
                                    upload_btn = inner_loc
                                    logger.info(f"Found upload trigger: {inner_sel}")
                                    break
                            except Exception:
                                continue

                        if upload_btn:
                            upload_btn.click(force=True)
                            page.wait_for_timeout(1500)

                        # Step 2: 注入文件到 hidden input[type=file]
                        file_injected = False
                        for input_sel in [
                            ".edit-cover-dialog-container input[type=\'file\']",
                            "input[type=\'file\'][accept*=\'image\']",
                            "input[type=\'file\']",
                        ]:
                            try:
                                file_input = page.locator(input_sel).last
                                if file_input.count() > 0:
                                    file_input.set_input_files(cover_abs)
                                    logger.info(f"Cover file injected via hidden input: {input_sel}")
                                    file_injected = True
                                    break
                            except Exception:
                                continue

                        if not file_injected:
                            logger.warning("Direct input injection failed, trying expect_file_chooser...")
                            try:
                                with page.expect_file_chooser(timeout=8000) as fc_info:
                                    if upload_btn:
                                        upload_btn.click(force=True)
                                    else:
                                        edit_btn.first.click(force=True)
                                fc_info.value.set_files(cover_abs)
                                file_injected = True
                                logger.info("Cover file set via OS file chooser.")
                            except Exception as fc_err:
                                logger.error(f"File chooser fallback also failed: {fc_err}")
                                raise

                        # Step 3: 等待上传完成
                        page.wait_for_timeout(5000)
                        page.screenshot(path="output/debug_cover_before_confirm.png")

                        # Step 4: 轮询等待"确认"按钮变为可点击状态，然后点击
                        # [Claude_Sonnet_4.6_Thinking_planning] P0 根因修复:
                        # 封面图上传后，微信需要几秒钟处理图片，期间"确认"按钮处于disabled状态
                        # 必须循环等待按钮从disabled变为enabled，而不是静态等待5秒就直接找
                        confirmed = False
                        logger.info("Polling for enabled confirm button in cover dialog (max 20s)...")

                        for poll_attempt in range(20):  # 最多等20秒
                            page.wait_for_timeout(1000)
                            # 用最直接的全局选择器: button:has-text('确认')
                            # 不限定在 dialog 容器内，因为微信的弹窗不一定有标准的 dialog role
                            for btn_name in ["确认", "确定", "完成"]:
                                # 策略1: 直接全局找 button 标签
                                btns = page.locator(f"button:has-text('{btn_name}')")
                                count = btns.count()
                                for i in range(count):
                                    try:
                                        btn = btns.nth(i)
                                        if not btn.is_visible():
                                            continue
                                        # 检查是否 disabled: 属性存在且不为 None 则跳过
                                        disabled_attr = btn.get_attribute("disabled")
                                        if disabled_attr is not None:
                                            logger.info(f"  [poll {poll_attempt}] button '{btn_name}' still disabled, waiting...")
                                            continue
                                        # 额外检查: aria-disabled
                                        if btn.get_attribute("aria-disabled") == "true":
                                            continue
                                        # 确认按钮可用，人类化点击（避免 isTrusted=false 检测）
                                        ok = human_click(page, btn)
                                        if not ok:
                                            ok = dispatch_human_click_events(page, btn)
                                        if not ok:
                                            try:
                                                btn.evaluate("node => node.click()")
                                                ok = True
                                            except Exception:
                                                pass
                                        if ok:
                                            logger.info(f"[Strategy A] Cover confirmed via human_click '{btn_name}' poll={poll_attempt}")
                                            confirmed = True
                                            break
                                    except Exception as click_err:
                                        logger.warning(f"  click error: {click_err}")
                                if confirmed:
                                    break
                            if confirmed:
                                break

                        if not confirmed:
                            logger.warning("Cover confirm button not found after 20s polling — cover may not be applied!")
                            page.screenshot(path="output/debug_cover_failed_confirm.png")
                        else:
                            page.wait_for_timeout(2000)
                            page.screenshot(path="output/debug_cover_after_confirm.png")
                            cover_set = True
                        break  # 成功处理一张卡片即退出循环
                    except Exception as e_card:
                        logger.warning(f"Cover strategy A failed for card \'{card_sel}\': {e_card}")
                        continue
            except Exception as e_a:
                logger.warning(f"Cover Strategy A (hover+edit) failed: {e_a}")

            # ── Strategy B: 兜底 — 暴力枚举常见上传 selector ──
            if not cover_set:
                logger.info("Cover Strategy B: brute-force selector search...")
                try:
                    for sel in [
                        "text=修改封面", "text=更换封面", "text=设置封面",
                        "button:has-text('修改封面')", "button:has-text('更换封面')",
                        ".cover-upload-btn",
                    ]:
                        try:
                            loc = page.locator(sel).first
                            if loc.count() > 0 and loc.is_visible():
                                with page.expect_file_chooser(timeout=8000) as fc_info:
                                    human_click(page, loc)  # 人类化点击打开文件选择器
                                fc_info.value.set_files(cover_abs)
                                page.wait_for_timeout(5000)
                                # [Claude_Sonnet_4.6_Thinking_fast] P0: 严格在 dialog 内找确认按钮，不误点"保存草稿"
                                # [Claude_Sonnet_4.6_Thinking_planning] 同 Strategy A，轮询等待按钮
                                for poll_attempt in range(20):
                                    page.wait_for_timeout(1000)
                                    for btn_name in ["确认", "确定", "完成"]:
                                        btns = page.locator(f"button:has-text('{btn_name}')")
                                        for i in range(btns.count()):
                                            try:
                                                btn = btns.nth(i)
                                                if not btn.is_visible():
                                                    continue
                                                if btn.get_attribute("disabled") is not None:
                                                    continue
                                                if btn.get_attribute("aria-disabled") == "true":
                                                    continue
                                                ok = human_click(page, btn)
                                                if not ok:
                                                    ok = dispatch_human_click_events(page, btn)
                                                if not ok:
                                                    try: btn.evaluate("node => node.click()"); ok = True
                                                    except Exception: pass
                                                if ok:
                                                    logger.info(f"[Strategy B] Cover confirmed via human_click '{btn_name}' attempt={poll_attempt}")
                                                    cover_set = True
                                                    break
                                            except Exception:
                                                pass
                                        if cover_set:
                                            break
                                    if cover_set:
                                        break
                                if cover_set:
                                    logger.info(f"[Strategy B] Cover set via selector: {sel}")
                                    break
                        except Exception:
                            continue

                except Exception as e_b:
                    logger.warning(f"Cover Strategy B failed: {e_b}")

            if not cover_set:
                logger.warning("All cover upload strategies failed — publishing without custom cover.")

        # ── 6. 原创声明 ───────────────────────────────────────────────────────
        logger.info("Checking original declaration checkbox...")
        # ═══════════════════════════════════════════════════════════════════════════
        # [Claude_Sonnet_4.6_Thinking_planning] v2.0 抗 UI 变化架构
        # 核心原则:
        #   1. 文字定位优先 (text walker) — CSS class 会变，文字内容相对稳定
        #   2. 逐层降级 (Tier 1→2→3) — 每一层都独立完整，不依赖上一层
        #   3. 轮询等待 — 永远不假设 UI 状态，等待后再检查
        #   4. 截图 + 日志 — 任何失败都留下证据
        #
        # 流程:
        #   Step A: 找到并点击"声明原创"toggle/switch/行
        #   Step B: 检测"原创权益"确认弹窗 (可能弹出)
        #   Step C: 弹窗内 (1)勾选"我已阅读" checkbox → (2)等"声明原创"按钮变蓝 → (3)点击
        # ═══════════════════════════════════════════════════════════════════════════

        def _click_original_toggle(page) -> bool:
            """Step A: 点击主界面上的原创声明 toggle。返回是否成功。"""
            # 策略 1: CSS 选择器（最快，但可能因 UI 变化失效）
            css_selectors = [
                "label:has-text('原创') input[type='checkbox']",
                "label:has-text('声明原创') input[type='checkbox']",
                "input[type='checkbox'][class*='original']",
                ".original-declaration input",
                "input[type='checkbox']:near(:text('原创'))",
                "input[type='checkbox']:near(:text('声明原创'))",
                ".weui-desktop-switch:near(:text('原创'))",
                ".weui-desktop-switch:near(:text('声明原创'))",
            ]
            for sel in css_selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if 'checkbox' in sel:
                            if not loc.first.is_checked():
                                human_click(page, loc.first)
                        else:
                            human_click(page, loc.first)
                        logger.info(f"[Original-ToggleA] human_click via: {sel}")
                        return True
                except Exception:
                    pass

            # 策略 2: JS 文字遍历 (抗 CSS 变化)
            result = page.evaluate("""() => {
                const targets = ['声明原创', '原创声明', '原创'];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    const txt = node.textContent.trim();
                    if (!targets.includes(txt)) continue;
                    let el = node.parentElement;
                    for (let i = 0; i < 8 && el; i++) {
                        // 找 input[type=checkbox]
                        const cb = el.querySelector('input[type="checkbox"]');
                        if (cb && !cb.checked) { cb.click(); return {ok:true, method:'cb', cls:cb.className}; }
                        // 找 role=switch
                        const sw = el.querySelector('[role="switch"]');
                        if (sw) { sw.click(); return {ok:true, method:'role-switch', cls:sw.className}; }
                        // 找 class 含 switch/toggle 的元素
                        const toggleEl = el.querySelector('[class*="switch"],[class*="toggle"],[class*="Switch"],[class*="Toggle"]');
                        if (toggleEl) { toggleEl.click(); return {ok:true, method:'cls-toggle', cls:toggleEl.className}; }
                        // 最后兜底: 整行可点击
                        if (el.tagName === 'LABEL' || el.getAttribute('role') === 'button') {
                            el.click(); return {ok:true, method:'row-click', cls:el.className};
                        }
                        el = el.parentElement;
                    }
                }
                return {ok:false};
            }""")
            if result and result.get('ok'):
                logger.info(f"[Original-ToggleA] JS text-walker click: {result}")
                return True

            logger.warning("[Original-ToggleA] All strategies failed — toggle not found")
            return False

        def _handle_original_rights_dialog(page) -> bool:
            """Step B+C: 处理"原创权益"二次确认弹窗。
            流程: 检测弹窗 -> 勾选 checkbox -> 等待"声明原创"按钮变蓝 -> 点击。

            # [Claude_Sonnet_4.6_Thinking_planning] v4.0 策略库架构:
            # 设计原则: 永不丢弃历史策略，只做累积。微信可能在不同版本/设备上
            # 切换 UI 方案，历史策略随时可能重新适用。
            # CHECKBOX_STRATEGIES = 所有已知方案的有序列表，逐一尝试，
            # 以"声明原创"按钮变 enabled 作为 checkbox 已勾选的唯一客观验证。
            """
            # ── 检测弹窗 (最多等4秒) ────────────────────────────────────────────
            dialog_detected = False
            for _ in range(8):
                page.wait_for_timeout(500)
                # [Gemini_3.5_Flash_High_planning] 优先使用 Playwright 自动穿透 Shadow DOM 的定位机制进行检测
                try:
                    # 查找可见的且包含“原创权益”的文本节点或元素
                    loc = page.locator("text=原创权益").first
                    if loc.count() > 0 and loc.is_visible(timeout=100):
                        dialog_detected = True
                        logger.info("[Original-Dialog] '原创权益' dialog detected via Playwright locator")
                        page.screenshot(path="output/debug_dialog_detected.png")
                        break
                except Exception:
                    pass

                # [Gemini_3.5_Flash_High_planning] 备选：递归穿透所有 Shadow DOM 进行深度遍历检测
                found_js = page.evaluate("""() => {
                    function findTextDeep(root) {
                        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                        let node;
                        while (node = walker.nextNode()) {
                            const t = node.textContent.trim();
                            if (t === '原创权益' || t.includes('原创权益')) {
                                const el = node.parentElement;
                                if (el && el.offsetParent !== null) return true;
                            }
                        }
                        const all = root.querySelectorAll('*');
                        for (const el of all) {
                            if (el.shadowRoot) {
                                if (findTextDeep(el.shadowRoot)) return true;
                            }
                        }
                        return false;
                    }
                    return findTextDeep(document.body);
                }""")
                if found_js:
                    dialog_detected = True
                    logger.info("[Original-Dialog] '原创权益' dialog detected via Deep JS search")
                    page.screenshot(path="output/debug_dialog_detected.png")
                    break

            if not dialog_detected:
                logger.info("[Original-Dialog] No dialog -- toggle direct, no confirmation needed")
                return True

            page.wait_for_timeout(1000)  # 等动画结束

            # ── 客观验证: 声明原创按钮是否 enabled ────────────────────────────
            def _is_declare_btn_enabled():
                """以"声明原创"按钮从 disabled->enabled 作为 checkbox 已勾选的验证
                # [Gemini_3.5_Flash_High_planning] 挂载 weui-desktop-btn_disabled 类名判定微前端场景下的禁用状态"""
                for btn_text in ["\u58f0\u660e\u539f\u521b", "\u786e\u5b9a"]:
                    try:
                        btns = page.locator(f"button:has-text('{btn_text}')")
                        for i in range(btns.count()):
                            btn = btns.nth(i)
                            if not btn.is_visible():
                                continue
                            cls = btn.get_attribute("class") or ""
                            # [Gemini_3.5_Flash_High_planning] 校验 disabled 属性、aria-disabled 以及 class 中的禁用类
                            if (btn.get_attribute("disabled") is None and
                                    btn.get_attribute("aria-disabled") != "true" and
                                    "disabled" not in cls.lower() and
                                    "weui-desktop-btn_disabled" not in cls):
                                return True, btn
                    except Exception:
                        pass
                return False, None

            # ── CHECKBOX_STRATEGIES: 所有已知 UI 方案的策略库 ─────────────────
            # 规则: 永不删除，只追加。每个策略返回 True/False 表示是否成功触发点击。
            # 验证由外层统一做 (_is_declare_btn_enabled)，与策略解耦。

            def _s1_native_input_css(page):
                """S1 (v2.0遗留): 标准 input[type=checkbox] CSS 选择器
                适用: 微信使用原生 HTML checkbox 的版本"""
                for sel in [
                    ".weui-desktop-dialog input[type='checkbox']",
                    ".weui-desktop-dialog__bd input[type='checkbox']",
                    "div[role='dialog'] input[type='checkbox']",
                    "input[type='checkbox']:near(:text('\u9605\u8bfb'))",
                    "input[type='checkbox']:near(:text('\u540c\u610f'))",
                    "input[type='checkbox']",  # 页内唯一 checkbox 兜底
                ]:
                    try:
                        cb = page.locator(sel)
                        if cb.count() > 0 and cb.first.is_visible(timeout=300):
                            if cb.first.is_checked():
                                logger.info(f"[S1] Already checked via {sel}")
                                return True
                            ok = human_check(page, cb.first)
                            if ok:
                                logger.info(f"[S1] native input checked via: {sel}")
                                return True
                    except Exception:
                        pass
                return False

            def _s2_label_has_text(page):
                """S2 (v3.0): 点击包含'阅读'文字的 label 标签
                适用: 微信将 checkbox+文字 包在 label 内的版本"""
                for text_kw in ["\u6211\u5df2\u9605\u8bfb\u5e76\u540c\u610f",
                                "\u6211\u5df2\u9605\u8bfb", "\u9605\u8bfb\u5e76\u540c\u610f",
                                "\u9605\u8bfb", "\u540c\u610f"]:
                    for sel in [
                        f"label:has-text('{text_kw}')",
                        f".weui-desktop-dialog label:has-text('{text_kw}')",
                        f"[role='dialog'] label:has-text('{text_kw}')",
                        ".weui-desktop-dialog label",
                        "div[role='dialog'] label",
                    ]:
                        try:
                            loc = page.locator(sel).first
                            if loc.count() > 0 and loc.is_visible(timeout=300):
                                ok = human_click(page, loc)
                                if ok:
                                    logger.info(f"[S2] label clicked: {sel}")
                                    return True
                        except Exception:
                            pass
                return False

            def _s3_js_coord_click(page):
                """S3 (v3.0): JS 找'阅读'文字节点 -> BoundingRect -> 鼠标坐标点击
                适用: 自定义组件无法被 Playwright 选择器找到，但坐标可用"""
                rect = page.evaluate("""() => {
                    const keys = ['\u6211\u5df2\u9605\u8bfb\u5e76\u540c\u610f',
                                  '\u6211\u5df2\u9605\u8bfb', '\u9605\u8bfb\u5e76\u540c\u610f',
                                  '\u9605\u8bfb'];
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while (node = walker.nextNode()) {
                        const t = node.textContent.trim();
                        if (keys.some(k => t.includes(k))) {
                            let el = node.parentElement;
                            for (let i = 0; i < 6 && el; i++) {
                                if (el.offsetParent !== null) {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) {
                                        return {x: r.left + 8, y: r.top + r.height / 2,
                                                text: t.slice(0, 30)};
                                    }
                                }
                                el = el.parentElement;
                            }
                        }
                    }
                    return null;
                }""")
                if rect:
                    import random as _rand
                    cx = rect["x"] + _rand.uniform(1, 6)
                    cy = rect["y"] + _rand.uniform(-2, 2)
                    page.mouse.move(cx, cy)
                    page.wait_for_timeout(120)
                    page.mouse.click(cx, cy)
                    logger.info(f"[S3] coord click ({cx:.0f},{cy:.0f}) '{rect.get('text','')}'")
                    return True
                return False

            def _s4_class_enum_in_container(page):
                """S4 (v3.0): 在弹窗容器内枚举所有 checkbox 类元素并点击
                适用: class 名含'checkbox'的自定义组件版本"""
                result = page.evaluate("""() => {
                    const kw = '\u539f\u521b\u6743\u76ca';
                    const dialogs = [...document.querySelectorAll(
                        '[class*="dialog"],[class*="Dialog"],[class*="modal"],[role="dialog"]'
                    )].filter(el => el.offsetParent !== null && el.innerText.includes(kw));
                    const container = dialogs[0] || document.body;
                    const candidates = container.querySelectorAll(
                        'input[type="checkbox"],[class*="checkbox"],[class*="check-box"],' +
                        '[class*="Checkbox"],[role="checkbox"]'
                    );
                    for (const el of candidates) {
                        if (el.offsetParent === null) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        el.click();
                        return {ok:true, tag:el.tagName, cls:el.className.slice(0,50)};
                    }
                    return {ok:false};
                }""")
                if result and result.get("ok"):
                    logger.info(f"[S4] class enum click: {result}")
                    return True
                return False

            def _s5_label_in_container(page):
                """S5 (v3.0): 弹窗容器内找含'阅读'文字的 label 并点击
                适用: label 不被 :has-text 找到但在容器内可枚举的版本"""
                result = page.evaluate("""() => {
                    const kw = '\u539f\u521b\u6743\u76ca';
                    const dialogs = [...document.querySelectorAll(
                        '[class*="dialog"],[class*="Dialog"],[class*="modal"],[role="dialog"]'
                    )].filter(el => el.offsetParent !== null && el.innerText.includes(kw));
                    const container = dialogs[0] || document.body;
                    const labels = container.querySelectorAll('label');
                    for (const lb of labels) {
                        if (lb.offsetParent !== null &&
                            (lb.innerText.includes('\u9605\u8bfb') || lb.innerText.includes('\u540c\u610f'))) {
                            lb.click();
                            return {ok:true, text:lb.innerText.slice(0,40)};
                        }
                    }
                    return {ok:false};
                }""")
                if result and result.get("ok"):
                    logger.info(f"[S5] label in container: {result}")
                    return True
                return False

            def _s6_dispatch_events_on_small_element(page):
                """S6 (新增): 对弹窗内第一个小型可见元素派发完整鼠标事件序列
                适用: 自定义组件对 click() 不响应，但响应 mousedown/mouseup 的版本"""
                result = page.evaluate("""() => {
                    const kw = '\u539f\u521b\u6743\u76ca';
                    const dialogs = [...document.querySelectorAll(
                        '[class*="dialog"],[class*="Dialog"],[class*="modal"],[role="dialog"]'
                    )].filter(el => el.offsetParent !== null && el.innerText.includes(kw));
                    const container = dialogs[0] || document.body;
                    // 找宽高 < 30px 的小元素 (通常是 checkbox 图标)
                    const all = container.querySelectorAll('*');
                    for (const el of all) {
                        if (el.offsetParent === null) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width > 5 && r.width <= 28 && r.height > 5 && r.height <= 28) {
                            return {ok:true, x: r.left + r.width/2, y: r.top + r.height/2,
                                    tag: el.tagName, cls: el.className.slice(0,40)};
                        }
                    }
                    return {ok:false};
                }""")
                if result and result.get("ok"):
                    import random as _rand
                    cx = result["x"] + _rand.uniform(-2, 2)
                    cy = result["y"] + _rand.uniform(-1, 1)
                    # 派发完整事件序列
                    page.mouse.move(cx, cy)
                    page.wait_for_timeout(80)
                    page.mouse.down()
                    page.wait_for_timeout(60)
                    page.mouse.up()
                    logger.info(f"[S6] dispatch events on small el ({cx:.0f},{cy:.0f}) {result.get('tag')} '{result.get('cls','')[:30]}'")
                    return True
                return False

            def _s7_tab_space_keyboard(page):
                """S7 (新增): 键盘 Tab + Space 触发 checkbox
                适用: 弹窗内 checkbox 获得焦点后 Space 可切换的版本"""
                try:
                    # Tab 到弹窗内元素
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(100)
                    page.keyboard.press("Space")
                    logger.info("[S7] keyboard Tab+Space fired")
                    return True
                except Exception:
                    return False

            def _s8_antd_checkbox_wrapper(page):
                """S8 (新增): 点击 .ant-checkbox-wrapper 或 .ant-checkbox-inner
                适用: 微信在微前端中使用 Ant Design Checkbox 的版本
                # [Gemini_3.5_Flash_High_planning] 能够被 Playwright pierced-shadow 机制自动识别"""
                for sel in [
                    ".ant-checkbox-wrapper",
                    ".ant-checkbox-inner",
                    "label.ant-checkbox-wrapper",
                    "span.ant-checkbox-inner",
                    ".declare-body-wrapper label",
                ]:
                    try:
                        cb = page.locator(sel).first
                        if cb.count() > 0 and cb.is_visible(timeout=300):
                            ok = human_click(page, cb)
                            if ok:
                                logger.info(f"[S8] AntD checkbox clicked via: {sel}")
                                return True
                    except Exception:
                        pass
                return False

            def _s9_antd_checkbox_force_input(page):
                """S9 (新增): 强制点击隐藏的 .ant-checkbox-input
                # [Gemini_3.5_Flash_High_planning] 强制点击隐藏 input 是 Playwright 中处理不可见原生控件的推荐方式"""
                try:
                    cb = page.locator(".ant-checkbox-input").first
                    if cb.count() > 0:
                        cb.click(force=True, timeout=500)
                        logger.info("[S9] AntD hidden input force clicked")
                        return True
                except Exception:
                    pass
                return False

            def _s10_absolute_coordinate_click(page):
                """S10 (新增): 物理坐标定位点击 (基于用户建议)
                # [Gemini_3.5_Flash_High_planning] 获取元素 bounding box 后以真实鼠标坐标点击其中心点"""
                for sel in [
                    ".ant-checkbox-wrapper",
                    ".ant-checkbox-inner",
                    "span.ant-checkbox-inner"
                ]:
                    try:
                        cb = page.locator(sel).first
                        if cb.count() > 0 and cb.is_visible(timeout=300):
                            box = cb.bounding_box()
                            if box:
                                cx = box["x"] + box["width"] / 2
                                cy = box["y"] + box["height"] / 2
                                page.mouse.move(cx, cy)
                                page.wait_for_timeout(100)
                                page.mouse.click(cx, cy)
                                logger.info(f"[S10] absolute coordinate click at ({cx:.0f},{cy:.0f}) via: {sel}")
                                return True
                    except Exception as e:
                        pass
                return False

            # 策略库（按历史可靠性和通用性排序，不删除旧策略）
            CHECKBOX_STRATEGIES = [
                ("S1_native_input_css",          _s1_native_input_css),
                ("S2_label_has_text",            _s2_label_has_text),
                ("S3_js_coord_click",            _s3_js_coord_click),
                ("S4_class_enum_in_container",   _s4_class_enum_in_container),
                ("S5_label_in_container",        _s5_label_in_container),
                ("S6_dispatch_on_small_el",      _s6_dispatch_events_on_small_element),
                ("S7_tab_space_keyboard",        _s7_tab_space_keyboard),
                ("S8_antd_checkbox_wrapper",     _s8_antd_checkbox_wrapper),
                ("S9_antd_checkbox_force_input",  _s9_antd_checkbox_force_input),
                ("S10_absolute_coordinate_click", _s10_absolute_coordinate_click),
            ]

            # ── 逐策略尝试，以按钮 enabled 为验证 ───────────────────────────
            for strategy_name, strategy_fn in CHECKBOX_STRATEGIES:
                logger.info(f"[Original-Dialog] Trying {strategy_name}...")
                try:
                    triggered = strategy_fn(page)
                except Exception as e:
                    logger.warning(f"[Original-Dialog] {strategy_name} raised: {e}")
                    triggered = False

                if not triggered:
                    logger.info(f"[Original-Dialog] {strategy_name}: no element found, skipping")
                    continue

                # 等微信响应
                page.wait_for_timeout(800)
                enabled, declare_btn = _is_declare_btn_enabled()

                if enabled:
                    logger.info(f"[Original-Dialog] \u2705 {strategy_name} succeeded! '\u58f0\u660e\u539f\u521b' now enabled")
                    # 点击"声明原创"按钮
                    ok = human_click(page, declare_btn)
                    if not ok:
                        ok = dispatch_human_click_events(page, declare_btn)
                    if not ok:
                        try:
                            declare_btn.evaluate("node => node.click()")
                            ok = True
                        except Exception:
                            pass
                    if ok:
                        logger.info("[Original-Dialog] \u2705 '\u58f0\u660e\u539f\u521b' button clicked!")
                        page.wait_for_timeout(1000)
                        return True
                    else:
                        logger.warning(f"[Original-Dialog] {strategy_name}: button enabled but click failed, continuing...")
                else:
                    logger.warning(f"[Original-Dialog] {strategy_name}: triggered but button still disabled — UI variant mismatch")
                    page.screenshot(path=f"output/debug_dialog_{strategy_name}_fail.png")

            logger.warning("[Original-Dialog] All 7 strategies exhausted — checkbox could not be activated")
            page.screenshot(path="output/debug_original_dialog_fail.png")
            return False

        # ── 执行原创声明流程 ───────────────────────────────────────────────────
        page.screenshot(path="output/debug_original_before.png")

        toggle_ok = _click_original_toggle(page)
        if toggle_ok:
            dialog_ok = _handle_original_rights_dialog(page)
            if dialog_ok:
                logger.info("✅ Original declaration completed successfully")
            else:
                logger.warning("⚠️ Original declaration dialog handling failed — proceeding anyway")
        else:
            logger.warning("⚠️ Original declaration toggle not found — proceeding anyway")

        page.screenshot(path="output/debug_original_after.png")

        # ── 7. 分类选择 (已弃用) ──────────────────────────────────────────────────────
        if category:
            logger.info(f"Category logic skipped. WeChat Web UI no longer supports category selectors. Relying on hashtags for {category!r}.")
            
        # ── 8. 合集选择与新建 ───────────────────────────────────────────────────
        if collection:
            _select_collection(page, collection)

        # ── 9. 发表前清理残留遮罩 ────────────────────────────────────────────────
        # [Claude_Sonnet_4.6_Thinking_planning] v2.0.0 bugfix:
        # 合集创建流程可能留下未关闭的 .weui-desktop-dialog__wrp，会拦截「发表」按钮点击
        try:
            overlay = page.locator(".weui-desktop-dialog__wrp").first
            if overlay.count() > 0 and overlay.is_visible():
                logger.warning("Detected open dialog overlay before publish — pressing Escape to dismiss.")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
        except Exception:
            pass
            
        # 5. 执行提交或存草稿
        if draft:
            logger.info("Saving as draft...")
            draft_btn = page.locator("button:has-text('保存草稿')").first
            if draft_btn.count() == 0:
                draft_btn = page.locator("button:has-text('存草稿')").first
                
            if draft_btn.count() > 0:
                draft_btn.click()
                logger.info("Clicked Save Draft button.")
            else:
                logger.warning("Save Draft button not found. Falling back to Publish.")
                page.locator("button:has-text('发表')").first.click()
        else:
            logger.info("Publishing post...")
            publish_btn = page.locator("button:has-text('发表')").first
            if publish_btn.count() > 0:
                publish_btn.click()
                logger.info("Clicked Publish button.")
            else:
                logger.error("Publish button not found!")
                browser.close()
                return 1
                
        # 6. 确认发布/保存成功
        page.wait_for_timeout(5000)
        try:
            # 成功发布后视频号网页通常跳转到 /post/list
            page.wait_for_url("**/post/list**", timeout=15000)
            logger.info("Confirmed: Successfully navigated to post list. Publish complete.")
        except Exception:
            # 降级通过页面文本判断
            content = page.content()
            if "成功" in content or "发表成功" in content or "保存成功" in content:
                logger.info("Confirmed: Success message found in page content.")
            else:
                logger.warning("Could not confirm success via URL redirect or page content. Please double check manually.")
                
        browser.close()
        return 0

def main():
    parser = argparse.ArgumentParser(description="Upload and publish videos to WeChat Channels.")
    parser.add_argument("--video",         help="Path to vertical MP4 video file")
    parser.add_argument("--copy",          help="Path to WeChat copy description text file")
    parser.add_argument("--title-file",    help="Path to short title text file (6-16 chars, WeChat platform limit)")
    parser.add_argument("--cover",         help="Path to cover image JPEG file")
    parser.add_argument("--category-file", help="Path to category text file")
    parser.add_argument("--collection",    help="Custom collection/playlist name to associate with this video")
    parser.add_argument("--state",  default="output/wechat_state.json",
                        help="Path to save/load Playwright session state")
    parser.add_argument("--login-only",  action="store_true")
    parser.add_argument("--no-headless", dest="headless", action="store_false")
    parser.add_argument("--draft",       action="store_true")
    parser.set_defaults(headless=True)
    args = parser.parse_args()

    code = run_uploader(
        video_path    = args.video,
        copy_path     = args.copy,
        title_path    = args.title_file,
        cover_path    = args.cover,
        category_path = args.category_file,
        state_path    = args.state,
        login_only    = args.login_only,
        headless      = args.headless,
        draft         = args.draft,
        collection    = args.collection,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()

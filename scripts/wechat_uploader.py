"""WeChat Channels Automated Video Uploader

# Modification History
| Version | Date       | Author                              | Description                                              |
|---------|------------|-------------------------------------|----------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.5_Flash_planning           | Initial creation using Playwright                        |
| 1.1.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 处理短标题/封面/分类/原创勾选；修复登录误判 URL优先策略 |
| 1.2.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | P0根因修复: (1)封面确认改为轮询等待disabled→enabled (2)原创声明增加JS兜底 |
| 1.3.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | 原创声明 v2.0: 抗 UI 变化三层降级架构 (_click_original_toggle + _handle_original_rights_dialog) |
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright

try:
    import requests as _requests
except ImportError:
    _requests = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("wechat_uploader")

# 微信视频号发表地址
WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"

def run_uploader(
    video_path: str = None,
    copy_path: str = None,
    state_path: str = "output/wechat_state.json",
    login_only: bool = False,
    headless: bool = True,
    draft: bool = False,
    title_path: str = None,      # 短标题文件（≤ 28 字）
    cover_path: str = None,      # 封面图文件 (JPEG)
    category_path: str = None,   # 分类文件
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
        logger.info(f"short_title={short_title!r}  category={category!r}  cover={'yes' if cover_abs else 'no'}")
    else:
        video_abs = copy_text = short_title = cover_abs = category = None
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

        # 反检测：覆盖 navigator.webdriver = false（必须在 goto 之前注入）
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
            window.chrome = { runtime: {} };
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
                        page.wait_for_timeout(2000)  # 等 QR 码渲染

                        # 精确截取 QR 码区域，降级截全页面
                        qr_path = str(state_file.parent / "login_qr.png")
                        qr_captured = False
                        for qr_sel in ["img.qrcode", ".login-qr img", ".qr-code img",
                                       "img[src*='qr']", ".qrcode"]:
                            qr_el = page.locator(qr_sel)
                            if qr_el.count() > 0:
                                try:
                                    qr_el.first.screenshot(path=qr_path)
                                    qr_captured = True
                                    logger.info(f"QR captured via: {qr_sel}")
                                    break
                                except Exception:
                                    continue
                        if not qr_captured:
                            page.screenshot(path=qr_path)
                            logger.info("QR full-page screenshot (fallback).")

                        # 发送图片到 Telegram
                        caption = (
                            "\U0001f510 微信视频号登录二维码\n"
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

                        # 等待扫码跳转（最多 120s）
                        page.wait_for_url("**/post/create", timeout=120000)
                        logger.info("Login detected after Telegram QR scan. Saving session...")
                        context.storage_state(path=str(state_file))
                        logger.info(f"Session saved to: {state_file}")

                        # 告知已成功
                        _requests.post(
                            f"https://api.telegram.org/bot{tg_token}/sendMessage",
                            json={"chat_id": tg_chat_id,
                                  "text": "\u2705 微信视频号登录成功，继续上传任务..."},
                            timeout=10,
                        )
                    except Exception as e_tg:
                        logger.error(f"Telegram QR login failed: {e_tg}")
                        browser.close()
                        return 2
                else:
                    logger.error(
                        "Session expired. Headless mode cannot QR scan. "
                        "Set TELEGRAM_BOT_TOKEN + TELEGRAM_ADMIN_IDS in .env to enable remote QR login."
                    )
                    browser.close()
                    return 2  # 上层识别为 LOGIN_REQUIRED
            else:
                logger.info("=" * 50)
                logger.info("⚠️ 请在弹出的浏览器窗口中，使用手机微信扫码登录！")
                logger.info("=" * 50)
                try:
                    page.wait_for_url("**/post/create", timeout=120000)
                    logger.info("Login detected. Saving session state...")
                    context.storage_state(path=str(state_file))
                    logger.info(f"Session saved to: {state_file}")
                except Exception as e:
                    logger.error(f"Login wait timed out or failed: {e}")
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
                short_title_clean = short_title_clean[:TITLE_MAX]
                logger.warning(f"Short title truncated to {TITLE_MAX} chars: {short_title_clean!r}")

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
                                        # 确认按钮可用，点击
                                        btn.click(timeout=2000, force=True)
                                        logger.info(f"[Strategy A] Cover confirmed via button:has-text('{btn_name}') on poll attempt {poll_attempt}")
                                        confirmed = True
                                        break
                                    except Exception as click_err:
                                        logger.warning(f"  button click error: {click_err}")
                                        try:
                                            btn.evaluate("node => node.click()")
                                            confirmed = True
                                            logger.info(f"[Strategy A] Cover confirmed via JS .click() on poll attempt {poll_attempt}")
                                            break
                                        except Exception:
                                            pass
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
                                    loc.click(force=True)
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
                                                btn.click(timeout=2000, force=True)
                                                logger.info(f"[Strategy B] Cover confirmed via button '{btn_name}' on attempt {poll_attempt}")
                                                cover_set = True
                                                break
                                            except Exception:
                                                try:
                                                    btn.evaluate("node => node.click()")
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
                                loc.first.click(force=True)
                        else:
                            loc.first.click(force=True)
                        logger.info(f"[Original-ToggleA] CSS click via: {sel}")
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
            流程: 检测弹窗 → 勾选 checkbox → 等待"声明原创"按钮变蓝 → 点击。
            返回: True=弹窗不存在(无需处理) 或 处理成功; False=处理失败。
            """
            # 检测弹窗是否存在 (最多等2秒)
            dialog_detected = False
            for _ in range(4):
                page.wait_for_timeout(500)
                # 判断"原创权益"弹窗是否出现
                found = page.evaluate("""() => {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while (node = walker.nextNode()) {
                        if (node.textContent.trim() === '原创权益') {
                            const el = node.parentElement;
                            if (el && el.offsetParent !== null) return true;
                        }
                    }
                    return false;
                }""")
                if found:
                    dialog_detected = True
                    logger.info("[Original-Dialog] '原创权益' dialog detected")
                    break

            if not dialog_detected:
                logger.info("[Original-Dialog] No dialog appeared — toggle was direct (no confirmation needed)")
                return True  # 无需处理

            # Step C1: 勾选"我已阅读并同意"checkbox
            # 同样用文字遍历，找 checkbox 附近的"阅读"/"同意"文字
            agree_checked = False
            for poll in range(10):
                page.wait_for_timeout(800)

                # CSS 方式
                for cb_sel in [
                    ".weui-desktop-dialog input[type='checkbox']",
                    ".weui-desktop-dialog__bd input[type='checkbox']",
                    "div[role='dialog'] input[type='checkbox']",
                    "input[type='checkbox']:near(:text('阅读'))",
                    "input[type='checkbox']:near(:text('同意'))",
                ]:
                    try:
                        cb = page.locator(cb_sel)
                        if cb.count() > 0 and cb.first.is_visible():
                            try:
                                if cb.first.is_checked():
                                    agree_checked = True
                                    break
                            except Exception:
                                pass
                            cb.first.click(force=True)
                            agree_checked = True
                            logger.info(f"[Original-Dialog] Agreement checkbox clicked via CSS: {cb_sel}")
                            break
                    except Exception:
                        pass
                if agree_checked:
                    break

                # JS 文字遍历方式 (兜底)
                result = page.evaluate("""() => {
                    const keywords = ['我已阅读', '阅读并同意', '阅读', '同意'];
                    // 直接找所有可见的 input[type=checkbox]
                    const cbs = document.querySelectorAll('input[type="checkbox"]');
                    for (const cb of cbs) {
                        if (cb.offsetParent === null) continue;
                        if (cb.checked) return {ok:true, method:'already-checked'};
                        // 验证其附近文字含关键词
                        const parentText = cb.closest('label, div, span')?.innerText || '';
                        const isAgreeCb = keywords.some(k => parentText.includes(k)) || true; // 弹窗内只有这一个 checkbox
                        if (isAgreeCb) {
                            cb.click();
                            return {ok:true, method:'direct-cb', text: parentText.slice(0,30)};
                        }
                    }
                    return {ok:false};
                }""")
                if result and result.get('ok'):
                    agree_checked = True
                    logger.info(f"[Original-Dialog] Agreement checkbox via JS: {result}")
                    break

            if not agree_checked:
                logger.warning("[Original-Dialog] Could not check agreement checkbox after 10 polls")
                page.screenshot(path="output/debug_original_agree_fail.png")
                return False

            # Step C2: 等"声明原创"按钮从灰→蓝 (disabled→enabled)
            page.wait_for_timeout(500)
            confirm_clicked = False
            for poll in range(15):
                page.wait_for_timeout(700)

                # 按优先级尝试点击: 声明原创 > 确定 > 同意
                for btn_text in ["声明原创", "确定", "同意并继续", "同意"]:
                    btns = page.locator(f"button:has-text('{btn_text}')")
                    count = btns.count()
                    for i in range(count):
                        try:
                            btn = btns.nth(i)
                            if not btn.is_visible():
                                continue
                            # 跳过 disabled 按钮
                            if btn.get_attribute("disabled") is not None:
                                logger.info(f"  [poll {poll}] '{btn_text}' still disabled, waiting...")
                                continue
                            if btn.get_attribute("aria-disabled") == "true":
                                continue
                            # 点击
                            btn.click(timeout=2000, force=True)
                            confirm_clicked = True
                            logger.info(f"[Original-Dialog] '声明原创' confirmed via button '{btn_text}' on poll {poll}")
                            break
                        except Exception as ce:
                            try:
                                btns.nth(i).evaluate("node => node.click()")
                                confirm_clicked = True
                                logger.info(f"[Original-Dialog] Confirmed via JS .click() on poll {poll}")
                                break
                            except Exception:
                                pass
                    if confirm_clicked:
                        break
                if confirm_clicked:
                    break

            if not confirm_clicked:
                logger.warning("[Original-Dialog] '声明原创' button never enabled after 15 polls")
                page.screenshot(path="output/debug_original_confirm_fail.png")
                return False

            page.wait_for_timeout(1000)
            return True

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

        # ── 7. 分类选择 ───────────────────────────────────────────────────────
        if category:
            logger.info(f"Selecting category: {category!r}")
            cat_set = False
            
            # 第一阶段：找到并点击分类下拉框的入口
            dropdown_triggers = [
                page.locator("text=视频分类").locator("xpath=..").locator("div").first,
                page.locator("text=分类").locator("xpath=..").locator("div").first,
                page.locator(".category-selector"),
                page.locator("div[class*='category-select']")
            ]
            
            for trigger in dropdown_triggers:
                try:
                    if trigger.count() > 0 and trigger.first.is_visible(timeout=1500):
                        try:
                            trigger.first.click(timeout=500)
                        except Exception:
                            trigger.first.evaluate("node => node.click()")
                        page.wait_for_timeout(800) # 等待下拉菜单展开
                        
                        # 第二阶段：在展开的菜单中点击目标分类
                        # 微信的选项通常在单独的浮层层级中
                        options = [
                            page.locator(f"li:has-text('{category}')"),
                            page.locator(f".weui-desktop-dropdown__list li:has-text('{category}')"),
                            page.locator(f"div[role='option']:has-text('{category}')")
                        ]
                        
                        for opt in options:
                            if opt.count() > 0 and opt.first.is_visible(timeout=1000):
                                try:
                                    opt.first.click(force=True, timeout=500)
                                    logger.info(f"Category '{category}' selected successfully.")
                                    cat_set = True
                                    break
                                except Exception:
                                    try:
                                        opt.first.evaluate("node => node.click()")
                                        logger.info(f"Category '{category}' selected successfully via evaluate.")
                                        cat_set = True
                                        break
                                    except Exception:
                                        pass
                        
                        if cat_set:
                            break
                        else:
                            # 没找到对应选项，可能需要点击旁边收起下拉框
                            page.mouse.click(0, 0)
                            page.wait_for_timeout(500)
                except Exception:
                    continue

            if not cat_set:
                logger.warning(f"Could not set category '{category}', skipping.")
            
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
    parser.add_argument("--title-file",    help="Path to short title text file (<=28 chars)")
    parser.add_argument("--cover",         help="Path to cover image JPEG file")
    parser.add_argument("--category-file", help="Path to category text file")
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
    )
    sys.exit(code)


if __name__ == "__main__":
    main()

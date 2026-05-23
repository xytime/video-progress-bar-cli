"""WeChat Channels Automated Video Uploader

# Modification History
| Version | Date       | Author                              | Description                                              |
|---------|------------|-------------------------------------|----------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.5_Flash_planning           | Initial creation using Playwright                        |
| 1.1.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 处理短标题/封面/分类/原创勾选；修复登录误判 URL优先策略 |
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright

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
                get: () => undefined,
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
                logger.error("Session expired or not logged in. Headless mode cannot QR scan.")
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
        if short_title:
            logger.info(f"Setting short title: {short_title!r}")
            page.wait_for_timeout(2000)
            robust_locators = [
                page.locator("input[placeholder*='短标题']"),
                page.locator("input[placeholder*='标题']"),
                page.locator("input[placeholder*='28']"),
                page.locator("textarea[placeholder*='短标题']"),
                page.locator("text=短标题").locator("xpath=..").locator("input, textarea, [contenteditable='true']"),
                page.locator(".post-title input"),
                page.locator(".header-input"),
            ]
            
            for loc in robust_locators:
                try:
                    if loc.count() > 0 and loc.first.is_visible():
                        loc.first.fill(short_title)
                        logger.info(f"Short title set via robust locator")
                        break
                except Exception:
                    continue
            else:
                logger.warning("Could not find title input via locators, trying JS evaluation...")
                # 尝试通过 JS 强行寻找相关输入框 (有些是动态组件)
                js_injected = page.evaluate('''
                    (titleText) => {
                        let elements = Array.from(document.querySelectorAll('input, textarea'));
                        let target = elements.find(el => (el.placeholder || '').includes('短标题') || (el.placeholder || '').includes('标题'));
                        if (target) {
                            target.value = titleText;
                            target.dispatchEvent(new Event('input', { bubbles: true }));
                            return true;
                        }
                        return false;
                    }
                ''', short_title)
                
                if js_injected:
                    logger.info("Short title set via JS evaluation fallback.")
                else:
                    logger.warning("Could not find title input anywhere, skipping.")

        # ── 5. 封面上传 ───────────────────────────────────────────────────────
        if cover_abs:
            logger.info(f"Uploading cover: {cover_abs}")
            cover_set = False
            try:
                # 尝试通过第二个 file input 注入 (通常第一个是视频，第二个是封面)
                inputs = page.locator("input[type='file']")
                if inputs.count() >= 2:
                    inputs.nth(1).set_input_files(cover_abs)
                    logger.info("Cover uploaded via second image file input.")
                    cover_set = True
            except Exception as e:
                pass
                
            if not cover_set:
                try:
                    # 必须先 Hover 视频预览区域，才能让“更换封面”按钮变为可见
                    preview_areas = [
                        page.locator(".video-preview").first,
                        page.locator(".post-video-preview").first,
                        page.locator(".cover-wrap").first,
                        page.locator(".form-item:has-text('封面')").first,
                        page.locator("text=封面预览").locator("xpath=..").first
                    ]
                    for pa in preview_areas:
                        if pa.count() > 0 and pa.is_visible():
                            pa.hover()
                            page.wait_for_timeout(500)
                            break
                            
                    trigger_loc = None
                    for sel in [
                        "text=修改封面", "text=更换封面", "text=上传封面", "text=设置封面", "text=编辑",
                        "button:has-text('修改封面')", "button:has-text('上传封面')", "button:has-text('更换封面')", "button:has-text('编辑')",
                        ".cover-upload-btn", ".post-cover-edit"
                    ]:
                        loc = page.locator(sel).first
                        if loc.count() > 0:
                            trigger_loc = loc
                            break
                            
                    if trigger_loc:
                        with page.expect_file_chooser(timeout=6000) as fc_info:
                            trigger_loc.click(force=True)
                        fc_info.value.set_files(cover_abs)
                        logger.info("Cover uploaded via file chooser.")
                        
                        # 尝试点击裁剪/封面的"确定"或"完成"按钮
                        page.wait_for_timeout(1500)
                        for btn_sel in ["text=确定", "text=完成", "button:has-text('确定')", "button:has-text('完成')"]:
                            btn = page.locator(btn_sel).last
                            if btn.count() > 0 and btn.is_visible():
                                btn.click(force=True)
                                logger.info(f"Clicked cover confirm button: {btn_sel}")
                                page.wait_for_timeout(1000)
                                break
                    else:
                        logger.warning("Could not find a valid cover upload trigger button.")
                except Exception as e:
                    logger.warning(f"Cover upload failed (non-fatal): {e}")

        # ── 6. 原创声明 ───────────────────────────────────────────────────────
        logger.info("Checking original declaration checkbox...")
        for sel in [
            "input[type='checkbox'][class*='original']",
            "label:has-text('原创') input[type='checkbox']",
            ".original-declaration input",
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    if not loc.first.is_checked():
                        loc.first.click(force=True)
                        
                        # 处理二次确认协议窗口 (终极防爆轮询机制)
                        try:
                            # 尝试 10 次，每次等 1 秒（最多 10 秒），不断尝试找按钮并点击
                            read_clicked = False
                            confirm_clicked = False
                            for attempt in range(10):
                                page.wait_for_timeout(1000)
                                
                                # 1. 尝试找到弹窗内的 checkbox 并点击
                                if not read_clicked:
                                    for cb_sel in [
                                        ".weui-desktop-dialog input[type='checkbox']",
                                        ".weui-desktop-dialog__bd input[type='checkbox']",
                                        "div[role='dialog'] input[type='checkbox']",
                                        "text=我已阅读",
                                        "text=阅读并同意",
                                        "label:has-text('阅读')",
                                        "label:has-text('条款')"
                                    ]:
                                        loc_cb = page.locator(cb_sel)
                                        if loc_cb.count() > 0:
                                            # 如果是真正的 input checkbox 并且已经勾选了，则跳过点击
                                            try:
                                                if loc_cb.first.evaluate("node => node.tagName === 'INPUT' && node.type === 'checkbox' && node.checked"):
                                                    read_clicked = True
                                                    break
                                            except Exception:
                                                pass
                                            
                                            try:
                                                loc_cb.first.click(timeout=500, force=True)
                                                read_clicked = True
                                                logger.info(f"Checked agreement in modal via {cb_sel} on attempt {attempt}")
                                                break
                                            except Exception:
                                                try:
                                                    # [Gemini_3.1_Pro_High_planning] 终极防爆：如果常规点击失败，使用原生 JS 强制修改 checked 属性并派发事件，无视遮罩层
                                                    loc_cb.first.evaluate("""node => {
                                                        if (node.tagName === 'INPUT' && node.type === 'checkbox') {
                                                            node.checked = true;
                                                            node.dispatchEvent(new Event('change', { bubbles: true }));
                                                        }
                                                        node.click();
                                                    }""")
                                                    read_clicked = True
                                                    logger.info(f"Checked agreement in modal (eval override) via {cb_sel} on attempt {attempt}")
                                                    break
                                                except Exception:
                                                    pass
                                                
                                        # [Gemini_3.1_Pro_High_planning] Frame 穿透：如果主 DOM 没有找到，尝试在所有的 iframes 中寻找
                                        if not read_clicked:
                                            for frame in page.frames:
                                                try:
                                                    floc = frame.locator(cb_sel)
                                                    if floc.count() > 0:
                                                        floc.first.evaluate("node => { node.checked = true; node.dispatchEvent(new Event('change', { bubbles: true })); node.click(); }")
                                                        read_clicked = True
                                                        logger.info(f"Checked agreement inside iframe via {cb_sel}")
                                                        break
                                                except Exception:
                                                    pass
                                                    
                                # 2. 尝试点击确定（必须在勾选阅读之后）
                                if read_clicked and not confirm_clicked:
                                    # 微信视频号声明原创弹窗按钮常见文本：“声明原创”、“确定”
                                    for bt in ["声明原创", "确定", "同意并继续", "同意"]:
                                        for btn_sel in [
                                            f".weui-desktop-dialog__ft button:has-text('{bt}')",
                                            f"button:has-text('{bt}')",
                                            f".weui-desktop-btn:has-text('{bt}')"
                                        ]:
                                            btn = page.locator(btn_sel)
                                            if btn.count() > 0:
                                                try:
                                                    btn.first.click(timeout=500, force=True)
                                                    confirm_clicked = True
                                                    logger.info(f"Clicked confirm '{bt}' button via {btn_sel} on attempt {attempt}")
                                                    break
                                                except Exception:
                                                    try:
                                                        btn.first.evaluate("node => node.click()")
                                                        confirm_clicked = True
                                                        logger.info(f"Clicked confirm '{bt}' button (eval) via {btn_sel} on attempt {attempt}")
                                                        break
                                                    except Exception:
                                                        pass
                                                        
                                                # [Gemini_3.1_Pro_High_planning] Frame 穿透：确认按钮的 iframe 查找
                                                if not confirm_clicked:
                                                    for frame in page.frames:
                                                        try:
                                                            fbtn = frame.locator(btn_sel)
                                                            if fbtn.count() > 0:
                                                                fbtn.first.evaluate("node => node.click()")
                                                                confirm_clicked = True
                                                                logger.info(f"Clicked confirm '{bt}' inside iframe via {btn_sel}")
                                                                break
                                                        except Exception:
                                                            pass
                                        if confirm_clicked:
                                            break

                                if read_clicked and confirm_clicked:
                                    logger.info("Modal dialog handled successfully.")
                                    # 等待弹窗消失
                                    page.wait_for_timeout(1000)
                                    break
                                    
                        except Exception as e:
                            logger.info(f"Modal handling error: {e}")

                    logger.info(f"Original declaration checked via: {sel}")
                    break
            except Exception:
                continue

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

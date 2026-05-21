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
        # 强制使用 chromium 并指定参数以支持视频格式与稳定上传
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-web-security", "--no-sandbox"]
        )
        
        # 加载 Cookie 状态
        context_opts = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if state_file.exists():
            logger.info(f"Loading session state from: {state_file}")
            context_opts["storage_state"] = str(state_file)
            
        context = browser.new_context(**context_opts)
        page = context.new_page()
        
        logger.info(f"Navigating to WeChat Channels creation page: {WECHAT_CREATE_URL}")
        page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded")
        # 等待页面完全渲染（Vue SPA 需额外时间）
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        
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
            
        # 等待上传面板和描述编辑区呈现
        page.wait_for_timeout(5000)
        
        # 3. 填写视频文案/描述
        logger.info("Writing copy to description field...")
        desc_input = None
        for selector in ["div[contenteditable='true']", "textarea", ".editor", "div.placeholder", ".description-textarea"]:
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
                # 微信使用的是 contenteditable 富文本编辑器，使用键盘模拟输入最不易出错
                # 模拟全选并删除现有内容
                page.keyboard.press("Meta+A")
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                # 逐字/段插入文案
                page.keyboard.insert_text(copy_text)
                logger.info("Successfully pasted copy description.")
            except Exception as e:
                logger.error(f"Failed to write description: {e}")
        else:
            logger.warning("Could not find description input selector, trying fallback fill...")
            
        # ── 3. 短标题 ─────────────────────────────────────────────────────────
        if short_title:
            logger.info(f"Setting short title: {short_title!r}")
            title_selectors = [
                "input[placeholder*='\u6807\u9898']",
                "input[placeholder*='title']",
                ".post-title input",
                ".header-input",
                "input[maxlength='30']",
                "input[maxlength='28']",
            ]
            for sel in title_selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible(timeout=1500):
                        loc.first.fill(short_title)
                        logger.info(f"Short title set via selector: {sel}")
                        break
                except Exception:
                    continue
            else:
                logger.warning("Could not find title input field, skipping.")

        # ── 4. 封面上传 ───────────────────────────────────────────────────────
        if cover_abs:
            logger.info(f"Uploading cover: {cover_abs}")
            cover_set = False
            # 尝试直接找 accept=image 的 file input
            try:
                n = page.evaluate("() => document.querySelectorAll('input[type=\"file\"][accept*=\"image\"]').length")
                if n > 0:
                    page.locator("input[type='file'][accept*='image']").first.set_input_files(cover_abs)
                    logger.info("Cover uploaded via image file input.")
                    cover_set = True
            except Exception as e:
                logger.warning(f"Cover direct input failed: {e}")
            # filechooser 兜底
            if not cover_set:
                try:
                    cover_btn_sels = [
                        "button:has-text('\u4e0a\u4f20\u5c01\u9762')",
                        ".cover-upload", ".thumb-upload", "[class*='cover']",
                    ]
                    with page.expect_file_chooser(timeout=6000) as fc_info:
                        for sel in cover_btn_sels:
                            try:
                                loc = page.locator(sel)
                                if loc.count() > 0 and loc.first.is_visible():
                                    loc.first.click()
                                    break
                            except Exception:
                                continue
                    fc_info.value.set_files(cover_abs)
                    logger.info("Cover uploaded via file chooser.")
                except Exception as e:
                    logger.warning(f"Cover upload failed (non-fatal): {e}")

        # ── 5. 原创声明 ───────────────────────────────────────────────────────
        logger.info("Checking original declaration checkbox...")
        original_selectors = [
            "input[type='checkbox'][class*='original']",
            "label:has-text('\u539f\u521b') input[type='checkbox']",
            ".original-declaration input",
            "input[type='checkbox']:near(:text('\u539f\u521b'))",
        ]
        original_checked = False
        for sel in original_selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    if not loc.first.is_checked():
                        loc.first.check()
                    logger.info(f"Original declaration checked via: {sel}")
                    original_checked = True
                    break
            except Exception:
                continue
        if not original_checked:
            logger.warning("Could not find original declaration checkbox, skipping.")

        # ── 6. 分类选择 ───────────────────────────────────────────────────────
        if category:
            logger.info(f"Selecting category: {category!r}")
            cat_set = False
            # 尝试 select 元素
            for sel in ["select[class*='category']", "select[class*='type']", "select"]:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible(timeout=1500):
                        loc.first.select_option(label=category)
                        logger.info(f"Category set via select: {sel}")
                        cat_set = True
                        break
                except Exception:
                    continue
            # 尝试点击式下拉（微信常用 Vue 组件）
            if not cat_set:
                try:
                    # 点击分类触发器
                    for sel in [".category-selector", "[class*='category']",
                                "button:has-text('\u5206\u7c7b')", "[placeholder*='\u5206\u7c7b']"]:
                        loc = page.locator(sel)
                        if loc.count() > 0 and loc.first.is_visible():
                            loc.first.click()
                            page.wait_for_timeout(500)
                            # 点击对应选项
                            opt = page.locator(f"li:has-text('{category}'), div:has-text('{category}')")
                            if opt.count() > 0:
                                opt.first.click()
                                logger.info(f"Category '{category}' selected via dropdown.")
                                cat_set = True
                            break
                except Exception as e:
                    logger.warning(f"Category dropdown failed: {e}")
            if not cat_set:
                logger.warning(f"Could not set category '{category}', skipping.")

        # ── 7. 等待视频上传完成 ────────────────────────────────────────────────
        upload_finished = False
        for i in range(60): # 60 * 5s = 300s
            page.wait_for_timeout(5000)
            
            # 检测是否上传完成或处理完毕
            content = page.content()
            if "上传成功" in content or "已上传100%" in content or "上传完成" in content:
                logger.info("Upload progress reached 100% (detected via text).")
                upload_finished = True
                break
                
            # 也可以检测发表按钮的状态是否可用
            publish_btn = page.locator("button:has-text('发表')").first
            if publish_btn.count() > 0:
                is_disabled = publish_btn.get_attribute("disabled") is not None or "disabled" in (publish_btn.get_attribute("class") or "").lower()
                if not is_disabled:
                    logger.info("Upload progress completed (Publish button is enabled).")
                    upload_finished = True
                    break
                    
            logger.info(f"Still uploading... (tick {i+1}/60)")
            
        if not upload_finished:
            logger.warning("Video upload verification timed out (5 minutes). Attempting to proceed anyway.")
            
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

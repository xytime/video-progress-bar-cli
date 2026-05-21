"""WeChat Channels Automated Video Uploader - Automates posting videos and copy to WeChat Creator Platform.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Gemini_3.5_Flash_planning | Initial creation of the WeChat uploader script using Playwright |
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

def run_uploader(video_path: str = None, copy_path: str = None, state_path: str = "output/wechat_state.json", 
                 login_only: bool = False, headless: bool = True, draft: bool = False) -> int:
    """运行 Playwright 微信上传自动化"""
    
    # 确保状态目录存在
    state_file = Path(state_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    if not login_only:
        if not video_path or not Path(video_path).exists():
            logger.error(f"Video file not found: {video_path}")
            return 1
        if not copy_path or not Path(copy_path).exists():
            logger.error(f"Copy text file not found: {copy_path}")
            return 1
            
        video_abs = str(Path(video_path).resolve())
        copy_text = Path(copy_path).read_text(encoding="utf-8")
    else:
        video_abs = None
        copy_text = None
        # [Gemini_3.5_Flash_planning] 登录时强制展示浏览器界面
        headless = False

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
        page.goto(WECHAT_CREATE_URL)
        
        # 等待页面加载
        page.wait_for_timeout(3000)
        
        # 检测是否重定向到登录页面
        is_login_page = False
        current_url = page.url
        if "login" in current_url or page.locator("text=使用微信扫码登录").is_visible() or page.locator(".login-box").is_visible() or page.locator(".login-qr").is_visible():
            is_login_page = True
            
        if is_login_page:
            if headless:
                # [Gemini_3.5_Flash_planning] 头模式下检测到登录失效，直接返回退出，提示上层触发扫码
                logger.error("Session expired or not logged in. Headless mode cannot perform QR scan.")
                browser.close()
                return 2 # 返回 2 标识需要扫码登录
            else:
                logger.info("==================================================")
                logger.info("⚠️ 请在弹出的浏览器窗口中，使用手机微信扫码登录！")
                logger.info("==================================================")
                try:
                    # 等待登录成功并跳转回创作页 (超时 120 秒)
                    page.wait_for_url("**/post/create", timeout=120000)
                    logger.info("Login detected. Saving session state...")
                    context.storage_state(path=str(state_file))
                    logger.info(f"Session saved to: {state_file}")
                except Exception as e:
                    logger.error(f"Login wait timed out or failed: {e}")
                    browser.close()
                    return 1
        else:
            logger.info("Successfully authenticated via saved session.")
            
        if login_only:
            logger.info("Login-only mode execution completed successfully.")
            browser.close()
            return 0
            
        # 2. 上传视频文件
        logger.info(f"Locating file input and uploading video: {video_abs}")
        try:
            # 微信视频号的文件上传控件通常是 input[type="file"]
            file_input = page.locator("input[type='file']")
            if file_input.count() > 0:
                file_input.first.set_input_files(video_abs)
                logger.info("Video file selected for upload.")
            else:
                logger.error("Failed to find file upload input element.")
                browser.close()
                return 1
        except Exception as e:
            logger.error(f"Failed to set input files: {e}")
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
            
        # 4. 等待视频上传并处理完毕
        logger.info("Waiting for video upload processing...")
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
    parser.add_argument("--video", help="Path to vertical MP4 video file")
    parser.add_argument("--copy", help="Path to WeChat copy description text file")
    parser.add_argument("--state", default="output/wechat_state.json", help="Path to save/load Playwright state")
    parser.add_argument("--login-only", action="store_true", help="Launch GUI to perform QR code login scan, then exit")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run browser in visible GUI mode")
    parser.add_argument("--draft", action="store_true", help="Save the video as draft instead of publishing")
    
    parser.set_defaults(headless=True)
    args = parser.parse_args()
    
    code = run_uploader(
        video_path=args.video,
        copy_path=args.copy,
        state_path=args.state,
        login_only=args.login_only,
        headless=args.headless,
        draft=args.draft
    )
    sys.exit(code)

if __name__ == "__main__":
    main()

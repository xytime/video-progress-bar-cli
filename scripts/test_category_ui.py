import sys
import time
from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="output/wechat_state.json", viewport={"width": 1280, "height": 1000})
        page = context.new_page()
        page.goto("https://channels.weixin.qq.com/platform/post/create", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        
        # If redirected to home, click 发表视频
        if "login" not in page.url and "/post/create" not in page.url:
            print("Clicking 发表视频 button...")
            try:
                page.locator("text=发表视频").first.click()
                page.wait_for_timeout(3000)
            except Exception as e:
                print("Failed to click 发表视频:", e)
                
        # 1. Try to upload a small video
        video_path = "/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/XcSdPK5Xwbk.mp4"
        try:
            print("Finding file input...")
            # Use same strategy as wechat_uploader
            upload_selectors = [
                "input[type='file']",
                "[class*='upload']:not(div>div)",
                "button:has-text('上传视频')",
                ".upload-btn", ".upload-area"
            ]
            for sel in upload_selectors:
                loc = page.locator(sel)
                if loc.count() > 0:
                    print(f"Found input via {sel}")
                    loc.first.set_input_files(video_path)
                    print("Video uploaded!")
                    break
        except Exception as e:
            print("Upload failed:", e)
            
        # 2. Wait for upload to complete
        page.wait_for_timeout(10000)
        
        # Scroll down to capture everything
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        
        # 3. Take screenshot
        page.screenshot(path="output/debug_test_category_after_upload_full.png", full_page=True)
        
        # 4. Dump all text on page to search for "分类"
        all_text = page.locator("body").inner_text()
        print("Page contains '分类':", "分类" in all_text)
        
        browser.close()

if __name__ == "__main__":
    test()

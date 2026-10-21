
# 2026-10-21: 旧诊断入口绕过账户调度，停用以保护账号。
raise SystemExit("旧视频号诊断入口已停用；请使用受账户调度保护的正式入口，禁止冷却探测。")

from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--window-size=1280,1000"])
    context = browser.new_context(storage_state="output/wechat_state.json")
    page = context.new_page()
    page.goto("https://channels.weixin.qq.com/platform/post/create")
    page.wait_for_timeout(3000)
    
    # Upload video
    with page.expect_file_chooser() as fc_info:
        page.locator("input[type='file']").first.click(force=True)
    fc_info.value.set_files("output/zJ0V9gvK5FU.mp4")
    
    # Wait for the form to appear
    print("Waiting for form...")
    page.wait_for_timeout(15000)
    
    with open("output/page_after_upload.html", "w") as f:
        f.write(page.content())
    print("Dumped to output/page_after_upload.html")
    browser.close()

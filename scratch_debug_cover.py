import time
from playwright.sync_api import sync_playwright

STATE = "output/wechat_state.json"
VIDEO = "output/zJ0V9gvK5FU.mp4"
COVER = "/Users/ryusei/.gemini/antigravity/brain/11cc548f-1a93-4780-93df-ada5f9761875/artifacts/iB2eApp0Kmo_cover.jpg"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        storage_state=STATE,
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()
    
    page.goto("https://channels.weixin.qq.com/platform/post/create", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # 1. Upload video
    with page.expect_file_chooser(timeout=10000) as fc:
        page.locator("[class*='upload']:not(div>div)").first.click()
    fc.value.set_files(VIDEO)
    
    # wait for upload to complete
    for _ in range(30):
        page.wait_for_timeout(2000)
        btn = page.locator("button:has-text('发表')").first
        if btn.count() > 0 and btn.get_attribute("disabled") is None:
            print("Upload complete.")
            break

    # 2. Upload cover
    print("Uploading cover...")
    cover_card_sels = [
        "text=个人主页卡片",
        "text=分享卡片",
        "text=封面预览",
    ]
    for card_sel in cover_card_sels:
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
            
        print(f"Found 编辑 button under: {card_sel}. Clicking...")
        edit_btn.first.click(force=True)
        page.wait_for_timeout(2000)
        
        page.screenshot(path="output/debug_cover_1_modal_opened.png")
        
        upload_btn = None
        for inner_sel in ["text=上传封面", "text=本地上传", ".upload-btn", ".cover-upload"]:
            inner_loc = page.locator(inner_sel).last
            if inner_loc.count() > 0 and inner_loc.is_visible():
                upload_btn = inner_loc
                print(f"Found upload trigger: {inner_sel}")
                break
                
        if upload_btn:
            upload_btn.click(force=True)
            page.wait_for_timeout(1500)
            
        file_injected = False
        for input_sel in [
            ".edit-cover-dialog-container input[type='file']",
            "input[type='file'][accept*='image']",
            "input[type='file']",
        ]:
            file_input = page.locator(input_sel).last
            if file_input.count() > 0:
                file_input.set_input_files(COVER)
                print(f"Cover file injected via hidden input: {input_sel}")
                file_injected = True
                break
                
        page.wait_for_timeout(3000)
        page.screenshot(path="output/debug_cover_2_after_injection.png")
        
        for btn_text in ["完成", "确定", "保存", "应用"]:
            btn = page.locator(f".edit-cover-dialog-container button:has-text('{btn_text}')").last
            if btn.count() == 0:
                btn = page.locator(f"button:has-text('{btn_text}')").last
            if btn.count() > 0 and btn.is_visible():
                print(f"Clicking confirm button: '{btn_text}'")
                btn.click(force=True)
                break
                
        page.wait_for_timeout(2000)
        page.screenshot(path="output/debug_cover_3_after_confirm.png")
        break

    browser.close()

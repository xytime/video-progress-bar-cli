import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(storage_state="output/wechat_state.json")
    page = context.new_page()
    page.goto("https://channels.weixin.qq.com/platform/post/create")
    page.wait_for_timeout(3000)
    
    # Strategy B from wechat_uploader
    clicked = False
    with page.expect_file_chooser(timeout=10000) as fc_info:
        for sel in ["[class*='upload']:not(div>div)", "button:has-text('上传视频')", "button:has-text('上传')", ".upload-btn", ".upload-area"]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    clicked = True
                    break
            except: pass
    if clicked:
        fc_info.value.set_files("output/zJ0V9gvK5FU.mp4")
        print("Upload initiated...")
    else:
        print("Fallback: trying input[type='file']")
        page.locator("input[type='file']").first.set_input_files("output/zJ0V9gvK5FU.mp4")

    print("Waiting for upload to complete and DOM to render...")
    page.wait_for_timeout(10000)
    
    # Dump all placeholders
    elements = page.evaluate('''() => {
        return Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]')).map(el => {
            return {
                tag: el.tagName,
                placeholder: el.placeholder || el.getAttribute('placeholder') || '',
                class: el.className,
                id: el.id
            }
        });
    }''')
    
    print("ALL INPUT ELEMENTS:")
    for el in elements:
        print(el)
        
    # Open cover modal
    print("Hovering cover area and clicking 编辑")
    try:
        page.locator("text=封面预览").locator("xpath=..").hover()
        page.wait_for_timeout(1000)
        page.locator("text=编辑").first.click(force=True)
        page.wait_for_timeout(2000)
        
        # Dump modal buttons
        modal_btns = page.evaluate('''() => {
            let dialog = document.querySelector('.weui-desktop-dialog, .modal, div[role="dialog"]');
            if(!dialog) return [];
            return Array.from(dialog.querySelectorAll('button, .weui-desktop-btn')).map(b => b.innerText.trim());
        }''')
        print("COVER MODAL BUTTONS:", modal_btns)
    except Exception as e:
        print("Failed to open cover modal:", e)
        
    browser.close()

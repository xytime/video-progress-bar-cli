import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(storage_state="output/wechat_state.json")
    page = context.new_page()
    page.goto("https://channels.weixin.qq.com/platform/post/create")
    page.wait_for_timeout(3000)
    
    with page.expect_file_chooser(timeout=10000) as fc_info:
        page.locator("[class*='upload']:not(div>div)").first.click()
    fc_info.value.set_files("output/zJ0V9gvK5FU.mp4")
    
    page.wait_for_timeout(15000) # Wait for upload
    
    data = []
    # Playwright locator automatically pierces Shadow DOM
    for el in page.locator("input, textarea, [contenteditable='true']").all():
        tag = el.evaluate("node => node.tagName")
        cls = el.get_attribute("class") or ""
        ph = el.get_attribute("placeholder") or ""
        text = el.inner_text() or ""
        val = el.input_value() if "input" in tag.lower() or "textarea" in tag.lower() else ""
        data.append({"tag": tag, "class": cls, "placeholder": ph, "text": text, "value": val})
        
    with open("output/test_dom_playwright.json", "w") as f:
        json.dump(data, f)
        
    browser.close()

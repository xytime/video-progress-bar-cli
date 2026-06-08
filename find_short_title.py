from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(storage_state="output/wechat_state.json")
    page = context.new_page()
    page.goto("https://channels.weixin.qq.com/platform/post/create")
    page.wait_for_timeout(3000)
    
    # Use standard input file setter since click() timed out last time
    inputs = page.locator("input[type='file']")
    if inputs.count() > 0:
        inputs.first.set_input_files("output/zJ0V9gvK5FU.mp4")
        print("Video uploaded.")
    else:
        print("No file input found.")
        
    page.wait_for_timeout(10000)
    
    # Now find the short title element
    elements = page.locator("input, textarea, [contenteditable='true']").all()
    found = False
    for el in elements:
        ph = el.get_attribute("placeholder") or ""
        if "短标题" in ph or "标题" in ph:
            print(f"FOUND: tag={el.evaluate('node => node.tagName')}, placeholder={ph}, class={el.get_attribute('class')}")
            found = True
    
    if not found:
        print("Not found by placeholder. Dumping all input placeholders:")
        for el in elements:
            ph = el.get_attribute("placeholder") or ""
            if ph:
                print(f" - {ph}")
                
    browser.close()

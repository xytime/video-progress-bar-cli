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
    
    page.wait_for_timeout(10000) # Wait for upload
    
    # DUMP THE DOM AROUND '个人主页卡片'
    print("Dumping cover elements...")
    html = page.evaluate('''() => {
        let el = document.evaluate("//*[contains(text(), '个人主页卡片')]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        if(!el) return "Not Found";
        return el.parentElement.parentElement.outerHTML;
    }''')
    print("HTML:\n", html)
    
    browser.close()

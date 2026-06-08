# -*- coding: utf-8 -*-
"""Verify WeChat session login status.

# Modification History
| Version | Date       | Author                   | Description           |
|---------|------------|--------------------------|-----------------------|
| 1.0.0   | 2026-06-01 | Gemini_3.5_Flash_planning | Initial verify script |
"""

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

def verify_session():
    # [Gemini_3.5_Flash_planning] Define path to state file
    state_file = Path("output/wechat_state.json")
    if not state_file.exists():
        print("ERROR: State file output/wechat_state.json does not exist.")
        return 1

    print(f"Loading state file: {state_file}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(state_file),
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        
        # [Gemini_3.5_Flash_planning] Navigate to WeChat creation page
        url = "https://channels.weixin.qq.com/platform/post/create"
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        
        current_url = page.url
        print(f"Current URL: {current_url}")
        
        if "post/create" in current_url:
            print("SUCCESS: Session is valid and logged in!")
            browser.close()
            return 0
        else:
            print("FAIL: Redirected or not logged in.")
            browser.close()
            return 2

if __name__ == "__main__":
    sys.exit(verify_session())

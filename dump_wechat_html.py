
# 2026-10-21: 旧诊断入口绕过账户调度，停用以保护账号。
raise SystemExit("旧视频号诊断入口已停用；请使用受账户调度保护的正式入口，禁止冷却探测。")

from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(storage_state="output/wechat_state.json")
    page = context.new_page()
    page.goto("https://channels.weixin.qq.com/platform/post/create")
    page.wait_for_timeout(5000)
    with open("output/page_dump.html", "w") as f:
        f.write(page.content())
    browser.close()

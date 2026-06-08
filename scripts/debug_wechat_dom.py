import time
from playwright.sync_api import sync_playwright

def main():
    print("🚀 启动微信视频号 DOM 探测器...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--window-size=1280,1000"])
        context = browser.new_context(storage_state="output/wechat_state.json")
        page = context.new_page()
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        
        print("\n" + "="*50)
        print("请在弹出的浏览器中：")
        print("1. 手动上传一个测试视频")
        print("2. 找到【短标题】输入框，随便输入几个字")
        print("3. 点击封面的【编辑】按钮，进入封面裁剪/选择弹窗，但不要点击完成")
        print("="*50 + "\n")
        
        input("👉 准备好后，请按回车键继续探测 DOM 结构...")
        
        print("\n🔍 正在截取全网页长截图...")
        page.screenshot(path="output/debug_full_page.png", full_page=True)
        print("✅ 全网页截图已保存至 output/debug_full_page.png")
        
        print("🔍 正在扫描【短标题】输入框...")
        # 查找所有可能包含我们输入的短标题的元素，或者placeholder
        elements = page.locator("input, textarea, [contenteditable='true']").all()
        found_title = False
        for el in elements:
            try:
                val = el.input_value()
                ph = el.get_attribute("placeholder") or ""
                if "短标题" in ph or "标题" in ph:
                    print(f"🎯 发现疑似短标题输入框: tag={el.evaluate('node => node.tagName')}, placeholder='{ph}', class='{el.get_attribute('class')}'")
                    found_title = True
            except:
                pass
        if not found_title:
            print("❌ 未能通过常规属性找到短标题输入框，它可能隐藏在更深层或无特征。")

        print("🔍 正在扫描封面裁剪弹窗的确认按钮...")
        dialogs = page.locator(".weui-desktop-dialog, .modal, div[role='dialog']").all()
        for d in dialogs:
            if d.is_visible():
                print(f"🎯 发现弹窗。内部按钮：")
                btns = d.locator("button, .btn").all()
                for b in btns:
                    try:
                        print(f"   - 按钮文本: '{b.inner_text().strip()}', class='{b.get_attribute('class')}'")
                    except:
                        pass
        
        print("\n探测完成！浏览器将在 5 秒后关闭...")
        time.sleep(5)
        browser.close()

if __name__ == "__main__":
    main()

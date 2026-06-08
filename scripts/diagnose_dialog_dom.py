#!/usr/bin/env python3
"""
diagnose_dialog_dom.py — 当封面弹窗打开时，用 Playwright 分析其真实 DOM

使用方式:
  1. 手动打开微信视频号助手页面，进入发布视频页，打开封面编辑弹窗
  2. 运行本脚本，脚本会连接到已有浏览器 OR 直接分析截图中描述的弹窗

因为弹窗是动态的，这里换一个策略:
- 启动浏览器，加载 session
- 上传一个视频
- 等待进入上传完成状态 
- 打开封面弹窗
- 在弹窗打开的那一刻，抓取完整 DOM (包括 shadow DOM 和 iframe)

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-24 | Claude_Sonnet_4.6_Thinking | 分析弹窗真实DOM结构 |
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from playwright.sync_api import sync_playwright

STATE_FILE = Path("output/wechat_state.json")
OUTPUT_DIR = Path("output")

DUMP_JS = """() => {
    function analyzeElement(el, depth=0) {
        if (depth > 10) return null;
        const children = Array.from(el.children).map(c => analyzeElement(c, depth+1)).filter(Boolean);
        const text = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3)
            .map(n => n.textContent.trim())
            .filter(t => t.length > 0)
            .join(' ');
        return {
            tag: el.tagName,
            id: el.id || undefined,
            class: el.className || undefined,
            role: el.getAttribute('role') || undefined,
            aria_checked: el.getAttribute('aria-checked') || undefined,
            disabled: el.disabled || el.getAttribute('disabled') || undefined,
            type: el.type || undefined,
            text: text || undefined,
            children: children.length > 0 ? children : undefined
        };
    }
    
    // 找到最上层的可见弹窗
    const results = {
        dialogs: [],
        iframes: [],
        confirm_buttons: [],
        all_buttons: [],
        original_area: null
    };
    
    // 所有弹窗容器
    for (const sel of ['[role="dialog"]', '.weui-desktop-dialog', '[class*="modal"]', '[class*="dialog"]', '[class*="Dialog"]', '[class*="Modal"]']) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
            if (el.offsetParent !== null || el.style.display !== 'none') {
                results.dialogs.push({
                    selector: sel,
                    tag: el.tagName,
                    class: el.className,
                    inner_html_snippet: el.innerHTML.slice(0, 500),
                    buttons: Array.from(el.querySelectorAll('button, [class*="btn"], [class*="Btn"], a')).map(b => ({
                        tag: b.tagName, class: b.className, text: b.innerText.trim(),
                        disabled: b.disabled || b.getAttribute('disabled'),
                        visible: b.offsetParent !== null,
                        type: b.type
                    }))
                });
            }
        }
    }
    
    // iframe 信息
    for (const iframe of document.querySelectorAll('iframe')) {
        results.iframes.push({
            src: iframe.src, class: iframe.className, id: iframe.id,
            visible: iframe.offsetParent !== null
        });
        try {
            const idoc = iframe.contentDocument;
            if (idoc) {
                const btns = Array.from(idoc.querySelectorAll('button, [class*="btn"]')).map(b => ({
                    tag: b.tagName, class: b.className, text: b.innerText?.trim()
                }));
                results.iframes[results.iframes.length-1].inner_buttons = btns;
            }
        } catch(e) { results.iframes[results.iframes.length-1].cross_origin_error = e.toString(); }
    }
    
    // 全局找所有按钮
    for (const btn of document.querySelectorAll('button, [class*="btn-primary"], [class*="btn-confirm"]')) {
        if (btn.offsetParent !== null) {
            results.all_buttons.push({
                tag: btn.tagName, class: btn.className, text: btn.innerText?.trim(),
                disabled: btn.disabled || btn.getAttribute('disabled')
            });
        }
    }
    
    // 找原创声明区域 (用文字节点遍历)
    const allText = document.querySelectorAll('*');
    for (const el of allText) {
        const directText = el.innerText?.trim();
        if (directText && (directText.includes('声明原创') || directText.includes('原创声明')) && el.children.length < 5) {
            results.original_area = {
                tag: el.tagName,
                class: el.className,
                text: directText.slice(0, 200),
                html: el.outerHTML.slice(0, 500),
                parent_html: el.parentElement?.outerHTML?.slice(0, 500)
            };
            break;
        }
    }
    
    return results;
}
"""

def wait_for_upload_complete(page):
    """等待视频上传完成的关键：找到封面区域的"编辑"按钮"""
    for _ in range(60):  # 最多等60秒
        page.wait_for_timeout(1000)
        # 如果封面区域出现了，说明上传完成
        for sel in ["text=封面预览", "text=个人主页卡片", "text=分享卡片", ".cover-wrap", "[class*='cover']"]:
            loc = page.locator(sel)
            if loc.count() > 0:
                print(f"✅ 检测到上传完成标志: {sel}")
                return True
    return False


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        ctx = browser.new_context(
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        
        print("🚀 正在加载页面...")
        page.goto("https://channels.weixin.qq.com/platform/post/create", timeout=60000)
        page.wait_for_timeout(5000)
        page.screenshot(path="output/diag2_01_loaded.png")
        
        # 检查是否已登录
        if "login" in page.url or page.locator("text=微信扫码").count() > 0:
            print("❌ Session 已过期，需要重新登录！请手动扫码后按 Enter 继续...")
            input("按 Enter 继续...")
            page.wait_for_timeout(3000)
        
        # 上传最小的测试视频
        vertical_files = sorted(OUTPUT_DIR.glob("*_vertical.mp4"), key=lambda f: f.stat().st_size)
        if not vertical_files:
            print("❌ 无可用测试视频")
            return
        
        video_path = str(vertical_files[0].resolve())
        print(f"📹 上传测试视频: {vertical_files[0].name} ({vertical_files[0].stat().st_size // 1024} KB)")
        
        for sel in ["input[type='file'][accept*='video']", "input[type='file']"]:
            fi = page.locator(sel)
            if fi.count() > 0:
                fi.first.set_input_files(video_path)
                print(f"✅ 视频已注入: {sel}")
                break
        
        print("⏳ 等待上传完成...")
        done = wait_for_upload_complete(page)
        if not done:
            print("⚠️ 超时未检测到上传完成，继续分析...")
        page.wait_for_timeout(3000)
        page.screenshot(path="output/diag2_02_post_upload.png")
        
        # 打开封面编辑弹窗
        print("\n📖 正在打开封面编辑弹窗...")
        opened = False
        
        # 策略1: hover 封面预览区域 -> 点击编辑
        for card_sel in ["text=封面预览", "text=个人主页卡片", "text=分享卡片"]:
            try:
                card = page.locator(card_sel).first
                if card.count() > 0 and card.is_visible():
                    parent = card.locator("xpath=../..")
                    parent.hover()
                    page.wait_for_timeout(1000)
                    edit_btn = parent.locator("text=编辑")
                    if edit_btn.count() == 0:
                        edit_btn = page.locator("text=编辑").last
                    if edit_btn.count() > 0 and edit_btn.is_visible():
                        edit_btn.click(force=True)
                        opened = True
                        print(f"✅ 通过 {card_sel} -> 编辑 打开弹窗")
                        break
            except Exception as e:
                print(f"  ⚠️ {card_sel}: {e}")
        
        if not opened:
            print("⚠️ 未能自动打开弹窗，等您手动打开编辑封面弹窗后按 Enter...")
            input("请手动打开封面编辑弹窗, 然后按 Enter 继续分析...")
        
        page.wait_for_timeout(2000)
        page.screenshot(path="output/diag2_03_dialog_open.png")
        
        # === 分析弹窗 DOM ===
        print("\n🔬 分析弹窗 DOM...")
        dom_result = page.evaluate(DUMP_JS)
        
        with open("output/diag2_04_full_dom.json", "w", encoding="utf-8") as f:
            json.dump(dom_result, f, ensure_ascii=False, indent=2)
        
        print(f"\n📊 分析结果:")
        print(f"  弹窗容器数量: {len(dom_result['dialogs'])}")
        print(f"  iframe 数量: {len(dom_result['iframes'])}")
        print(f"  全局可见按钮: {len(dom_result['all_buttons'])}")
        
        print("\n  📌 弹窗内按钮:")
        for d in dom_result['dialogs']:
            for btn in d.get('buttons', []):
                if btn.get('text'):
                    print(f"    [{btn['tag']}] class='{btn['class']}' text='{btn['text']}' disabled={btn['disabled']} visible={btn['visible']}")
        
        print("\n  📌 全局可见按钮 (非空文字):")
        for btn in dom_result['all_buttons']:
            if btn.get('text'):
                print(f"    [{btn['tag']}] class='{btn['class']}' text='{btn['text']}' disabled={btn['disabled']}")
        
        print("\n  📌 iframe 内按钮:")
        for iframe in dom_result['iframes']:
            if iframe.get('inner_buttons'):
                for btn in iframe['inner_buttons']:
                    if btn.get('text'):
                        print(f"    [iframe:{iframe['src'][:60]}] [{btn['tag']}] class='{btn['class']}' text='{btn['text']}'")
        
        if dom_result.get('original_area'):
            print(f"\n  📌 原创声明区域: {dom_result['original_area']}")
        
        print(f"\n✅ 完整 DOM 已保存至: output/diag2_04_full_dom.json")
        
        # 上传封面并在弹窗打开后分析
        # 找到上传封面 input
        print("\n📎 尝试上传封面图...")
        cover_files = list(OUTPUT_DIR.glob("*_cover.jpg"))
        if cover_files:
            cover_path = str(cover_files[0].resolve())
            for input_sel in [
                ".edit-cover-dialog-container input[type='file']",
                "input[type='file'][accept*='image']",
                "input[type='file']"
            ]:
                fi = page.locator(input_sel).last
                if fi.count() > 0:
                    fi.set_input_files(cover_path)
                    print(f"✅ 封面已注入: {input_sel}")
                    break
            page.wait_for_timeout(5000)
            page.screenshot(path="output/diag2_05_after_cover_upload.png")
            
            # 再次分析 DOM，这次应该有确认按钮了
            print("\n🔬 封面上传后再次分析 DOM...")
            dom_result2 = page.evaluate(DUMP_JS)
            with open("output/diag2_06_after_cover_dom.json", "w", encoding="utf-8") as f:
                json.dump(dom_result2, f, ensure_ascii=False, indent=2)
            
            print("\n  📌 封面上传后弹窗内按钮:")
            for d in dom_result2['dialogs']:
                for btn in d.get('buttons', []):
                    if btn.get('text'):
                        print(f"    [{btn['tag']}] class='{btn['class']}' text='{btn['text']}' disabled={btn['disabled']} visible={btn['visible']}")
            
            print("\n  📌 封面上传后全局可见按钮:")
            for btn in dom_result2['all_buttons']:
                if btn.get('text'):
                    print(f"    [{btn['tag']}] class='{btn['class']}' text='{btn['text']}' disabled={btn['disabled']}")
        
        input("\n按 Enter 退出...")
        browser.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
diagnose_original_rights_dialog.py — 自动化诊断“原创权益”弹窗 DOM 结构并输出的工具

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-05-24 | Gemini_3.5_Flash_High_planning | 升级为完全自动化运行版本 |
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from playwright.sync_api import sync_playwright

STATE_FILE = Path("output/wechat_state.json")
OUTPUT_DIR = Path("output")

DUMP_JS = """() => {
    function querySelectorAllDeep(selector, root = document, result = []) {
        const elements = root.querySelectorAll(selector);
        for (const el of elements) {
            result.push(el);
        }
        const allElements = root.querySelectorAll('*');
        for (const el of allElements) {
            if (el.shadowRoot) {
                querySelectorAllDeep(selector, el.shadowRoot, result);
            }
        }
        return result;
    }

    function serializeDom(el) {
        const rect = el.getBoundingClientRect();
        const attrs = {};
        for (const attr of el.attributes || []) {
            attrs[attr.name] = attr.value;
        }
        
        const children = [];
        for (const child of el.children || []) {
            const childData = serializeDom(child);
            if (childData) children.push(childData);
        }

        const textNodes = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).filter(Boolean);
        
        return {
            tagName: el.tagName,
            className: el.className,
            id: el.id || undefined,
            attributes: Object.keys(attrs).length > 0 ? attrs : undefined,
            text: textNodes.join(' ') || undefined,
            innerText: el.innerText ? el.innerText.trim().slice(0, 150) : undefined,
            rect: {
                left: rect.left,
                top: rect.top,
                width: rect.width,
                height: rect.height
            },
            children: children.length > 0 ? children : undefined
        };
    }

    // Find dialogs
    const divs = querySelectorAllDeep('div, dialog, section');
    const dialogEl = divs.find(el => {
        const text = el.innerText || '';
        return text.includes('原创权益') && text.includes('我已阅读') && text.length < 2000;
    });

    if (!dialogEl) {
        // Fallback: search for any element containing "原创权益"
        const all = querySelectorAllDeep('*');
        const match = all.find(el => {
            const text = el.innerText || '';
            return text.includes('原创权益') && text.includes('我已阅读') && text.length < 2000;
        });
        if (match) {
            return {
                found: true,
                message: 'Found container via generic match',
                html: match.outerHTML,
                serialized: serializeDom(match)
            };
        }
        return { error: '未在任何 Shadow DOM 中找到原创权益弹窗' };
    }

    return {
        found: true,
        html: dialogEl.outerHTML,
        serialized: serializeDom(dialogEl)
    };
}
"""

def wait_for_upload_complete(page):
    """等待视频上传完成：找到封面区域的编辑或类似按钮"""
    for _ in range(60):  # 最多等60秒
        page.wait_for_timeout(1000)
        for sel in ["text=封面预览", "text=个人主页卡片", "text=分享卡片", ".cover-wrap", "[class*='cover']"]:
            loc = page.locator(sel)
            if loc.count() > 0:
                print(f"✅ 检测到上传完成标志: {sel}")
                return True
    return False

def main():
    print("🚀 启动自动化微信原创权益弹窗 DOM 诊断器...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--window-size=1280,1000"])
        context = browser.new_context(
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_timeout(5000)
        
        # 检查是否登录 (检查URL中是否包含 post/create)
        if "/post/create" not in page.url:
            print("❌ 未登录，当前 URL 是:", page.url)
            browser.close()
            return
            
        # 查找测试视频
        video_path = Path("XcSdPK5Xwbk.mp4")
        if not video_path.exists():
            print("❌ 未找到测试视频 XcSdPK5Xwbk.mp4")
            browser.close()
            return
            
        print(f"📹 正在上传测试视频: {video_path.name}")
        for sel in ["input[type='file'][accept*='video']", "input[type='file']"]:
            fi = page.locator(sel)
            if fi.count() > 0:
                fi.first.set_input_files(str(video_path.resolve()))
                print(f"✅ 视频已注入: {sel}")
                break
                
        print("⏳ 等待上传完成...")
        if not wait_for_upload_complete(page):
            print("⚠️ 上传超时")
            
        page.wait_for_timeout(3000)
        
        # 点击“原创声明”开关
        print("👆 尝试点击原创声明 toggle...")
        css_selectors = [
            "label:has-text('原创') input[type='checkbox']",
            "label:has-text('声明原创') input[type='checkbox']",
            "input[type='checkbox'][class*='original']",
            ".original-declaration input",
            "input[type='checkbox']:near(:text('原创'))",
            "input[type='checkbox']:near(:text('声明原创'))",
            ".weui-desktop-switch:near(:text('原创'))",
            ".weui-desktop-switch:near(:text('声明原创'))",
        ]
        
        toggled = False
        for sel in css_selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    print(f"✅ 点击成功: {sel}")
                    toggled = True
                    break
            except Exception as e:
                pass
                
        if not toggled:
            # 尝试 JS 文字定位
            result = page.evaluate("""() => {
                const targets = ['声明原创', '原创声明', '原创'];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    const txt = node.textContent.trim();
                    if (!targets.includes(txt)) continue;
                    let el = node.parentElement;
                    for (let i = 0; i < 8 && el; i++) {
                        const cb = el.querySelector('input[type="checkbox"]');
                        if (cb) { cb.click(); return {ok:true, method:'cb'}; }
                        const sw = el.querySelector('[role="switch"]');
                        if (sw) { sw.click(); return {ok:true, method:'role-switch'}; }
                        const toggleEl = el.querySelector('[class*="switch"],[class*="toggle"]');
                        if (toggleEl) { toggleEl.click(); return {ok:true, method:'cls-toggle'}; }
                        if (el.tagName === 'LABEL' || el.getAttribute('role') === 'button') {
                            el.click(); return {ok:true, method:'row-click'};
                        }
                        el = el.parentElement;
                    }
                }
                return {ok:false};
            }""")
            if result and result.get('ok'):
                print(f"✅ 通过 JS 文字定位点击成功: {result}")
                toggled = True
                
        if not toggled:
            print("❌ 无法点击原创声明开关")
            page.screenshot(path="output/diagnose_original_toggle_failed.png")
            browser.close()
            return
            
        print("⏳ 等待 3 秒让弹窗完全出现...")
        page.wait_for_timeout(3000)
        page.screenshot(path="output/diagnose_original_dialog_open.png")
        
        print("🔍 捕获弹窗 DOM 结构中...")
        res = page.evaluate(DUMP_JS)
        
        if "error" in res:
            print(f"❌ 诊断失败: {res['error']}")
            page.screenshot(path="output/diagnose_original_failed_capture.png")
        else:
            output_path_html = OUTPUT_DIR / "diagnose_original_result.html"
            with open(output_path_html, "w", encoding="utf-8") as f:
                f.write(res.get("html", ""))
                
            output_path_json = OUTPUT_DIR / "diagnose_original_result.json"
            with open(output_path_json, "w", encoding="utf-8") as f:
                json.dump(res.get("serialized", {}), f, ensure_ascii=False, indent=2)
                
            print(f"✅ 诊断 HTML 已保存至: {output_path_html}")
            print(f"✅ 诊断 JSON 已保存至: {output_path_json}")
            print("🎉 成功捕获并保存了弹窗结构！")
            
        browser.close()

if __name__ == "__main__":
    main()

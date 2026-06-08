#!/usr/bin/env python3
"""
diagnose_cover_dialog.py — 封面弹窗与原创声明区 DOM 诊断工具

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-24 | Claude_Sonnet_4.6_Thinking | 初建，用于精确捕获弹窗DOM与原创声明DOM，定位根因 |
"""
import sys
import json
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

STATE_FILE = Path("output/wechat_state.json")
OUTPUT_DIR = Path("output")

def diagnose():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto("https://channels.weixin.qq.com/platform/post/create", timeout=60000)
        page.wait_for_timeout(5000)

        # === 阶段1: 找第一个可用视频文件并上传 ===
        # 找 output 目录下最小的 _vertical.mp4
        vertical_files = sorted(OUTPUT_DIR.glob("*_vertical.mp4"), key=lambda f: f.stat().st_size)
        if not vertical_files:
            print("❌ 没有找到 _vertical.mp4 文件，请先处理至少一个视频")
            browser.close()
            return

        video_path = str(vertical_files[0].resolve())
        print(f"📹 使用测试视频: {video_path}")

        # 上传视频
        for sel in ["input[type='file'][accept*='video']", "input[type='file']"]:
            fi = page.locator(sel)
            if fi.count() > 0:
                fi.first.set_input_files(video_path)
                print(f"✅ 视频已上传: {sel}")
                break

        # 等待上传进度
        print("⏳ 等待视频上传完成 (最多90s)...")
        try:
            page.wait_for_selector(".upload-progress", state="detached", timeout=90000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        page.screenshot(path="output/diag_01_after_upload.png")

        # === 阶段2: 打开封面编辑弹窗 ===
        # 先 Hover 封面预览区域，使"编辑"按钮出现
        print("\n🔍 [阶段2] 寻找封面编辑入口...")
        cover_selectors_to_try = [
            ".cover-wrap",
            ".post-cover",
            ".video-cover",
            "[class*='cover']",
            "text=封面预览",
            "text=个人主页卡片",
            "text=分享卡片",
        ]
        found_edit = False
        for sel in cover_selectors_to_try:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=2000):
                    loc.hover()
                    page.wait_for_timeout(1500)
                    # 找 编辑 按钮
                    edit_btn = page.locator("text=编辑").last
                    if edit_btn.count() == 0:
                        edit_btn = page.locator("button:has-text('编辑')").last
                    if edit_btn.count() > 0 and edit_btn.is_visible():
                        print(f"✅ 找到编辑按钮, hover 触发: {sel}")
                        edit_btn.click(force=True)
                        found_edit = True
                        break
            except Exception as e:
                print(f"  ⚠️ {sel}: {e}")
                continue

        if not found_edit:
            # 尝试直接点击"编辑"
            edit_btn = page.locator("text=编辑").last
            if edit_btn.count() > 0:
                edit_btn.click(force=True)
                found_edit = True
                print("✅ 直接点击 text=编辑")

        page.wait_for_timeout(2000)
        page.screenshot(path="output/diag_02_edit_cover_opened.png")

        # === 阶段3: 分析弹窗 DOM ===
        print("\n🔍 [阶段3] 分析封面编辑弹窗 DOM...")
        dialog_info = {}

        # 用JS提取弹窗内所有按钮的完整信息
        dialog_dom = page.evaluate("""() => {
            const results = {};

            // 方法1: 找所有 role=dialog 的元素
            const roleDialogs = document.querySelectorAll('[role="dialog"]');
            results.role_dialogs = Array.from(roleDialogs).map(d => ({
                tag: d.tagName,
                class: d.className,
                visible: d.offsetParent !== null,
                text_snippet: d.innerText?.slice(0, 200),
                buttons: Array.from(d.querySelectorAll('button, [class*="btn"], [class*="Btn"]')).map(b => ({
                    tag: b.tagName,
                    class: b.className,
                    text: b.innerText?.trim(),
                    disabled: b.disabled || b.getAttribute('disabled'),
                    visible: b.offsetParent !== null,
                }))
            }));

            // 方法2: 找所有 weui-desktop-dialog 类的元素
            const weuiDialogs = document.querySelectorAll('[class*="weui-desktop-dialog"], [class*="dialog"]');
            results.weui_dialogs = Array.from(weuiDialogs).map(d => ({
                tag: d.tagName,
                class: d.className,
                visible: d.offsetParent !== null,
                text_snippet: d.innerText?.slice(0, 200),
                buttons: Array.from(d.querySelectorAll('button, [class*="btn"], [class*="Btn"]')).map(b => ({
                    tag: b.tagName,
                    class: b.className,
                    text: b.innerText?.trim(),
                    disabled: b.disabled || b.getAttribute('disabled'),
                    visible: b.offsetParent !== null,
                }))
            }));

            // 方法3: 全局找所有可见的包含"确认"或"确定"文字的元素
            results.confirm_candidates = [];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (text === '确认' || text === '确定' || text === '完成') {
                    const el = node.parentElement;
                    if (el && el.offsetParent !== null) {
                        results.confirm_candidates.push({
                            tag: el.tagName,
                            class: el.className,
                            text: text,
                            visible: el.offsetParent !== null,
                            disabled: el.disabled || el.getAttribute('disabled'),
                            rect: JSON.stringify(el.getBoundingClientRect()),
                        });
                    }
                }
            }

            return results;
        }""")

        with open("output/diag_03_dialog_dom.json", "w", encoding="utf-8") as f:
            json.dump(dialog_dom, f, ensure_ascii=False, indent=2)
        print(f"✅ 弹窗 DOM 已保存到: output/diag_03_dialog_dom.json")
        print(f"  role_dialog 数量: {len(dialog_dom.get('role_dialogs', []))}")
        print(f"  weui_dialog 数量: {len(dialog_dom.get('weui_dialogs', []))}")
        print(f"  确认按钮候选: {len(dialog_dom.get('confirm_candidates', []))}")

        for c in dialog_dom.get('confirm_candidates', []):
            print(f"    → [{c['tag']}] class='{c['class']}' text='{c['text']}' visible={c['visible']} disabled={c['disabled']}")

        # === 阶段4: 尝试直接用 JS 点击确认按钮 ===
        print("\n🔍 [阶段4] 尝试 JS 点击确认按钮...")
        clicked = page.evaluate("""() => {
            const texts = ['确认', '确定', '完成'];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (texts.includes(text)) {
                    const el = node.parentElement;
                    if (el && el.offsetParent !== null && !el.disabled) {
                        el.click();
                        return { clicked: true, tag: el.tagName, class: el.className, text };
                    }
                }
            }
            return { clicked: false };
        }""")
        print(f"  JS 点击结果: {clicked}")
        page.wait_for_timeout(2000)
        page.screenshot(path="output/diag_04_after_js_click.png")

        # === 阶段5: 分析原创声明区域 ===
        print("\n🔍 [阶段5] 分析原创声明区域...")
        original_dom = page.evaluate("""() => {
            const results = {};

            // 找包含"原创"文字的区域
            results.original_area = [];
            const allElements = document.querySelectorAll('*');
            for (const el of allElements) {
                const directText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join('');
                if (directText.includes('原创') || directText.includes('声明原创')) {
                    results.original_area.push({
                        tag: el.tagName,
                        class: el.className,
                        text: directText.slice(0, 100),
                        visible: el.offsetParent !== null,
                        parent_class: el.parentElement?.className,
                    });
                }
            }

            // 找所有 input[type=checkbox]
            results.checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"]')).map(cb => ({
                class: cb.className,
                checked: cb.checked,
                disabled: cb.disabled,
                name: cb.name,
                id: cb.id,
                visible: cb.offsetParent !== null,
                parent_text: cb.parentElement?.innerText?.trim()?.slice(0, 80),
            }));

            // 找所有 switch 类型控件
            results.switches = Array.from(document.querySelectorAll('[class*="switch"], [class*="Switch"]')).map(sw => ({
                tag: sw.tagName,
                class: sw.className,
                visible: sw.offsetParent !== null,
                aria_checked: sw.getAttribute('aria-checked'),
                parent_text: sw.parentElement?.innerText?.trim()?.slice(0, 80),
            }));

            return results;
        }""")

        with open("output/diag_05_original_dom.json", "w", encoding="utf-8") as f:
            json.dump(original_dom, f, ensure_ascii=False, indent=2)
        print(f"✅ 原创声明 DOM 已保存到: output/diag_05_original_dom.json")
        print(f"  原创相关元素: {len(original_dom.get('original_area', []))}")
        print(f"  Checkbox 数量: {len(original_dom.get('checkboxes', []))}")
        print(f"  Switch 控件数量: {len(original_dom.get('switches', []))}")

        for sw in original_dom.get('switches', []):
            print(f"    → [{sw['tag']}] class='{sw['class']}' aria_checked={sw['aria_checked']} visible={sw['visible']} parent='{sw['parent_text']}'")

        for cb in original_dom.get('checkboxes', []):
            print(f"    → [INPUT] id='{cb['id']}' class='{cb['class']}' checked={cb['checked']} visible={cb['visible']} parent='{cb['parent_text']}'")

        page.screenshot(path="output/diag_06_original_area.png")

        print("\n🎉 诊断完成！请查看 output/diag_*.json 和 output/diag_*.png 文件")
        print("按 Enter 退出...")
        input()
        browser.close()

if __name__ == "__main__":
    diagnose()

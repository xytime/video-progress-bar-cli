"""
微信视频号合集 DOM 结构探针
[Claude_Sonnet_4.6_Thinking_planning]

用法：
    python scratch/dump_collection_dom.py
"""

import sys
import time
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dom_dump")

OUT_DIR = PROJECT_ROOT / "output" / "test_collection"
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = PROJECT_ROOT / "output" / "wechat_state.json"
WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"


def ss(page, name):
    path = OUT_DIR / f"{time.strftime('%H%M%S')}_{name}.png"
    page.screenshot(path=str(path))
    log.info(f"📸 {path.name}")


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--window-size=1280,900"]
    )
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 900},
        storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => false})")
    page = ctx.new_page()

    log.info("Navigating...")
    page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(4000)
    ss(page, "00_loaded")

    # ── 1. 全量 class 扫描「合集」相关元素 ───────────────────────────────────
    log.info("=== DOM PROBE 1: All elements containing '合集' ===")
    result = page.evaluate("""() => {
        function getPath(el) {
            const parts = [];
            while (el && el !== document.body) {
                let desc = el.tagName.toLowerCase();
                if (el.id) desc += '#' + el.id;
                if (el.className && typeof el.className === 'string')
                    desc += '.' + el.className.trim().replace(/\\s+/g, '.');
                parts.unshift(desc);
                el = el.parentElement;
            }
            return parts.join(' > ');
        }
        const all = Array.from(document.querySelectorAll('*'));
        return all
            .filter(el => el.childNodes.length === 1 && el.firstChild?.nodeType === 3
                         && el.innerText?.includes('合集'))
            .map(el => ({
                tag: el.tagName,
                text: el.innerText?.trim().slice(0, 40),
                classes: el.className,
                path: getPath(el),
            }));
    }""")
    for r in result:
        log.info(f"  TAG={r['tag']} TEXT={r['text']!r}")
        log.info(f"    class: {r['classes']}")
        log.info(f"    path:  {r['path'][:120]}")
        log.info("")

    # ── 2. 找「选择合集」下拉控件 ───────────────────────────────────────────
    log.info("=== DOM PROBE 2: Dropdown/select near '合集' ===")
    result2 = page.evaluate("""() => {
        // 找包含"合集"的 label 的 form row，然后找其 sibling/child 下拉触发器
        const rows = Array.from(document.querySelectorAll('*')).filter(el =>
            el.innerText?.includes('添加到合集') && el.children.length > 0
        );
        return rows.slice(0, 5).map(row => ({
            tag: row.tagName,
            classes: row.className,
            html: row.outerHTML.slice(0, 600),
        }));
    }""")
    for r in result2:
        log.info(f"  TAG={r['tag']} class={r['classes']}")
        log.info(f"  HTML:\n{r['html']}")
        log.info("")

    # ── 3. 直接点击「选择合集」下拉，然后 dump DOM 变化 ─────────────────────
    log.info("=== DOM PROBE 3: Click '选择合集' and dump opened dropdown ===")

    # 用 text 定位，强制点击
    try:
        collection_row = page.locator("text=添加到合集").first
        log.info(f"  '添加到合集' found: {collection_row.count() > 0}")
        if collection_row.count() > 0:
            # 找旁边的下拉容器
            parent = collection_row.locator("xpath=ancestor::*[contains(@class,'form') or contains(@class,'item') or contains(@class,'row')][1]")
            log.info(f"  Parent count: {parent.count()}")
            if parent.count() > 0:
                log.info(f"  Parent HTML: {parent.first.inner_html()[:400]}")
    except Exception as e:
        log.warning(f"  Error: {e}")

    # 直接用 JS 找到「选择合集」元素并点击
    log.info("  Trying JS click on '选择合集'...")
    click_result = page.evaluate("""() => {
        // 找到 innerText 包含"选择合集"的元素
        const el = Array.from(document.querySelectorAll('*')).find(e =>
            e.innerText?.trim() === '选择合集' || e.innerText?.includes('选择合集')
        );
        if (!el) return {found: false};
        const r = el.getBoundingClientRect();
        return {
            found: true,
            tag: el.tagName,
            classes: el.className,
            x: r.left + r.width/2,
            y: r.top + r.height/2,
            outerHTML: el.outerHTML.slice(0, 300),
        };
    }""")
    log.info(f"  '选择合集' element: {click_result}")

    if click_result.get('found'):
        page.mouse.click(click_result['x'], click_result['y'])
        page.wait_for_timeout(1500)
        ss(page, "03_after_collection_click")

        # Dump whatever appeared
        log.info("=== DOM PROBE 4: DOM after dropdown click ===")
        after_dom = page.evaluate("""() => {
            // 找所有可能的下拉列表容器（新出现的）
            const candidates = Array.from(document.querySelectorAll('*')).filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 100 && r.height > 50 && r.top > 100 && el.children.length > 0
                    && (el.className?.includes('dropdown') || el.className?.includes('select')
                        || el.className?.includes('popup') || el.className?.includes('list')
                        || el.className?.includes('menu') || el.className?.includes('panel'));
            });
            return candidates.slice(0, 10).map(el => ({
                tag: el.tagName,
                classes: el.className,
                text: el.innerText?.trim().slice(0, 100),
                html: el.outerHTML.slice(0, 500),
            }));
        }""")
        for r in after_dom:
            log.info(f"  TAG={r['tag']} class={r['classes']}")
            log.info(f"  text: {r['text']!r}")
            log.info(f"  html: {r['html'][:300]}")
            log.info("")

        # 全部 li 元素
        li_dump = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('li')).map(li => ({
                classes: li.className,
                text: li.innerText?.trim().slice(0, 60),
                visible: li.offsetParent !== null,
            })).filter(li => li.visible);
        }""")
        log.info(f"=== All visible <li> elements after click ({len(li_dump)}) ===")
        for li in li_dump:
            log.info(f"  class={li['classes']!r} text={li['text']!r}")

        # 把完整 body HTML 保存到文件
        body_html = page.content()
        dump_path = OUT_DIR / "dom_after_click.html"
        dump_path.write_text(body_html, encoding="utf-8")
        log.info(f"\n  Full HTML saved: {dump_path}")

    log.info("\n⏸  Keeping open 8s for manual inspection...")
    page.wait_for_timeout(8000)
    browser.close()
    log.info("Done.")

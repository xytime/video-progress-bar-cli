"""
微信合集下拉 DOM 探针 v2 - 使用正确选择器点击并 dump 结果
[Claude_Sonnet_4.6_Thinking_planning]
"""
import sys, time, logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dom_probe_v2")

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
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except: pass
    page.wait_for_timeout(4000)
    ss(page, "v2_00_loaded")

    # ── Step1: 用正确 selector 找触发器 ─────────────────────────────────────
    log.info("=== Finding trigger via .post-album-display-wrap ===")
    trigger = page.locator(".post-album-display-wrap").first
    log.info(f"  Found: count={trigger.count()}, visible={trigger.is_visible() if trigger.count() > 0 else 'N/A'}")

    if trigger.count() == 0:
        # 兜底
        trigger = page.locator("div[class*='post-album']").first
        log.info(f"  Fallback post-album: count={trigger.count()}")

    if trigger.count() == 0:
        # 用 text + xpath 父级
        trigger = page.locator("text=添加到合集").locator("xpath=following-sibling::div//div[contains(@class,'display')]").first
        log.info(f"  Fallback sibling: count={trigger.count()}")

    # ── Step2: 也输出整个 .post-album-wrap 的完整 HTML ──────────────────────
    full_html = page.evaluate("""() => {
        const el = document.querySelector('.post-album-wrap');
        return el ? el.outerHTML : 'NOT FOUND';
    }""")
    log.info(f"=== .post-album-wrap full HTML ===\n{full_html[:2000]}")
    (OUT_DIR / "post_album_wrap.html").write_text(full_html, encoding="utf-8")

    # ── Step3: 点击触发器 ────────────────────────────────────────────────────
    if trigger.count() > 0:
        log.info(f"Clicking trigger: {trigger.first.get_attribute('class')!r}")
        trigger.first.click()
        page.wait_for_timeout(2000)
        ss(page, "v2_01_after_click")

        # dump 点击后所有新出现的元素
        log.info("=== DOM after click: looking for popup/dropdown ===")
        after = page.evaluate("""() => {
            // 找所有 visible 且 position:fixed 或 absolute 的浮层
            return Array.from(document.querySelectorAll('*')).filter(el => {
                if (!el.offsetParent && el.tagName !== 'BODY') return false;
                const style = window.getComputedStyle(el);
                const pos = style.position;
                const display = style.display;
                if (display === 'none') return false;
                return (pos === 'fixed' || pos === 'absolute') && el.clientHeight > 30;
            }).map(el => ({
                tag: el.tagName,
                classes: el.className,
                id: el.id,
                text: el.innerText?.trim().slice(0, 150),
                html: el.outerHTML.slice(0, 600),
            }));
        }""")
        log.info(f"  {len(after)} floating elements found after click")
        for r in after:
            log.info(f"  [{r['tag']}] class={r['classes']!r}")
            log.info(f"  text: {r['text']!r}")
            log.info(f"  html: {r['html'][:400]}")
            log.info("")

        # 保存完整页面 HTML
        full_page_html = page.content()
        p_html = OUT_DIR / "dom_after_click_v2.html"
        p_html.write_text(full_page_html, encoding="utf-8")
        log.info(f"Full HTML saved: {p_html}")

        # grep 有哪些 li, option 可见
        log.info("=== Visible list items / options ===")
        items = page.evaluate("""() => {
            const tags = ['li', 'option', 'div[role="option"]'];
            const results = [];
            for (const sel of tags) {
                document.querySelectorAll(sel).forEach(el => {
                    if (el.offsetParent !== null) {
                        results.push({
                            tag: el.tagName,
                            classes: el.className,
                            text: el.innerText?.trim().slice(0, 80),
                        });
                    }
                });
            }
            return results;
        }""")
        log.info(f"  {len(items)} items")
        for it in items:
            log.info(f"  <{it['tag']}> class={it['classes']!r} text={it['text']!r}")

        # 检查是否有「新建合集」按钮
        log.info("=== Looking for 新建合集 button ===")
        new_btn = page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('*'));
            return all.filter(el => el.offsetParent !== null && (
                el.innerText?.includes('新建合集') || el.innerText?.includes('创建合集') || el.innerText?.includes('新建')
            )).map(el => ({
                tag: el.tagName,
                classes: el.className,
                text: el.innerText?.trim().slice(0, 80),
                html: el.outerHTML.slice(0, 300),
            }));
        }""")
        for b in new_btn:
            log.info(f"  [{b['tag']}] {b['classes']!r} text={b['text']!r}")
            log.info(f"    html: {b['html'][:200]}")

    log.info("\n⏸  Keeping open 10s for manual inspection...")
    page.wait_for_timeout(10000)
    browser.close()
    log.info("Done.")

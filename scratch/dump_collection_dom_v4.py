"""
微信合集 DOM 探针 v4 - iframe 内容探测
[Claude_Sonnet_4.6_Thinking_planning]
"""
import sys, time, logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dom_v4")

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

    page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded")
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except: pass
    page.wait_for_timeout(4000)

    # ── 点击前：列出所有 frames ────────────────────────────────────────────
    log.info("=== Frames BEFORE click ===")
    for i, frame in enumerate(page.frames):
        log.info(f"  Frame[{i}]: url={frame.url!r} name={frame.name!r}")

    # ── 点击合集触发器 ─────────────────────────────────────────────────────
    trigger = page.locator(".post-album-display-wrap").first
    trigger.click()

    # ── 等下拉出现 ─────────────────────────────────────────────────────────
    page.wait_for_selector("text=创建新合集", timeout=5000)
    page.wait_for_timeout(500)
    ss(page, "v4_01_dropdown_open")

    # ── 点击后：列出所有 frames ────────────────────────────────────────────
    log.info("\n=== Frames AFTER click ===")
    for i, frame in enumerate(page.frames):
        log.info(f"  Frame[{i}]: url={frame.url!r} name={frame.name!r}")
        try:
            has_create = "创建新合集" in (frame.content() or "")
            has_ai = "AI如何" in (frame.content() or "")
            log.info(f"    → has '创建新合集': {has_create}, has 'AI如何': {has_ai}")
            if has_create or has_ai:
                log.info(f"    *** TARGET FRAME FOUND ***")
                # Save this frame's HTML
                frame_html = frame.content()
                fname = OUT_DIR / f"target_frame_{i}.html"
                fname.write_text(frame_html, encoding="utf-8")
                log.info(f"    Saved: {fname}")

                # Dump relevant elements from this frame
                items = frame.evaluate("""() => {
                    return Array.from(document.querySelectorAll('*'))
                        .filter(el => el.innerText?.includes('创建新合集')
                                   || el.innerText?.includes('共') && el.innerText?.includes('个内容'))
                        .map(el => ({
                            tag: el.tagName,
                            classes: el.className,
                            text: el.innerText?.trim().slice(0, 100),
                            html: el.outerHTML.slice(0, 500),
                        }));
                }""")
                log.info(f"    Items in frame: {len(items)}")
                for it in items[:10]:
                    log.info(f"      [{it['tag']}] classes={it['classes']!r}")
                    log.info(f"        text: {it['text']!r}")
                    log.info(f"        html: {it['html'][:300]}")
        except Exception as e:
            log.warning(f"    Frame error: {e}")

    # ── Playwright frame-aware selector dump ──────────────────────────────
    log.info("\n=== Playwright frame-aware locator for 创建新合集 ===")
    create_loc = page.get_by_text("创建新合集", exact=True)
    log.info(f"  count: {create_loc.count()}")
    for i in range(create_loc.count()):
        el = create_loc.nth(i)
        log.info(f"  [{i}] visible={el.is_visible()}")
        try:
            log.info(f"    tag: {el.evaluate('e => e.tagName')}")
            log.info(f"    classes: {el.evaluate('e => e.className')}")
            log.info(f"    outerHTML: {el.evaluate('e => e.outerHTML')[:400]}")
            # parent
            log.info(f"    parent HTML: {el.evaluate('e => e.parentElement?.outerHTML')[:400]}")
        except Exception as ex:
            log.warning(f"    Error: {ex}")

    # ── 找合集列表项 ───────────────────────────────────────────────────────
    log.info("\n=== Playwright: items with '共N个内容' ===")
    items_loc = page.locator("text=/共\\d+个内容/")
    log.info(f"  count: {items_loc.count()}")
    for i in range(min(5, items_loc.count())):
        el = items_loc.nth(i)
        try:
            parent_html = el.evaluate("e => e.closest('[class]')?.outerHTML")
            log.info(f"  [{i}] parent: {parent_html[:300] if parent_html else 'none'}")
        except Exception as ex:
            log.warning(f"  [{i}] error: {ex}")

    # ── 找「创建新合集」元素的所有祖先 class ──────────────────────────────
    log.info("\n=== 创建新合集 ancestor classes ===")
    try:
        create_el = page.get_by_text("创建新合集", exact=True).first
        ancestors = create_el.evaluate("""el => {
            const result = [];
            let cur = el;
            while (cur && cur !== document.body) {
                result.push({tag: cur.tagName, classes: cur.className});
                cur = cur.parentElement;
            }
            return result;
        }""")
        for a in ancestors:
            log.info(f"  {a['tag']}: {a['classes']!r}")
    except Exception as ex:
        log.warning(f"  Error: {ex}")

    log.info("\n⏸ Keeping open 10s...")
    page.wait_for_timeout(10000)
    browser.close()

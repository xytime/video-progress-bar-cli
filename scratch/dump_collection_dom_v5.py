"""
微信合集 DOM 探针 v5 - 精确 dump filter-wrap 内容
[Claude_Sonnet_4.6_Thinking_planning]
"""
import sys, time, logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dom_v5")

OUT_DIR = PROJECT_ROOT / "output" / "test_collection"
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = PROJECT_ROOT / "output" / "wechat_state.json"
WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"

def ss(page, name):
    path = OUT_DIR / f"{time.strftime('%H%M%S')}_{name}.png"
    page.screenshot(path=str(path))
    log.info(f"📸 {path.name}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False,
        args=["--disable-blink-features=AutomationControlled", "--window-size=1280,900"])
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

    # ── 点击合集触发器 ─────────────────────────────────────────────────────
    page.locator(".post-album-display-wrap").first.click()
    page.wait_for_selector("text=创建新合集", timeout=5000)
    page.wait_for_timeout(300)
    ss(page, "v5_01_open")

    # ── dump filter-wrap HTML ─────────────────────────────────────────────
    log.info("=== filter-wrap full HTML ===")
    fw = page.locator(".filter-wrap").first
    log.info(f"  filter-wrap count={fw.count()}, visible={fw.is_visible() if fw.count()>0 else 'N/A'}")
    if fw.count() > 0:
        html = fw.inner_html()
        log.info(f"  HTML ({len(html)} chars):")
        log.info(html[:3000])
        (OUT_DIR / "filter_wrap.html").write_text(html, encoding="utf-8")
        log.info("  Saved: filter_wrap.html")

    # ── dump post-album-list ──────────────────────────────────────────────
    log.info("\n=== post-album-list ===")
    pal = page.locator(".post-album-list").first
    log.info(f"  count={pal.count()}")
    if pal.count() > 0:
        log.info(f"  HTML: {pal.inner_html()[:1000]}")

    # ── 用 Playwright locator 找每个合集 item ─────────────────────────────
    log.info("\n=== Collection items via locator ===")
    # 找 filter-wrap 内的直接子 div (除 .create 之外)
    items = page.locator(".filter-wrap > div:not(.create)").all()
    log.info(f"  Direct children (not .create): {len(items)}")
    for i, item in enumerate(items[:3]):
        log.info(f"  item[{i}]: class={item.get_attribute('class')!r}")
        log.info(f"           innerText={item.inner_text()[:100]!r}")
        log.info(f"           innerHTML={item.inner_html()[:300]}")

    # ── 找单个 item 的结构 ────────────────────────────────────────────────
    log.info("\n=== First desc element parent chain ===")
    first_desc = page.locator(".desc").first
    if first_desc.count() > 0:
        ancestors = first_desc.evaluate("""el => {
            const chain = [];
            let cur = el;
            for (let i=0; i<5; i++) {
                if (!cur) break;
                chain.push({tag: cur.tagName, cls: cur.className, html: cur.outerHTML.slice(0,300)});
                cur = cur.parentElement;
            }
            return chain;
        }""")
        for a in ancestors:
            log.info(f"  {a['tag']} class={a['cls']!r}")
            log.info(f"    {a['html'][:200]}")

    # ── 「已有合集」点击测试 (不提交) ──────────────────────────────────────
    log.info("\n=== Testing click on existing collection ===")
    # 找第一个合集 item
    first_item = page.locator(".filter-wrap .post-album-item, .filter-wrap .album-item, .filter-wrap .item").first
    log.info(f"  .post-album-item count={page.locator('.post-album-item').count()}")
    log.info(f"  .album-item count={page.locator('.album-item').count()}")
    log.info(f"  .item count={page.locator('.item').count()}")

    # 用 desc 的祖父元素找 item
    item_via_desc = page.locator(".desc").first.locator("xpath=..")
    if item_via_desc.count() > 0:
        log.info(f"  parent of .desc: class={item_via_desc.get_attribute('class')!r}")
        grandparent = item_via_desc.locator("xpath=..")
        if grandparent.count() > 0:
            log.info(f"  grandparent: class={grandparent.get_attribute('class')!r}")
            log.info(f"  grandparent HTML: {grandparent.inner_html()[:400]}")

    log.info("\n⏸ Keeping open 10s...")
    page.wait_for_timeout(10000)
    browser.close()

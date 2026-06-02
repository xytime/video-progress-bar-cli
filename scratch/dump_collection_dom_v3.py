"""
微信合集 DOM 探针 v3 - 等下拉稳定后再 dump
[Claude_Sonnet_4.6_Thinking_planning]
"""
import sys, time, logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dom_v3")

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
    ss(page, "v3_00_loaded")

    # ── 点击合集触发器 ─────────────────────────────────────────────────────
    trigger = page.locator(".post-album-display-wrap").first
    log.info(f"Trigger count={trigger.count()}, visible={trigger.is_visible() if trigger.count() > 0 else 'N/A'}")
    trigger.first.click()

    # ── 等待「创建新合集」出现（最多 5 秒）───────────────────────────────
    log.info("Waiting for dropdown to appear (looking for '创建新合集' text)...")
    try:
        page.wait_for_selector("text=创建新合集", timeout=5000)
        log.info("  ✅ '创建新合集' appeared!")
    except Exception as e:
        log.warning(f"  Timeout waiting: {e}")
        # 也尝试其他信号
        try:
            page.wait_for_selector(".post-album-list, .album-list, [class*='album-item']", timeout=3000)
            log.info("  ✅ album-list appeared!")
        except:
            pass

    page.wait_for_timeout(500)  # 额外稳定等待
    ss(page, "v3_01_dropdown_stable")

    # ── 全量 DOM 转储 ────────────────────────────────────────────────────
    log.info("=== Full DOM dump after wait ===")
    result = page.evaluate("""() => {
        // 找所有包含"合集"文字、或 class 含 album 的元素
        const all = Array.from(document.querySelectorAll('*'));
        const relevant = all.filter(el => {
            const txt = el.innerText || '';
            const cls = (el.className || '').toString();
            return (txt.includes('创建新合集') || txt.includes('AI如何') || 
                    cls.includes('album') || cls.includes('collection'))
                   && el.children.length <= 10;
        });
        return relevant.map(el => ({
            tag: el.tagName,
            classes: el.className,
            text: (el.innerText||'').trim().slice(0, 100),
            html: el.outerHTML.slice(0, 500),
            visible: el.offsetParent !== null,
        }));
    }""")
    log.info(f"  Found {len(result)} relevant elements")
    for r in result:
        log.info(f"\n  [{r['tag']}] visible={r['visible']}")
        log.info(f"  classes: {r['classes']}")
        log.info(f"  text: {r['text']!r}")
        log.info(f"  html: {r['html'][:400]}")

    # ── 专项：找「创建新合集」元素及其父级 ──────────────────────────────
    log.info("\n=== 创建新合集 button element ===")
    create_info = page.evaluate("""() => {
        function getInfo(el) {
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {
                tag: el.tagName,
                classes: el.className,
                text: el.innerText?.trim().slice(0, 80),
                html: el.outerHTML.slice(0, 400),
                x: r.left + r.width/2,
                y: r.top + r.height/2,
                visible: el.offsetParent !== null,
            };
        }
        // 找所有包含"创建新合集"的元素
        const matches = Array.from(document.querySelectorAll('*'))
            .filter(el => el.childNodes.length <= 3 && el.innerText?.includes('创建新合集'));
        return matches.map(getInfo);
    }""")
    log.info(f"  {len(create_info)} matches")
    for c in create_info:
        log.info(f"  {c}")

    # ── 专项：找列表容器 ─────────────────────────────────────────────────
    log.info("\n=== List container ===")
    list_info = page.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('*'));
        return all.filter(el => {
            const txt = el.innerText || '';
            return txt.includes('共') && txt.includes('个内容') && el.children.length > 0;
        }).map(el => ({
            tag: el.tagName,
            classes: el.className,
            childCount: el.children.length,
            text: (el.innerText||'').trim().slice(0, 200),
            html: el.outerHTML.slice(0, 600),
        }));
    }""")
    for li in list_info:
        log.info(f"\n  [{li['tag']}] classes={li['classes']!r} children={li['childCount']}")
        log.info(f"  text: {li['text']!r}")
        log.info(f"  html: {li['html'][:500]}")

    # ── 保存稳定后 HTML ───────────────────────────────────────────────────
    html = page.content()
    p = OUT_DIR / "dom_stable_v3.html"
    p.write_text(html, encoding="utf-8")
    log.info(f"\nSaved: {p} ({len(html)} chars)")

    # grep 关键字
    for kw in ["创建新合集", "AI如何重塑", "共9个内容", "post-album-list", "album-item"]:
        idx = html.find(kw)
        if idx >= 0:
            log.info(f"  ✅ '{kw}' found at {idx}: ...{html[max(0,idx-50):idx+100]}...")
        else:
            log.info(f"  ❌ '{kw}' NOT in HTML")

    log.info("\n⏸ Keeping open 10s...")
    page.wait_for_timeout(10000)
    browser.close()

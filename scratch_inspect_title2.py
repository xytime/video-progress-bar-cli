"""
扩大范围：dump 所有 input/textarea + 所有 JS bundle，写入文件供分析
"""
from playwright.sync_api import sync_playwright
import re, json
from pathlib import Path

STATE = "output/wechat_state.json"
VIDEO = "output/zJ0V9gvK5FU.mp4"
OUT   = Path("output/title_inspect")
OUT.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        storage_state=STATE,
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()

    js_responses = {}
    def capture(r):
        url = r.url
        if ".js" in url and ("channels.weixin" in url or "res.wx.qq.com" in url):
            js_responses[url] = None
    page.on("response", capture)

    page.goto("https://channels.weixin.qq.com/platform/post/create", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    with page.expect_file_chooser(timeout=10000) as fc:
        page.locator("[class*='upload']:not(div>div)").first.click()
    fc.value.set_files(VIDEO)
    
    for _ in range(30):
        page.wait_for_timeout(5000)
        btn = page.locator("button:has-text('发表')").first
        if btn.count() > 0 and btn.get_attribute("disabled") is None:
            print("Upload complete.")
            break
        print("Uploading...")

    # Dump ALL inputs on page
    all_inputs = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('input, textarea')).map(el => {
            const attrs = {};
            for(const a of el.attributes) attrs[a.name] = a.value;
            return { tag: el.tagName, attrs, placeholder: el.placeholder, outerHTML: el.outerHTML.slice(0,300) };
        });
    }""")
    Path("output/all_inputs.json").write_text(json.dumps(all_inputs, ensure_ascii=False, indent=2))
    print(f"Found {len(all_inputs)} inputs. See output/all_inputs.json")

    # Dump all JS bundle URLs  
    print("\nJS bundle URLs:")
    for url in js_responses:
        print(" ", url)

    # Fetch each JS bundle and grep for title/validation rules
    keywords = ['短标题', 'shortTitle', 'short_title', 'titleLen', 'titleLimit',
                'maxLength', 'minLength', '半角', '全角', 'ascii', 'ASCII',
                'pattern', 'validate.*title', 'title.*validate',
                r'\b6\b.*\b16\b', r'\b16\b.*\b6\b', '28']
    
    for url in list(js_responses.keys()):
        try:
            content = page.evaluate(f"""async () => {{
                const r = await fetch('{url}');
                return r.text();
            }}""")
            fname = url.split("/")[-1].split("?")[0]
            (OUT / fname).write_text(content, encoding="utf-8")
            
            # Search patterns
            hits = []
            for kw in keywords:
                for m in re.finditer(rf'.{{0,100}}{kw}.{{0,100}}', content):
                    hits.append(m.group(0).strip())
            if hits:
                print(f"\n=== {fname} ({len(hits)} hits) ===")
                for h in hits[:30]:
                    print(f"  {h}")
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")

    browser.close()
    print("\nDone.")

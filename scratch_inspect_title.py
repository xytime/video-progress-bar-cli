"""
上传一个视频后，在发布页面对短标题 input 进行深度 DOM 检查：
  - input 的所有 attributes (maxlength, minlength, pattern, data-*, etc.)
  - 对应的 Vue 组件绑定 (data-v-*)
  - 相邻的提示文字 (字数限制说明、错误提示)
  - 搜索页面 bundle JS 中所有 /title|短标题|shortTitle/ 相关验证逻辑
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import json, re

STATE = "output/wechat_state.json"
VIDEO = "output/zJ0V9gvK5FU.mp4"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        storage_state=STATE,
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()

    # ── 收集页面加载的所有 JS bundle URLs ──
    js_urls = []
    page.on("response", lambda r: js_urls.append(r.url) if ".js" in r.url and "channels.weixin" in r.url else None)

    page.goto("https://channels.weixin.qq.com/platform/post/create", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # ── 上传视频，触发表单出现 ──
    with page.expect_file_chooser(timeout=10000) as fc:
        page.locator("[class*='upload']:not(div>div)").first.click()
    fc.value.set_files(VIDEO)

    # 等待上传完成
    for _ in range(30):
        page.wait_for_timeout(5000)
        btn = page.locator("button:has-text('发表')").first
        if btn.count() > 0 and btn.get_attribute("disabled") is None:
            print("Upload complete.")
            break
        print("Still uploading...")

    # ── 1. 找到短标题 input，dump 全部 attributes ──
    print("\n===== SHORT TITLE INPUT ATTRIBUTES =====")
    result = page.evaluate("""() => {
        const inputs = Array.from(document.querySelectorAll('input, textarea'));
        const candidates = inputs.filter(el => {
            const ph = (el.placeholder || '').toLowerCase();
            return ph.includes('标题') || ph.includes('title') || ph.includes('概括') || ph.includes('6-16') || ph.includes('28');
        });
        return candidates.map(el => {
            const attrs = {};
            for(const a of el.attributes) attrs[a.name] = a.value;
            return {
                tag: el.tagName,
                attrs,
                value: el.value,
                outerHTML: el.outerHTML.slice(0, 500),
            };
        });
    }""")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # ── 2. 找标题周围的说明文字（字数限制、错误提示）──
    print("\n===== TITLE AREA SURROUNDING TEXT =====")
    surrounding = page.evaluate("""() => {
        const inputs = Array.from(document.querySelectorAll('input, textarea'));
        const target = inputs.find(el => {
            const ph = (el.placeholder || '').toLowerCase();
            return ph.includes('标题') || ph.includes('概括') || ph.includes('6-16') || ph.includes('28');
        });
        if (!target) return 'TARGET NOT FOUND';
        // 向上找 3 层，输出 innerText
        let el = target;
        const parts = [];
        for(let i = 0; i < 4; i++) {
            el = el.parentElement;
            if(!el) break;
            parts.push({ level: i+1, class: el.className, text: el.innerText.slice(0, 300) });
        }
        return parts;
    }""")
    print(json.dumps(surrounding, ensure_ascii=False, indent=2))

    # ── 3. 从 JS bundle 中搜索验证逻辑 ──
    print("\n===== SEARCHING JS BUNDLES FOR TITLE VALIDATION =====")
    print(f"Found {len(js_urls)} JS URLs loaded from WeChat.")
    for url in js_urls:
        if any(kw in url for kw in ['chunk', 'app', 'index', 'post', 'create', 'video']):
            try:
                content = page.evaluate(f"""async () => {{
                    const r = await fetch('{url}');
                    return r.text();
                }}""")
                # 搜索标题相关规则
                matches = re.findall(r'.{{0,80}}(?:短标题|shortTitle|titleValidator|maxLength.*title|title.*max|半角|全角|ascii|checkTitle|6.16|28字|[\u77ed\u6807\u9898]).{{0,80}}', content)
                if matches:
                    print(f"\nURL: {url}")
                    for m in matches[:20]:
                        print(f"  >>> {m}")
            except Exception as e:
                pass

    browser.close()

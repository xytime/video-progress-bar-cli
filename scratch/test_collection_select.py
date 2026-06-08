"""
合集选择集成测试脚本
[Claude_Sonnet_4.6_Thinking_planning]

# Modification History
| Version | Date       | Author                              | Description           |
|---------|------------|-------------------------------------|-----------------------|
| 1.0.0   | 2026-06-02 | Claude_Sonnet_4.6_Thinking_planning | 初始创建              |

测试目标：
1. 以 --draft 模式（不提交）验证合集选择是否成功触达 UI
2. 验证「已存在合集」选中逻辑（去重）
3. 验证「不存在合集」新建逻辑
4. 对每个关键步骤截图，存入 output/test_collection/

用法：
    cd /Volumes/EXT2T/.../Video-precessing
    python scratch/test_collection_select.py [--collection 科技] [--skip-upload]
"""

import sys
import os
import argparse
import logging
import time
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from playwright.sync_api import sync_playwright
from human_mouse import human_click, _human_delay

# ── 日志 ───────────────────────────────────────────────────────────────────────
OUT_DIR = PROJECT_ROOT / "output" / "test_collection"
OUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(OUT_DIR / "test_run.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("test_collection")

WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"
STATE_FILE = PROJECT_ROOT / "output" / "wechat_state.json"

# ── 默认测试资产 ──────────────────────────────────────────────────────────────
DEFAULT_VIDEO  = str(PROJECT_ROOT / "output" / "-QQLU7ksuHQ_vertical.mp4")
DEFAULT_COPY   = str(PROJECT_ROOT / "output" / "-QQLU7ksuHQ_copy.txt")
DEFAULT_TITLE  = str(PROJECT_ROOT / "output" / "-QQLU7ksuHQ_title.txt")
DEFAULT_COVER  = str(PROJECT_ROOT / "output" / "-QQLU7ksuHQ_cover.jpg")


def screenshot(page, name: str):
    """保存截图，文件名自动加时间戳"""
    ts = time.strftime("%H%M%S")
    path = OUT_DIR / f"{ts}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        log.info(f"📸 Screenshot → {path.name}")
    except Exception as e:
        log.warning(f"Screenshot failed: {e}")
    return path


def try_select_collection(page, collection_name: str) -> str:
    """
    尝试在微信合集下拉框中选择合集。
    返回值：'selected_existing' | 'created_new' | 'failed'
    """
    log.info(f"\n{'='*60}")
    log.info(f"🎯 Testing collection: {collection_name!r}")
    log.info(f"{'='*60}")

    # ── Step 1: 定位"合集"触发按钮 ──────────────────────────────────────────
    log.info("Step 1: Locating collection dropdown trigger...")
    screenshot(page, "01_before_collection_click")

    collection_trigger = None

    # 方法 A: 遍历 form items
    form_items = page.locator(".weui-desktop-form__item")
    count = form_items.count()
    log.debug(f"  Found {count} form items")
    for i in range(count):
        item = form_items.nth(i)
        text = item.inner_text() or ""
        log.debug(f"  Form item [{i}] text: {text[:60]!r}")
        if "合集" in text:
            log.info(f"  ✅ Found '合集' in form item [{i}]")
            trigger = item.locator(
                ".weui-desktop-dropdown__trigger, .weui-desktop-select__trigger"
            ).first
            if trigger.count() == 0:
                trigger = item.locator("div[class*='select'], div[class*='dropdown']").first
            if trigger.count() > 0 and trigger.is_visible():
                collection_trigger = trigger
                log.info("  ✅ Trigger found within form item")
                break

    # 方法 B: 兜底 locators
    if not collection_trigger:
        log.warning("  Method A failed → trying fallback locators...")
        fallbacks = [
            page.locator(".weui-desktop-dropdown__trigger:near(:text('添加到合集'), 100)").first,
            page.locator(".weui-desktop-dropdown__trigger:near(:text('合集'), 100)").first,
            page.locator("text=添加到合集").locator("xpath=..").locator("div").first,
        ]
        for fb in fallbacks:
            try:
                if fb.count() > 0 and fb.is_visible():
                    collection_trigger = fb
                    log.info("  ✅ Trigger found via fallback")
                    break
            except Exception as e:
                log.debug(f"  Fallback failed: {e}")

    # 方法 C: JS 全局扫描
    if not collection_trigger:
        log.warning("  Method B failed → JS scan...")
        result = page.evaluate("""() => {
            const items = document.querySelectorAll('.weui-desktop-form__item');
            for (const item of items) {
                if (item.innerText.includes('合集')) {
                    const el = item.querySelector('[class*="dropdown"], [class*="select"]');
                    if (el) {
                        const r = el.getBoundingClientRect();
                        return {found: true, x: r.left + r.width/2, y: r.top + r.height/2, text: el.innerText};
                    }
                }
            }
            return {found: false};
        }""")
        log.info(f"  JS scan result: {result}")

    if not collection_trigger:
        log.error("  ❌ Cannot find collection trigger after all methods")
        screenshot(page, "FAIL_no_trigger")

        # 打印页面所有 form items 文本供调试
        all_text = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.weui-desktop-form__item'))
                .map((el, i) => `[${i}] ${el.innerText.slice(0, 80)}`).join('\\n');
        }""")
        log.info(f"  All form items:\n{all_text}")
        return "failed"

    # ── Step 2: 点击展开下拉菜单 ────────────────────────────────────────────
    log.info("Step 2: Clicking collection trigger...")
    try:
        collection_trigger.click(timeout=2000)
    except Exception:
        try:
            collection_trigger.evaluate("node => node.click()")
        except Exception as e:
            log.error(f"  ❌ Failed to click trigger: {e}")
            return "failed"

    page.wait_for_timeout(1000)
    screenshot(page, "02_dropdown_opened")

    # ── Step 3: 检查下拉列表 ────────────────────────────────────────────────
    log.info("Step 3: Inspecting dropdown list...")
    list_container = page.locator(".weui-desktop-dropdown__list").first

    # 打印所有可见选项
    try:
        all_options = page.evaluate("""() => {
            const list = document.querySelector('.weui-desktop-dropdown__list');
            if (!list) return 'NO LIST FOUND';
            return Array.from(list.querySelectorAll('li'))
                .map((li, i) => `[${i}] checked=${!!li.querySelector('input:checked')} ${li.innerText.trim().slice(0, 50)}`)
                .join('\\n');
        }""")
        log.info(f"  Dropdown options:\n{all_options}")
    except Exception as e:
        log.warning(f"  Could not enumerate options: {e}")

    target_option = None
    if list_container.count() > 0 and list_container.is_visible():
        opt = list_container.locator(f"li:has-text('{collection_name}')").first
        if opt.count() > 0 and opt.is_visible():
            target_option = opt
            log.info(f"  ✅ Found existing collection: {collection_name!r}")

    # ── Step 4a: 选中已存在合集 ─────────────────────────────────────────────
    if target_option:
        log.info(f"Step 4a: Selecting existing collection {collection_name!r}...")
        try:
            cb = target_option.locator("input[type='checkbox']").first
            if cb.count() > 0:
                is_checked = cb.is_checked()
                log.info(f"  Checkbox found, currently checked={is_checked}")
                if not is_checked:
                    human_click(page, cb)
                    page.wait_for_timeout(500)
                    is_checked_after = cb.is_checked()
                    log.info(f"  Checkbox after click: checked={is_checked_after}")
                    if is_checked_after:
                        log.info("  ✅ SUCCESS: Existing collection selected")
                        screenshot(page, "03a_existing_selected")
                        page.keyboard.press("Escape")
                        return "selected_existing"
                    else:
                        log.warning("  ⚠️ Checkbox did not check after click")
                else:
                    log.info("  ℹ️ Checkbox already checked (previously selected)")
                    screenshot(page, "03a_already_checked")
                    page.keyboard.press("Escape")
                    return "selected_existing"
            else:
                log.info("  No checkbox found, clicking item directly")
                ok = human_click(page, target_option)
                if not ok:
                    target_option.evaluate("node => node.click()")
                page.wait_for_timeout(500)
                screenshot(page, "03a_item_clicked")
                return "selected_existing"
        except Exception as e:
            log.error(f"  ❌ Failed to select existing: {e}")
            screenshot(page, "FAIL_select_existing")
            return "failed"

    # ── Step 4b: 创建新合集 ──────────────────────────────────────────────────
    log.info(f"Step 4b: Collection {collection_name!r} NOT found → creating new...")
    screenshot(page, "03b_before_create")

    create_btn = None
    for btn_text in ["新建合集", "创建合集", "新建", "创建"]:
        btn = page.locator(f"button:has-text('{btn_text}')").first
        if btn.count() > 0 and btn.is_visible():
            create_btn = btn
            log.info(f"  Found create button: {btn_text!r}")
            break

    if not create_btn:
        log.warning("  Create button not found via text, trying JS...")
        result_js = page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, a, div[role="button"]'));
            const target = btns.find(b => (b.innerText.includes('新建') || b.innerText.includes('创建')) && b.offsetParent !== null);
            if (target) {
                const r = target.getBoundingClientRect();
                return {ok: true, x: r.left + r.width/2, y: r.top + r.height/2, text: target.innerText};
            }
            return {ok: false};
        }""")
        log.info(f"  JS create button: {result_js}")
        if result_js and result_js.get("ok"):
            page.mouse.click(result_js["x"], result_js["y"])
            log.info("  Clicked create button via JS coordinates")
        else:
            log.error("  ❌ Cannot find create button")
            screenshot(page, "FAIL_no_create_btn")
            page.mouse.click(0, 0)
            return "failed"
    else:
        ok = human_click(page, create_btn)
        if not ok:
            create_btn.evaluate("node => node.click()")

    page.wait_for_timeout(1500)
    screenshot(page, "04b_create_clicked")

    # ── Step 5: 填写新建 Modal ───────────────────────────────────────────────
    log.info("Step 5: Filling new collection dialog...")
    modal = page.locator(".weui-desktop-dialog, div[role='dialog']").first
    if modal.count() > 0 and modal.is_visible():
        log.info("  ✅ Dialog visible")
        screenshot(page, "05_dialog_visible")

        import re as _re
        cleaned_name = _re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', collection_name).strip()[:15]
        log.info(f"  Cleaned collection name: {cleaned_name!r}")

        input_box = modal.locator(
            "input[type='text'], input[placeholder*='合集名称'], input[placeholder*='标题']"
        ).first

        if input_box.count() > 0:
            input_box.fill(cleaned_name)
            page.wait_for_timeout(500)
            log.info(f"  Filled input with: {cleaned_name!r}")
            screenshot(page, "06_dialog_filled")

            # 点确定（但这是测试，只截图不实际点击，避免创建真实合集）
            confirm_btn = None
            for bt in ["确定", "保存", "创建", "确认"]:
                btn = modal.locator(f"button:has-text('{bt}')").first
                if btn.count() > 0 and btn.is_visible():
                    confirm_btn = btn
                    log.info(f"  Found confirm button: {bt!r}")
                    break

            if confirm_btn:
                log.info(f"  ✅ Confirm button found: {confirm_btn.inner_text()!r}")
                log.info("  ⚠️  TEST MODE: NOT clicking confirm (avoid creating real collection)")
                screenshot(page, "07_ready_to_confirm_NOT_CLICKED")

                # 取消对话框
                cancel_btn = None
                for ct in ["取消", "关闭"]:
                    cb2 = modal.locator(f"button:has-text('{ct}')").first
                    if cb2.count() > 0 and cb2.is_visible():
                        cancel_btn = cb2
                        break
                if cancel_btn:
                    cancel_btn.click()
                    log.info("  Clicked cancel to close dialog")
                else:
                    page.keyboard.press("Escape")
                    log.info("  Pressed Escape to close dialog")

                return "created_new"
            else:
                log.error("  ❌ No confirm button found in dialog")
                screenshot(page, "FAIL_no_confirm")
                return "failed"
        else:
            log.error("  ❌ No input box in dialog")
            screenshot(page, "FAIL_no_input")
            return "failed"
    else:
        log.warning("  Dialog did not appear")
        screenshot(page, "FAIL_no_dialog")
        page.mouse.click(0, 0)
        return "failed"


def run_test(collection_name: str, skip_upload: bool = False):
    log.info("=" * 70)
    log.info(f"Collection Selection Test")
    log.info(f"Collection name: {collection_name!r}")
    log.info(f"Skip upload: {skip_upload}")
    log.info("=" * 70)

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # [Claude_Sonnet_4.6_Thinking_planning] 测试时显示浏览器，用户可观察
            args=[
                "--disable-web-security",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1280,900",
            ]
        )

        context_opts = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if STATE_FILE.exists():
            log.info(f"Loading session: {STATE_FILE}")
            context_opts["storage_state"] = str(STATE_FILE)
        else:
            log.error(f"No session state at {STATE_FILE}!")

        context = browser.new_context(**context_opts)
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
        """)

        page = context.new_page()

        # ── 导航到发布页 ────────────────────────────────────────────────────
        log.info(f"Navigating to: {WECHAT_CREATE_URL}")
        page.goto(WECHAT_CREATE_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(4000)
        screenshot(page, "00_page_loaded")

        current_url = page.url
        log.info(f"Current URL: {current_url}")
        if "login" in current_url:
            log.error("❌ Not logged in! Please run login first.")
            browser.close()
            return

        if not skip_upload:
            # ── 上传视频（必须先上传才能看到合集字段）────────────────────────
            log.info(f"Uploading video: {DEFAULT_VIDEO}")
            try:
                n_inputs = page.evaluate("() => document.querySelectorAll('input[type=\"file\"]').length")
                log.info(f"File inputs found: {n_inputs}")
                if n_inputs > 0:
                    file_input = page.locator("input[type='file']").first
                    file_input.set_input_files(DEFAULT_VIDEO)
                    log.info("Video upload triggered")
                    screenshot(page, "upload_triggered")
            except Exception as e:
                log.error(f"Upload failed: {e}")

            # ── 等待上传完成（最多 120s）───────────────────────────────────
            log.info("Waiting for upload to complete...")
            for i in range(24):  # 24 × 5s = 120s
                page.wait_for_timeout(5000)
                publish_btn = page.locator("button:has-text('发表')").first
                if publish_btn.count() > 0:
                    is_dis = publish_btn.get_attribute("disabled") is not None
                    log.info(f"  [{i+1}/24] Publish button visible, disabled={is_dis}")
                    if not is_dis:
                        log.info("  ✅ Upload complete (publish button enabled)")
                        break
                else:
                    log.info(f"  [{i+1}/24] Still uploading...")
            screenshot(page, "upload_complete")

            # 填描述（保持页面完整性）
            for selector in [".input-editor", "div[contenteditable='true']", "textarea"]:
                loc = page.locator(selector)
                if loc.count() > 0 and loc.first.is_visible():
                    try:
                        copy_text = Path(DEFAULT_COPY).read_text(encoding="utf-8")
                        loc.first.focus()
                        page.keyboard.press("Meta+A")
                        page.keyboard.insert_text(copy_text[:100] + " [TEST]")
                        log.info("Description filled")
                        break
                    except Exception:
                        pass

        # ── 测试 1：选择已存在合集（预期：selected_existing） ────────────
        log.info(f"\n{'#'*70}")
        log.info(f"# TEST 1: Select existing collection ({collection_name!r})")
        log.info(f"{'#'*70}")
        result1 = try_select_collection(page, collection_name)
        results["test1_existing"] = result1
        log.info(f"Result: {result1}")

        page.wait_for_timeout(2000)

        # ── 测试 2：同一名称再次选择（去重验证） ─────────────────────────
        log.info(f"\n{'#'*70}")
        log.info(f"# TEST 2: Same collection again (dedup test)")
        log.info(f"{'#'*70}")
        result2 = try_select_collection(page, collection_name)
        results["test2_dedup"] = result2
        log.info(f"Result: {result2}")

        page.wait_for_timeout(2000)

        # ── 测试 3：选择不存在的合集（预期：created_new，但不实际提交）─
        fake_name = "测试合集勿提交"
        log.info(f"\n{'#'*70}")
        log.info(f"# TEST 3: Non-existent collection ({fake_name!r})")
        log.info(f"{'#'*70}")
        result3 = try_select_collection(page, fake_name)
        results["test3_new_create"] = result3
        log.info(f"Result: {result3}")

        # ── 最终截图 ────────────────────────────────────────────────────────
        screenshot(page, "FINAL_state")

        # ── 汇总 ─────────────────────────────────────────────────────────────
        log.info("\n" + "=" * 70)
        log.info("📊 TEST SUMMARY")
        log.info("=" * 70)
        for k, v in results.items():
            icon = "✅" if v in ("selected_existing", "created_new") else "❌"
            log.info(f"  {icon} {k}: {v}")
        log.info("=" * 70)
        log.info(f"Screenshots saved to: {OUT_DIR}")
        log.info(f"Log saved to: {OUT_DIR / 'test_run.log'}")

        # [Claude_Sonnet_4.6_Thinking_planning] 测试完成后保持页面 5 秒让用户观察
        log.info("\n⏸  Keeping browser open for 5s for observation...")
        page.wait_for_timeout(5000)

        browser.close()
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collection selection integration test")
    parser.add_argument("--collection", default="科技", help="Collection name to test (default: 科技)")
    parser.add_argument("--skip-upload", action="store_true", help="Skip video upload (use if page already has video)")
    args = parser.parse_args()

    results = run_test(collection_name=args.collection, skip_upload=args.skip_upload)
    if results:
        all_ok = all(v in ("selected_existing", "created_new") for v in results.values())
        sys.exit(0 if all_ok else 1)
    else:
        sys.exit(1)

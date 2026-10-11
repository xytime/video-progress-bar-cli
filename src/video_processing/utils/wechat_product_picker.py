"""微信视频号发布页商品选择器实现。

实现 ProductPicker 契约协议，负责操作视频号实际发布页面（微前端/Iframe）完成商品选择、
弹窗确认、表单绑定完整性核查及清空取消动作。
严禁执行任何“发表”或“保存草稿”动作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-10-12 | Codex | 同一实际选中行分别保留商家商品 ID 与视频号挂载 ID，禁止用名称或列表序号映射。 |
| 1.2.0 | 2026-10-12 | Codex | 修复隐藏 iframe/Shadow DOM 定位；无 ID 卡片仅接受平台实际选中行及未变化表单证据。 |
| 1.1.0 | 2026-10-10 | Antigravity | 自动确认‘选择商品出现时机’弹窗，确保遮罩完全关闭且发表按钮无阻碍。 |
| 1.0.0 | 2026-10-10 | Antigravity | 初始实现：适配当前视频号微前端结构，支持完整商品查找、单选确认、表单回读与解绑。 |
"""

from __future__ import annotations

from time import monotonic
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from video_processing.core.wechat_product_policy import ProductIdentity, ProductLookup


class BindingIdentityUnavailable(RuntimeError):
    """页面未提供完整的实际商品身份；不能用配置补全。"""


# 每次执行均限定于同一 frame 的可见商品区域，不查询框架私有状态。
_DOM = r"""
const visible = e => !!e && !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
const text = e => (e?.innerText || '').trim();
const enabled = e => visible(e) && !e.disabled && e.getAttribute('aria-disabled') !== 'true';
const dialogs = () => Array.from(scope.querySelectorAll('.weui-desktop-dialog, .ant-modal, [role="dialog"]'))
    .filter(d => visible(d) && /从橱窗添加商品|选择商品出现时机/.test(text(d)));
const productDialogs = () => dialogs().filter(d => text(d).includes('从橱窗添加商品'));
const button = (d, re) => Array.from(d.querySelectorAll('button, .weui-desktop-btn')).find(b => enabled(b) && re.test(text(b)));
const binding = () => {
    const cards = Array.from(scope.querySelectorAll('.post-component-choose-wrap .choose-content')).filter(visible);
    const names = cards.flatMap(c => Array.from(c.querySelectorAll('.name')).filter(e => visible(e) && text(e)));
    if (names.length) {
        if (names.length !== 1 || cards.length !== 1) return {unknown: true};
        const card = cards[0], ids = new Set();
        for (const e of [card, ...card.querySelectorAll('[data-product-id], a[href]')]) {
            const id = e.getAttribute('data-product-id');
            if (id?.trim()) ids.add(id.trim());
            if (e.matches('a[href]')) {
                let u;
                try { u = new URL(e.getAttribute('href'), root.baseURI); } catch { return {unknown: true}; }
                for (const key of ['product_id', 'productId']) {
                    const value = u.searchParams.get(key);
                    if (value?.trim()) ids.add(value.trim());
                }
            }
        }
        return ids.size === 1 ? {product_id: [...ids][0], title: text(names[0])} : {unknown: true, missing_id: ids.size === 0, title: text(names[0])};
    }
    if (cards.some(c => text(c).includes('选择需要添加的商品')) ||
        Array.from(scope.querySelectorAll('.link-display-wrap')).some(e => visible(e) && text(e) === '选择链接'))
        return {unbound: true};
    return {unknown: true};
};
const selectedIdentity = () => {
    const ds = productDialogs();
    if (ds.length !== 1) return null;
    const rows = Array.from(ds[0].querySelectorAll('tr')).filter(r => visible(r) && r.querySelector('input[type="radio"]:checked'));
    if (rows.length !== 1) return null;
    const row = rows[0], ids = new Set();
    for (const e of [row, ...row.querySelectorAll('[data-product-id], .id-wrap')]) {
        const id = e.getAttribute('data-product-id') || (e.matches('.id-wrap') ? text(e) : '');
        if (id?.trim()) ids.add(id.trim());
    }
    // 简单表格兼容；radio.value 和 data-row-key 是橱窗行 ID，不能当作商品 ID。
    if (!ids.size && /^[A-Za-z0-9_-]+$/.test(text(row.cells[0]))) ids.add(text(row.cells[0]));
    const titleNode = row.querySelector('.title') || row.cells[1];
    const title = titleNode?.getAttribute('title')?.trim() || text(titleNode);
    const rowId = row.getAttribute('data-row-key'), radioId = row.querySelector('input[type="radio"]:checked')?.value;
    // 两个公开字段必须在同一实际选中行吻合；不把挂载 ID 替换为商家 ID。
    const platformId = rowId && /^\d+$/.test(rowId) && rowId === radioId ? rowId : null;
    if (rowId && radioId && rowId !== radioId) return null;
    return ids.size === 1 && title ? {product_id: [...ids][0], title, platform_product_id: platformId} : null;
};
const lookup = prod => {
    const ds = productDialogs();
    if (ds.length !== 1) return {status: 'IDENTITY_CONFLICT'};
    const rows = Array.from(ds[0].querySelectorAll('tr')).filter(visible);
    const matches = rows.filter(row => {
        const ids = [row, ...row.querySelectorAll('[data-product-id]')].map(e => e.getAttribute('data-product-id')).filter(Boolean);
        // 商品 ID 使用完整 token，不能让 123 匹配到 91234。
        const tokens = text(row).split(/[^A-Za-z0-9_-]+/);
        return ids.includes(prod.product_id) || tokens.includes(prod.product_id);
    });
    if (!matches.length) return {status: 'UNAVAILABLE'};
    if (matches.length !== 1) return {status: 'IDENTITY_CONFLICT'};
    const row = matches[0];
    const titles = [row, ...row.querySelectorAll('*')].filter(visible)
        .flatMap(e => [text(e), e.getAttribute('title')?.trim()]);
    if (!titles.includes(prod.title)) return {status: 'IDENTITY_CONFLICT'};
    const radio = row.querySelector('input[type="radio"]');
    if (!radio || radio.disabled || radio.getAttribute('aria-disabled') === 'true') return {status: 'UNAVAILABLE', matched: true};
    return {status: 'AVAILABLE', row, radio};
};
"""


class PlaywrightProductPicker:
    """方法内共享截止时间；实际身份只取自 DOM，不从本地目录推算。"""

    def __init__(self, page: Any, catalog=None, *, clock=monotonic) -> None:
        self.page = page
        self.clock = clock
        self._binding_attestation = None
        self.binding_identity_source = "FINAL_FORM_READBACK"
        self.binding_platform_product_id = None
        # catalog 仅保留调用兼容，不用于身份回读。

    def _get_content_frame(self) -> Any:
        # 无界微前端会保留隐藏的同名 iframe；当前可见控件优先。
        controls = self.page.locator('.post-component-choose-wrap:visible, .link-display-wrap:visible')
        if controls.count():
            return self.page
        frames = []
        for frame in getattr(self.page, "frames", []):
            if "content/post/create" in getattr(frame, "url", "") or getattr(frame, "name", "") == "content":
                if frame.frame_element().is_visible():
                    frames.append(frame)
        if len(frames) > 1:
            raise BindingIdentityUnavailable("PRODUCT_VISIBLE_FRAME_CONFLICT")
        return frames[0] if frames else self.page

    def _end(self, timeout_ms: int, cap_ms: int = 10000) -> float:
        if timeout_ms <= 0:
            raise TimeoutError("PRODUCT_OPERATION_TIMEOUT")
        return self.clock() + min(timeout_ms, cap_ms) / 1000

    def _remaining(self, end: float) -> int:
        remaining = int((end - self.clock()) * 1000)
        if remaining <= 0:
            raise TimeoutError("PRODUCT_OPERATION_TIMEOUT")
        return remaining

    def _eval(self, code: str, end: float, arg=None):
        try:
            ctx = self._get_content_frame()
            controls = ctx.locator('.post-component-choose-wrap:visible, .link-display-wrap:visible')
            if controls.count():
                if controls.evaluate_all('es => new Set(es.map(e => e.getRootNode())).size') != 1:
                    raise BindingIdentityUnavailable("PRODUCT_VISIBLE_ROOT_CONFLICT")
                anchor = controls.first
            else:
                anchor = ctx.locator("body").first
            # Locator 穿透公开 Shadow DOM，查询随后限定在该可见控件所属根。
            value = anchor.evaluate(
                "(root, arg) => {const scope = root.getRootNode();" + _DOM + code + "}", arg,
                timeout=self._remaining(end),
            )
        except PlaywrightTimeoutError as exc:
            raise TimeoutError("PRODUCT_OPERATION_TIMEOUT") from exc
        self._remaining(end)
        return value

    def _poll(self, code: str, end: float, arg=None):
        while True:
            value = self._eval(code, end, arg)
            if value:
                return value
            self.page.wait_for_timeout(min(50, self._remaining(end)))

    def _open(self, end: float):
        if self._eval("return productDialogs().length > 0;", end):
            return
        ctx = self._get_content_frame()
        try:
            if not self._eval("return Array.from(scope.querySelectorAll('.choosen-link-wrap')).some(e => visible(e) && text(e).includes('商品'));", end):
                ctx.get_by_text("选择链接", exact=True).click(timeout=self._remaining(end))
                ctx.get_by_text("商品", exact=True).click(timeout=self._remaining(end))
            ctx.get_by_text("选择需要添加的商品", exact=True).click(timeout=self._remaining(end))
        except PlaywrightTimeoutError as exc:
            raise TimeoutError("PRODUCT_OPERATION_TIMEOUT") from exc
        self._poll("return productDialogs().length > 0;", end)

    def read_binding(self, *, timeout_ms: int) -> ProductIdentity | None:
        end = self._end(timeout_ms)
        info = self._eval("return binding();", end)
        self.binding_identity_source = "FINAL_FORM_READBACK"
        self.binding_platform_product_id = None
        if info.get("unbound"):
            return None
        if self._binding_attestation is not None:
            actual = self._binding_attestation.evaluate("""e => {
                const cards = Array.from(e.scope.querySelectorAll('.post-component-choose-wrap .choose-content'))
                    .filter(n => !!n.getClientRects().length);
                const name = e.card.querySelector('.name');
                return e.valid && e.card.isConnected && cards.length === 1 && cards[0] === e.card
                    && name?.innerText.trim() === e.product.title ? e.product : null;
            }""")
            self._remaining(end)
            if actual and actual['title'] == info.get('title'):
                if info.get('product_id') == actual['product_id'] or info.get('missing_id'):
                    self.binding_platform_product_id = actual.get('platform_product_id')
                    self.binding_identity_source = "DOM_SELECTION_AND_UNCHANGED_FORM"
                    return ProductIdentity(actual['product_id'], actual['title'])
        if info.get("product_id") and info.get("title"):
            return ProductIdentity(info["product_id"], info["title"])
        raise BindingIdentityUnavailable("BINDING_ACTUAL_ID_OR_TITLE_UNAVAILABLE")

    def find(self, product: ProductIdentity, *, timeout_ms: int) -> ProductLookup:
        end = self._end(timeout_ms, 5000)
        self._open(end)
        ctx = self._get_content_frame()
        search = ctx.get_by_placeholder('请输入商品名称/编码搜索', exact=True)
        if search.count() == 1 and search.is_visible():
            # 平台公开控件：用精确商品编码跨分页筛选，再回读真实行的 ID 和完整名。
            try:
                search.fill(product.product_id, timeout=self._remaining(end))
                filtered = ctx.locator('[ml-key="filter_btn"]').filter(has_text='筛选')
                if filtered.count() != 1:
                    raise BindingIdentityUnavailable('PRODUCT_SEARCH_CONTROL_CONFLICT')
                filtered.click(timeout=self._remaining(end))
            except PlaywrightTimeoutError as exc:
                raise TimeoutError('PRODUCT_OPERATION_TIMEOUT') from exc
            # 真实异步列表必须结束 loading，空列表也需要明确空态；不能用旧行推测缺货。
            self._poll("return productDialogs().some(d => !Array.from(d.querySelectorAll('[aria-busy=true], .ant-spin-spinning, .weui-desktop-loading')).some(visible) && (lookup(arg).status !== 'UNAVAILABLE' || lookup(arg).matched || Array.from(d.querySelectorAll('.ant-empty, .weui-desktop-empty')).some(visible)));", end, vars(product))
        # 等到数据行或明确空列表出现，避免把加载中误判成缺货。
        self._poll("return productDialogs().some(d => Array.from(d.querySelectorAll('tr input[type=radio], .ant-empty, .weui-desktop-empty')).some(visible));", end)
        return ProductLookup(self._eval("return lookup(arg).status;", end, vars(product)))

    def select(self, product: ProductIdentity, *, timeout_ms: int) -> None:
        end = self._end(timeout_ms)
        self._open(end)
        status = self._eval("const r = lookup(arg); if (r.status === 'AVAILABLE') r.radio.click(); return r.status;", end, vars(product))
        if status != "AVAILABLE":
            raise BindingIdentityUnavailable("PRODUCT_CHANGED_BEFORE_SELECTION")
        self._poll("const ds = productDialogs(); if (ds.length !== 1) return false; const r = lookup(arg); return r.status === 'AVAILABLE' && r.radio.checked;", end, vars(product))
        observed = self._eval("return selectedIdentity();", end)
        if not observed or ProductIdentity(observed['product_id'], observed['title']) != product:
            raise BindingIdentityUnavailable("SELECTED_ACTUAL_ID_OR_TITLE_CONFLICT")
        self._clear_attestation()
        self._poll(r"const d = productDialogs()[0]; const b = d && button(d, /^添加(?:\s*[（(]1[）)])?$/); if (!b) return false; b.click(); return true;", end)
        self._poll("""
            for (const d of dialogs().filter(d => text(d).includes('选择商品出现时机'))) {
                const b = button(d, /^确认$/); if (b) b.click();
            }
            const card = scope.querySelector('.post-component-choose-wrap .choose-content .name');
            return !dialogs().length && visible(card) && !!text(card);
        """, end)

        # 保存平台实际选中行的身份及随后生成的卡片节点，任何改选/解绑/节点变化使证据失效。
        self._binding_attestation = self._get_content_frame().locator(
            '.post-component-choose-wrap .choose-content:visible'
        ).evaluate_handle("""(card, product) => {
            const scope = card.getRootNode(), region = card.closest('.post-component-choose-wrap');
            const evidence = {card, product, scope, valid: true};
            const observer = new MutationObserver(changes => {
                if (changes.some(c => c.type !== 'attributes' || ['data-product-id','title','href'].includes(c.attributeName)))
                    evidence.valid = false;
            });
            observer.observe(region, {childList: true, subtree: true, characterData: true, attributes: true});
            const click = event => {
                if (event.composedPath().some(n => n?.matches?.('.post-component-choose-wrap, .choosen-link-wrap, .link-display-wrap')))
                    evidence.valid = false;
            };
            scope.addEventListener('click', click, true);
            evidence.dispose = () => {observer.disconnect(); scope.removeEventListener('click', click, true);};
            return evidence;
        }""", observed, timeout=self._remaining(end))
        self._remaining(end)

    def _clear_attestation(self):
        if self._binding_attestation is not None:
            self._binding_attestation.evaluate('e => e.dispose()')
            self._binding_attestation.dispose()
            self._binding_attestation = None

    def cancel_and_clear(self, *, timeout_ms: int) -> bool:
        self._clear_attestation()
        end = self._end(timeout_ms, 3000)
        self._eval("for (const d of dialogs()) { const b = button(d, /^取消$/); if (b) b.click(); }", end)
        self._eval("const name = scope.querySelector('.post-component-choose-wrap .choose-content .name'); const b = scope.querySelector('.post-component-choose-wrap .close-icon'); if (visible(name) && text(name) && visible(b)) b.click();", end)
        return bool(self._poll("return !dialogs().length && binding().unbound === true;", end))

    def ready_to_submit(self, *, timeout_ms: int) -> bool:
        return bool(self._eval("return !dialogs().length && !!button(scope, /^发表$/);", self._end(timeout_ms)))

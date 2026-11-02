"""公开商品弹窗的只读分页适配器；无选中、上传、草稿或发表动作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| public-dom-v1 | 2026-11-02 | Codex | 复用可见商品根；缺稳定账号或公开总数不宣称完整，不读取框架私有状态。 |
"""
from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlsplit

from .wechat_product_picker import PlaywrightProductPicker
from .wechat_product_pool import COLLECTOR_VERSION


class CatalogSyncError(ValueError):
    def __init__(self, reason, partial=None):
        super().__init__(reason)
        self.reason, self.partial = reason, partial or {}


def read_public_account(page):
    """只接受可见发布账号节点的稳定 finder 标识，昵称及 profile 路径均不算。"""
    rows = page.locator('[data-publisher-finder-username]:visible, .account-info[data-finder-username]:visible, '
                        '.user-info[data-finder-username]:visible').evaluate_all('''es => es.map(e => ({
        value: e.getAttribute('data-publisher-finder-username') || e.getAttribute('data-finder-username'),
        attribute: e.hasAttribute('data-publisher-finder-username') ? 'data-publisher-finder-username' : 'data-finder-username'
    }))''')
    if not rows or len({r['value'] for r in rows}) != 1 or not rows[0]['value'] or not rows[0]['value'].strip():
        return None
    return {'kind': 'PUBLIC_DOM_STABLE_ID', 'value': rows[0]['value'].strip(),
            'selector': '[data-publisher-finder-username], .account-info[data-finder-username], .user-info[data-finder-username]',
            'attribute': rows[0]['attribute']}


_SNAPSHOT = r'''
const ds = productDialogs();
if(ds.length !== 1) return null;
const d=ds[0];
if(Array.from(d.querySelectorAll('[aria-busy=true], .ant-spin-spinning, .weui-desktop-loading')).some(visible)) return null;
const tables=Array.from(d.querySelectorAll('table')).filter(visible);
const table=tables.find(t => t.querySelector('.id-wrap'));
if(!table) return {error:'CATALOG_EMPTY_OR_UNSUPPORTED', items:[]};
const heads=Array.from(table.querySelectorAll('thead th')).map(text);
const index = name => heads.findIndex(h => h.includes(name));
const stockIndex=index('库存'), shopIndex=index('店铺'), priceIndex=index('价格');
const rows=Array.from(table.querySelectorAll('tbody tr')).filter(visible);
const items=rows.map(row => {
    const idNodes=Array.from(row.querySelectorAll('.id-wrap')).filter(visible);
    const titles=Array.from(row.querySelectorAll('.title')).filter(visible);
    const id=idNodes.length===1 ? text(idNodes[0]) : '';
    const title=titles.length===1 ? titles[0].getAttribute('title')?.trim() || text(titles[0]) : '';
    const cells=Array.from(row.cells), value = i => i>=0 && cells[i] ? text(cells[i]) : '';
    const stockRaw=value(stockIndex).replace(/,/g,'');
    const stock=/^\d+$/.test(stockRaw) ? Number(stockRaw) : null;
    const radio=row.querySelector('input[type=radio]');
    const unavailable=Array.from(row.querySelectorAll('*')).some(e => visible(e) && /^(不可售卖|已下架|已售罄|售罄)$/.test(text(e)));
    const sale=unavailable || radio?.disabled || radio?.getAttribute('aria-disabled')==='true'
        ? 'UNAVAILABLE' : radio && (stock!==null || /可售卖|销售中|在售/.test(text(row))) ? 'AVAILABLE' : 'UNKNOWN';
    return {product_id:id, title, stock, shop:value(shopIndex)||text(row.querySelector('.shop-name'))||'未披露店铺',
            price:value(priceIndex)||text(row.querySelector('.price'))||'未披露价格', sale_state:sale};
});
const totalNodes=Array.from(d.querySelectorAll('.ant-pagination-total-text, .pagination-total, [data-total-items]')).filter(visible);
const totalValues=totalNodes.map(e => e.getAttribute('data-total-items') || text(e).match(/共\s*(\d+)\s*[件条]/)?.[1]).filter(Boolean).map(Number);
const totals=[...new Set(totalValues)];
const active=Array.from(d.querySelectorAll('.ant-pagination-item-active, [aria-current=page]')).filter(visible);
const current=active.length===1 ? Number(text(active[0])) : 1;
const next=Array.from(d.querySelectorAll('.ant-pagination-next, [aria-label="下一页"], [title="下一页"]')).filter(visible);
const nextAvailable=next.filter(e => enabled(e) && !e.classList.contains('ant-pagination-disabled'));
return {items, total_items:totals.length===1 ? totals[0] : null, page:current,
        next_count:nextAvailable.length, empty:items.length===0};
'''


def collect_catalog(page, *, timeout_seconds=60, max_pages=20, clock=monotonic):
    if not 0 < timeout_seconds <= 60 or not 1 <= max_pages <= 20:
        raise CatalogSyncError('CATALOG_BUDGET_INVALID')
    try:
        return _collect_catalog(page, timeout_seconds=timeout_seconds, max_pages=max_pages, clock=clock)
    except TimeoutError as exc:
        raise CatalogSyncError('CATALOG_SYNC_TIMEOUT') from exc


def _collect_catalog(page, *, timeout_seconds, max_pages, clock):
    end = clock() + timeout_seconds
    picker = PlaywrightProductPicker(page, clock=clock)
    picker._open(end)
    account = read_public_account(page)
    pages, observations, seen = [], [], set()
    first_total = None
    previous_signature = None
    while len(pages) < max_pages:
        snapshot = None
        while clock() < end:
            snapshot = picker._eval(_SNAPSHOT, end)
            if snapshot and snapshot.get('items'):
                signature = tuple(i['product_id'] for i in snapshot['items'])
                if signature != previous_signature:
                    break
            if snapshot and snapshot.get('error'):
                raise CatalogSyncError(snapshot['error'], {'pages': pages})
            page.wait_for_timeout(min(50, picker._remaining(end)))
        if not snapshot or clock() >= end:
            raise CatalogSyncError('CATALOG_SYNC_TIMEOUT', {'pages': pages})
        if snapshot['page'] != len(pages) + 1:
            raise CatalogSyncError('CATALOG_PAGE_CONFLICT', {'pages': pages})
        if first_total is None:
            first_total = snapshot['total_items']
        if first_total is None or snapshot['total_items'] != first_total:
            raise CatalogSyncError('CATALOG_TOTAL_UNVERIFIED', {'observed_items': len(snapshot['items']), 'pages': pages})
        items = []
        for row in snapshot['items']:
            pid = row['product_id']
            if not pid or pid in seen:
                raise CatalogSyncError('CATALOG_DUPLICATE_OR_MISSING_ID', {'pages': pages})
            seen.add(pid)
            items.append({k: row[k] for k in ('product_id', 'title', 'shop', 'price', 'stock')})
            observations.append({k: row[k] for k in ('product_id', 'title', 'stock', 'sale_state')} | {'page': snapshot['page']})
        pages.append({'page': snapshot['page'], 'items': items})
        if not account or read_public_account(page) != account:
            raise CatalogSyncError('CATALOG_ACCOUNT_UNVERIFIED', {'pages': pages, 'observed_items': len(seen)})
        if snapshot['next_count'] == 0:
            if len(seen) != first_total:
                raise CatalogSyncError('CATALOG_COUNT_MISMATCH', {'pages': pages})
            captured = datetime.now(timezone.utc).isoformat()
            data = {'schema_version': 2, 'captured_at': captured, 'source': COLLECTOR_VERSION,
                    'account_id': account['value'], 'total_pages': len(pages), 'total_items': len(seen), 'pages': pages}
            parsed = urlsplit(page.url)
            proof = {'schema_version': 1, 'collector_version': COLLECTOR_VERSION,
                     'captured_at': captured, 'account_id': account['value'], 'account_evidence': account,
                     'read_only': True, 'mutating_actions': [], 'observations': observations,
                     'page_urls': [parsed.scheme + '://' + parsed.netloc + parsed.path]}
            return data, proof
        if snapshot['next_count'] != 1:
            raise CatalogSyncError('CATALOG_PAGINATION_CONFLICT', {'pages': pages})
        previous_signature = tuple(i['product_id'] for i in snapshot['items'])
        context = picker._get_content_frame()
        dialogs = context.locator('.weui-desktop-dialog:visible, .ant-modal:visible, [role=dialog]:visible').filter(has_text='从橱窗添加商品')
        next_button = dialogs.locator('.ant-pagination-next:not(.ant-pagination-disabled), [aria-label="下一页"]:not([aria-disabled=true]), [title="下一页"]:not([aria-disabled=true])')
        if next_button.count() != 1:
            raise CatalogSyncError('CATALOG_PAGINATION_CONFLICT', {'pages': pages})
        next_button.click(timeout=picker._remaining(end))
    raise CatalogSyncError('CATALOG_PAGE_BUDGET', {'pages': pages})

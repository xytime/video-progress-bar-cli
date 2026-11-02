"""商品采集的公开 DOM 诊断与脱敏；不读取页面存储或网络凭证。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 限定诊断字段、文本长度与 URL path；阶段计时在异常时仍保留。 |
"""
from contextlib import contextmanager
import re
from time import monotonic
from urllib.parse import urlsplit


def _path(url):
    try:
        return urlsplit(url).path or '/'
    except ValueError:
        return '[URL]'


def public_text(value, limit=160):
    """先脱敏后截断，避免 query、Cookie、token 或 Authorization 落入回执。"""
    value = str(value or '')
    value = re.sub(r'(?:https?://|//)[^\s<>"\']+', lambda m: _path(m[0]), value)
    value = re.sub(r'(?is)\b(cookie|set-cookie|authorization)["\']?\s*[:=].*', r'\1=[REDACTED]', value)
    value = re.sub(r'''(?i)\b(?:bearer\s+\S+|[\w-]*(?:token|password|secret|session|credential)[\w-]*["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s;,]+))''', '[REDACTED]', value)
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def public_path(url):
    return public_text(_path(url), 240)


def sanitized_snapshot(raw):
    """只接收适配器声明的字段，不透传其他页面数据。"""
    result = {k: int(raw.get(k, 0)) for k in ('dialog_count', 'visible_table_count', 'recognized_table_count',
              'row_count', 'id_wrap_count', 'spinner_count')}
    result['state'] = raw['state'] if raw.get('state') in {'LOADING', 'READY', 'EMPTY_CONFIRMED', 'UNSUPPORTED'} else 'LOADING'
    for key in ('headers', 'empty_text', 'hints'):
        result[key] = [public_text(v) for v in raw.get(key, [])[:20]]
    for key in ('pagination_nodes', 'total_nodes', 'scope_account_nodes'):
        result[key] = [{'selector': public_text(n['selector'], 300), 'count': int(n['count']),
                        'visible_count': int(n.get('visible_count', n['count'])),
                        'texts': [public_text(v) for v in n.get('texts', [])[:5]]}
                       for n in raw.get(key, [])[:12]]
    return result


@contextmanager
def timed_phase(diagnostics, name, clock=monotonic):
    diagnostics['last_phase'] = name
    started = clock()
    try:
        yield
    finally:
        timings = diagnostics.setdefault('timings_seconds', {})
        timings[name] = round(timings.get(name, 0) + max(0, clock() - started), 3)


DOM_DIAGNOSTICS = r'''
const ds=productDialogs(), d=ds.length===1 ? ds[0] : null;
const tables=d ? Array.from(d.querySelectorAll('table')).filter(visible) : [];
const recognized=tables.filter(t => Array.from(t.querySelectorAll('.id-wrap')).some(visible));
const spinners=d ? Array.from(d.querySelectorAll('[aria-busy=true], .ant-spin-spinning, .weui-desktop-loading')).filter(visible) : [];
const emptyWords=/^(暂无商品|暂无数据|暂无可添加的商品|没有可添加的商品|橱窗暂无商品|暂无可售卖商品|暂无可展示的商品)$/;
const empty=d ? Array.from(d.querySelectorAll('*')).filter(e => visible(e) && emptyWords.test(text(e))).map(text) : [];
const hints=d ? Array.from(d.querySelectorAll('.ant-empty-description,.empty-text,.empty-tips,.no-data,[role=status],[role=alert],.weui-desktop-tips,.hint')).filter(visible).map(e => text(e).slice(0,1000)) : [];
const nodeSummary=(selectors, includeText=true) => selectors.map(selector => {
    const ns=Array.from((d || scope).querySelectorAll(selector)), vs=ns.filter(visible);
    return {selector, count:ns.length, visible_count:vs.length,
        texts:includeText ? vs.slice(0,5).map(e => text(e).slice(0,1000)) : []};
});
const diagnostic={dialog_count:ds.length, visible_table_count:tables.length, recognized_table_count:recognized.length,
    headers:tables.flatMap(t => Array.from(t.querySelectorAll('thead th')).map(e => text(e).slice(0,1000))).slice(0,20),
    row_count:tables.reduce((n,t) => n+Array.from(t.querySelectorAll('tbody tr')).filter(visible).length,0),
    id_wrap_count:tables.reduce((n,t) => n+Array.from(t.querySelectorAll('.id-wrap')).filter(visible).length,0),
    spinner_count:spinners.length, empty_text:[...new Set(empty)].slice(0,5), hints:hints.slice(0,8),
    pagination_nodes:nodeSummary(['.pagination-wrap','.weui-desktop-pagination','.ant-pagination','.ant-pagination-item-active','[aria-current=page]','.ant-pagination-next','[aria-label="下一页"]','[title="下一页"]']),
    total_nodes:nodeSummary(['.ant-pagination-total-text','.pagination-total','[data-total-items]']),
    scope_account_nodes:nodeSummary(['[data-publisher-finder-username]','.account-info[data-finder-username]','.user-info[data-finder-username]'],false)};
diagnostic.state=spinners.length ? 'LOADING' : empty.length && recognized.length===0 ? 'EMPTY_CONFIRMED' : recognized.length===1 ? 'READY' : 'LOADING';
'''

"""发布页已知滚动表的只读遍历；两次从顶到底回读并验证身份集合。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 限定公开 ant 表结构、固定预算、两轮一致性和加载等待；不点击商品。 |
"""
from hashlib import sha256
import json

from .wechat_catalog_diagnostics import sanitized_snapshot


def enumerate_scroll(picker, snapshot_code, end, max_steps, diagnostics):
    """无公开总数时，仅接受可定位滚动体的完整遍历，不用末屏条数冒充平台总数。"""
    steps = 0
    rounds = []
    traces = []

    def snapshot():
        while True:
            snap = picker._eval(snapshot_code, end)
            diagnostics['snapshot'] = sanitized_snapshot(snap['diagnostics'])
            if snap['state'] == 'READY':
                return snap
            if snap['state'] == 'EMPTY_CONFIRMED':
                raise ValueError('CATALOG_ENUMERATION_CHANGED')
            picker.page.wait_for_timeout(min(50, picker._remaining(end)))

    def move(position):
        nonlocal steps
        if steps >= max_steps:
            raise ValueError('CATALOG_PAGE_BUDGET')
        steps += 1
        picker._eval('''const ds=productDialogs();
            if(ds.length!==1) throw Error('CATALOG_SCROLL_ROOT');
            const bodies=Array.from(ds[0].querySelectorAll('.ant-table-body')).filter(visible);
            if(bodies.length!==1) throw Error('CATALOG_SCROLL_ROOT');
            const b=bodies[0]; b.scrollTop=arg==='top' ? 0 : Math.min(b.scrollHeight,b.scrollTop+Math.max(1,b.clientHeight*.8));
            return true;''', end, position)
        picker.page.wait_for_timeout(min(350, picker._remaining(end)))

    initial = snapshot()
    if not initial.get('scroll') or initial.get('pagination_present') or initial['next_count']:
        raise ValueError('CATALOG_TOTAL_UNVERIFIED')
    for _ in range(2):
        move('top')
        seen = {}
        while True:
            snap = snapshot()
            geometry = snap.get('scroll')
            if (not geometry or snap.get('pagination_present') or snap['next_count']
                    or not geometry['unfiltered'] or geometry['virtual'] or geometry['client'] <= 0):
                raise ValueError('CATALOG_TOTAL_UNVERIFIED')
            rows = snap['items']
            ids = [r['product_id'] for r in rows]
            if not ids or any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('CATALOG_DUPLICATE_OR_MISSING_ID')
            for row in rows:
                pid = row['product_id']
                if pid in seen and seen[pid] != row:
                    raise ValueError('CATALOG_ENUMERATION_CHANGED')
                seen[pid] = row
            diagnostics['observed_items'] = len(seen)
            traces.append({k: geometry[k] for k in ('top','height','client','bottom')})
            if geometry['bottom']:
                # 在底部停留，让滚动触发的异步加载完成，再确认几何和内容均未变化。
                picker.page.wait_for_timeout(min(1200, picker._remaining(end)))
                after = snapshot()
                if (after.get('scroll') == geometry and after['items'] == rows
                        and not after.get('pagination_present') and not after['next_count']):
                    break
            move('next')
        rounds.append(seen)
    if rounds[0] != rounds[1]:
        raise ValueError('CATALOG_ENUMERATION_CHANGED')
    rows = sorted(rounds[1].values(), key=lambda r: r['product_id'])
    identity = [(r['product_id'],r['title']) for r in rows]
    return rows, {'kind':'PUBLIC_DOM_SCROLL_ENUMERATION', 'rounds':2, 'steps':steps,
                  'observed_items':len(rows), 'identity_digest':sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest(),
                  'terminal_checks':traces, 'explicit_total':False}

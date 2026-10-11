"""商品目录校验、只读合并与原子导入；不访问平台、不改变运营策略。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
from pathlib import Path
import re

from video_processing.utils.wechat_product_config import _unique_object, atomic_json, load_policy, PolicyConflict

MAX_CATALOG_BYTES = 5_000_000


def catalog_digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _text(value, label):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'{label}必须是无首尾空白的非空文本')
    return value


def _timestamp(value):
    stamp = datetime.fromisoformat(_text(value, '采集时间'))
    if stamp.tzinfo is None:
        raise ValueError('采集时间必须包含时区')
    return stamp


def decode_catalog(raw: bytes, *, import_only: bool = False) -> tuple[dict, dict]:
    """返回原始文档与标准视图；完整性由分页和唯一 ID 数量计算，不能自报 complete。"""
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError('商品清单不能超过 5 MB')
    data = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int:
        raise ValueError('商品清单格式不受支持')
    version = data['schema_version']
    if version not in (1, 2) or (import_only and version != 2):
        raise ValueError('导入需要带账号、分页及总数的 v2 清单；旧快照不能证明完整性')
    _timestamp(data.get('captured_at'))
    _text(data.get('source'), '来源')
    result = dict(captured_at=data['captured_at'], source=data['source'], account_id=None,
                  completeness='unverified', live_verified=False, total_pages=None)
    if version == 1:
        digest = data.get('source_sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('商品清单缺少来源摘要')
        if data.get('completeness') not in {'unverified', 'partial', 'complete'}:
            raise ValueError('商品清单完整性状态不正确')
        result['completeness'] = 'partial' if data['completeness'] == 'partial' else 'unverified'
        result['source_sha256'] = digest
        items = data.get('items')
    else:
        fields = {'schema_version','captured_at','source','account_id','total_pages','total_items','pages'}
        if set(data) != fields:
            raise ValueError('v2 清单字段不正确，请参考导入格式说明')
        account = _text(data['account_id'], '账号标识')
        for name in ('total_pages', 'total_items'):
            if type(data[name]) is not int or not 1 <= data[name] <= 50000:
                raise ValueError('总页数和商品总数必须为正整数；空清单不覆盖旧资料')
        pages = data['pages']
        if not isinstance(pages, list) or len(pages) != data['total_pages']:
            raise ValueError('分页不完整：页数与声明总页数不符')
        items, seen_pages = [], set()
        for page in pages:
            if not isinstance(page, dict) or set(page) != {'page', 'items'}:
                raise ValueError('分页条目格式不正确')
            number = page['page']
            if type(number) is not int or not 1 <= number <= data['total_pages'] or number in seen_pages:
                raise ValueError('分页不完整：页码重复或超出范围')
            if not isinstance(page['items'], list) or not page['items']:
                raise ValueError('分页为空，不能确认清单完整')
            seen_pages.add(number)
            items.extend(page['items'])
        if len(items) != data['total_items']:
            raise ValueError('商品数量不符：实际条目数与声明总数不一致')
        result.update(account_id=account, completeness='complete', total_pages=data['total_pages'],
                      source_sha256=hashlib.sha256(raw).hexdigest())
    if not isinstance(items, list) or not items:
        raise ValueError('商品清单为空，未替换已有商品')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'product_id', 'title', 'shop', 'price', 'stock'}:
            raise ValueError('商品条目字段不正确')
        for field in ('product_id', 'title', 'shop', 'price'):
            _text(item[field], field)
        pid = item['product_id']
        if not re.fullmatch(r'[0-9]{1,64}', pid) or pid in seen:
            raise ValueError('商品 ID 无效或重复（含跨页重复）')
        seen.add(pid)
        if item['stock'] is not None and (type(item['stock']) is not int or item['stock'] < 0):
            raise ValueError('库存必须为非负整数或未知')
    result['items'] = items
    return data, result


def merge_catalog(catalog: dict, configured: dict) -> dict:
    products = dict(configured)
    aliases = {}
    for alias, product in products.items():
        aliases.setdefault(product['product_id'], alias)
    for item in catalog['items']:
        pid = item['product_id']
        if pid in aliases:
            if products[aliases[pid]]['title'] != item['title']:
                raise ValueError(f'商品 {pid} 与已保存名称冲突，请核实目录')
            continue
        alias = 'product_' + pid
        if alias in products:
            raise ValueError(f'商品 {pid} 的内部引用冲突')
        products[alias] = dict(product_id=pid, title=item['title'], enabled=True,
                               verified_at=catalog['captured_at'], verified_source=catalog['source'])
    return products


def catalog_view(path: Path, configured: dict) -> dict:
    fallback = dict(products=configured, items=[], captured_at=None, digest=None,
                    completeness='unverified', live_verified=False)
    try:
        if not path.exists():
            return dict(fallback, error='尚无后台商品清单，仅显示已配置商品。')
        raw = path.read_bytes()
        fallback['digest'] = hashlib.sha256(raw).hexdigest()
        _, catalog = decode_catalog(raw)
        return dict(catalog, products=merge_catalog(catalog, configured), digest=fallback['digest'], error=None)
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        return dict(fallback, error=f'商品清单读取失败：{exc}；仅显示已保存商品。')


def prepare_import(content: str, path: Path, active: Path, *, expected_catalog_digest: str | None,
                   expected_policy_digest: str) -> tuple[dict, dict]:
    """预览和写入共用检查；预览不创建锁、清单或策略文件。"""
    policy = load_policy(active)
    if policy.digest != expected_policy_digest or catalog_digest(path) != expected_catalog_digest:
        raise PolicyConflict('商品清单或规则已被其他窗口更新，请重新载入后再校验。')
    data, catalog = decode_catalog(content.encode('utf-8'), import_only=True)
    stamp = _timestamp(catalog['captured_at'])
    if stamp > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError('采集时间在未来，请核实来源时间')
    old = catalog_view(path, json.loads(policy.serialized)['products'])
    if old.get('error') and path.exists():
        raise ValueError('原清单不可读取，需先修复；未覆盖旧资料')
    if old.get('account_id') and old['account_id'] != catalog['account_id']:
        raise ValueError('账号与已保存清单不一致；不能跨账号覆盖')
    if old.get('captured_at') and stamp < _timestamp(old['captured_at']):
        raise ValueError('采集时间早于现有清单，不能用旧资料覆盖')
    merge_catalog(catalog, json.loads(policy.serialized)['products'])
    before = {p['product_id']:p for p in old['items']}
    after = {p['product_id']:p for p in catalog['items']}
    # 包括尚未写入规则的旧目录商品：同 ID 改名同样要核实，不能悄悄置换版本。
    for pid in before.keys() & after.keys():
        if before[pid]['title'] != after[pid]['title']:
            raise ValueError(f'商品 {pid} 与原清单名称冲突，请核实')
    report = dict(account_id=catalog['account_id'], account_first_import=not old.get('account_id'),
                  captured_at=catalog['captured_at'], total_items=len(after), total_pages=catalog['total_pages'],
                  completeness='complete', live_verified=False,
                  added=[after[k] for k in after.keys()-before.keys()],
                  missing=[before[k] for k in before.keys()-after.keys()],
                  updated=[after[k] for k in after.keys() & before.keys() if after[k] != before[k]],
                  content_digest=hashlib.sha256(content.encode('utf-8')).hexdigest())
    return data, report


def import_catalog(content: str, path: Path, active: Path, **expected) -> dict:
    """持有策略/目录锁后重验 CAS 并原子替换；从不写策略或触发发布。"""
    with active.with_suffix(active.suffix+'.lock').open('a') as policy_lock:
        fcntl.flock(policy_lock, fcntl.LOCK_EX)
        with path.with_suffix(path.suffix+'.lock').open('a') as catalog_lock:
            fcntl.flock(catalog_lock, fcntl.LOCK_EX)
            data, report = prepare_import(content, path, active, **expected)
            atomic_json(path, data)
            return report

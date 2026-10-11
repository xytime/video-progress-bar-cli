"""读取真实商品目录快照；与选品规则分开，不访问平台、不改写运营配置。"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

from video_processing.utils.wechat_product_config import _unique_object


def catalog_view(path: Path, configured: dict) -> dict:
    """按平台 ID 合并可配置目录；旧规则及停用状态优先，异常保留原配置。"""
    fallback = {'products': configured, 'items': [], 'captured_at': None,
                'completeness': 'unverified', 'live_verified': False}
    try:
        if not path.exists():
            return dict(fallback, error='尚无后台商品清单，仅显示已配置商品。')
        if path.stat().st_size > 5_000_000:
            raise ValueError('商品清单文件过大')
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('商品清单格式不受支持')
        captured = data.get('captured_at')
        if not isinstance(captured, str) or datetime.fromisoformat(captured).tzinfo is None:
            raise ValueError('采集时间必须包含时区')
        source = data.get('source')
        if not isinstance(source, str) or not source.strip():
            raise ValueError('商品清单缺少来源')
        if not isinstance(data.get('source_sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', data['source_sha256']):
            raise ValueError('商品清单缺少来源摘要')
        if data.get('completeness') not in {'unverified', 'partial', 'complete'}:
            raise ValueError('商品清单完整性状态不正确')
        items = data.get('items')
        if not isinstance(items, list) or not items:
            raise ValueError('商品清单为空，未替换已有商品')
        products = dict(configured)
        aliases = {}
        for alias, product in products.items():
            aliases.setdefault(product['product_id'], alias)
        seen = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {'product_id', 'title', 'shop', 'price', 'stock'}:
                raise ValueError('商品条目字段不正确')
            for key in ('product_id', 'title', 'shop', 'price'):
                if not isinstance(item[key], str) or not item[key] or item[key] != item[key].strip():
                    raise ValueError(f'商品条目 {key} 不正确')
            pid = item['product_id']
            if not re.fullmatch(r'[0-9]{1,64}', pid) or pid in seen:
                raise ValueError('商品 ID 无效或重复')
            seen.add(pid)
            stock = item['stock']
            if stock is not None and (type(stock) is not int or stock < 0):
                raise ValueError('库存必须为非负整数或未知')
            if pid in aliases:
                if products[aliases[pid]]['title'] != item['title']:
                    raise ValueError(f'商品 {pid} 与已保存名称冲突，请核实目录')
                continue
            alias = 'product_' + pid
            if alias in products:
                raise ValueError(f'商品 {pid} 的内部引用冲突')
            products[alias] = dict(product_id=pid, title=item['title'], enabled=True,
                                   verified_at=captured, verified_source=source)
        return dict(products=products, items=items, captured_at=captured,
                    source=source, source_sha256=data['source_sha256'],
                    completeness=data['completeness'], live_verified=False, error=None)
    except (ValueError, OSError) as exc:
        return dict(fallback, error=f'商品清单读取失败：{exc}；仅显示已保存商品。')

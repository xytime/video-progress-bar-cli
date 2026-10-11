"""商品资料校验；待核实资料与可用于自动选品的身份严格分开。"""
from datetime import datetime, timezone
import re

FIELDS = {'product_id','title','account_id','shop','merchant_appid','specification',
          'short_name','notes','identity_status','verified_at','verified_source','enabled'}


def validate_library(library: dict, products: dict) -> None:
    if not isinstance(products, dict):
        raise ValueError('候选目录必须是字典')
    if not isinstance(library, dict) or len(library) > 50000:
        raise ValueError('商品资料必须是有效字典')
    identities = {}
    accounts = set()
    for alias, row in library.items():
        if not isinstance(alias, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', alias):
            raise ValueError('商品内部引用无效')
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError('商品资料字段不完整')
        if type(row['enabled']) is not bool:
            raise ValueError('商品启用状态无效')
        for key in FIELDS - {'enabled'}:
            if not isinstance(row[key], str) or row[key] != row[key].strip() or len(row[key]) > 2000:
                raise ValueError('商品资料必须为文本且不含首尾空白')
        if row['identity_status'] not in {'UNVERIFIED', 'VERIFIED'}:
            raise ValueError('商品身份状态无效')
        active = products.get(alias)
        if row['identity_status'] == 'UNVERIFIED':
            if active is not None:
                raise ValueError(f'待核实商品不能进入候选目录：{alias}')
            continue
        if not all(row[k] for k in ('product_id','title','account_id','verified_at','verified_source')):
            raise ValueError('已核实商品必须有 ID、全名、发布账号、核实时间与来源')
        if not re.fullmatch(r'[0-9]{1,64}', row['product_id']):
            raise ValueError('商品 ID 必须是数字字符串，不能填写商家 AppID')
        stamp = datetime.fromisoformat(row['verified_at'])
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
            raise ValueError('核实时间必须含时区且不能在未来')
        identity = (row['account_id'], row['product_id'])
        if identity in identities:
            raise ValueError('同一账号商品 ID 重复，请编辑已有资料')
        identities[identity] = row['title']
        accounts.add(row['account_id'])
        expected = {k:row[k] for k in ('product_id','title','enabled','verified_at','verified_source')}
        if active != expected:
            raise ValueError('商品资料与候选身份不一致，请在同次保存修复')
    if len(accounts) > 1:
        raise ValueError('本期仅支持同一个发布账号，不能混用多账号商品')


def references(config: dict, alias: str) -> list[str]:
    rows = []
    if alias in config['default_candidates']:
        rows.append('全局默认')
    rows.extend(name for name, p in config.get('profiles', {}).items() if alias in p['candidates'])
    rows.extend(r['id'] for r in config['rules'] if alias in r['candidates'])
    return rows

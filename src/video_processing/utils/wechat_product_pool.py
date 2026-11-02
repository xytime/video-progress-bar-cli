"""当前可售商品池：目录与受控 DOM 观察凭证同摘要、同账号、同时间才有效。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-11-02 | Codex | 校验滚动遍历凭证及首页账号前后证据，保留TTL、可售与CAS门禁。 |
| live-pool-v1 | 2026-11-02 | Codex | 独立 live 凭证、7天时效、可售与身份闭锁；人工导入不自动自证 live。 |
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from config.settings import settings
from video_processing.utils.wechat_product_catalog import decode_catalog, import_catalog, catalog_digest
from video_processing.utils.wechat_product_config import atomic_json, load_policy, _unique_object, PolicyConflict
from video_processing.core.wechat_product_matching import validate_matching_config, digest

COLLECTOR_VERSION = 'wechat-product-public-dom-v1'


def matching_config(policy_path):
    path = Path(policy_path).with_name('wechat_product_matching.json')
    if not path.exists():
        return None  # 旧安装和旧测试保持原冻结合同；生产显式采用新配置。
    return validate_matching_config(json.loads(path.read_text(), object_pairs_hook=_unique_object))


def attestation_path(policy_path):
    return Path(policy_path).with_name('wechat_product_catalog.live.json')


def _stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('观察时间缺少时区')
    return stamp


def validate_observation(catalog, proof):
    """不信任自报的 live_verified；完整公共 DOM 证据和商品身份逐条重验。"""
    if (proof.get('schema_version') != 1 or proof.get('collector_version') != COLLECTOR_VERSION
            or proof.get('account_id') != catalog.get('account_id')
            or proof.get('captured_at') != catalog.get('captured_at')
            or proof.get('read_only') is not True or proof.get('mutating_actions') != []):
        raise ValueError('采集凭证与目录不一致')
    evidence = proof.get('account_evidence', {})
    if (evidence.get('kind') != 'PUBLIC_DOM_STABLE_ID' or evidence.get('value') != catalog['account_id']
            or not evidence.get('selector') or not evidence.get('attribute')):
        raise ValueError('未取得公开稳定账号标识')
    if evidence.get('attribute') == 'data-clipboard-text':
        checks = proof.get('account_checks', {})
        if checks.get('before') != evidence or checks.get('after') != evidence:
            raise ValueError('首页稳定账号缺少采集前后核对')
    enumeration = proof.get('completeness_evidence')
    if enumeration is not None:
        ids = sorted((i['product_id'], i['title']) for i in catalog['items'])
        expected = hashlib.sha256(json.dumps(ids, ensure_ascii=False).encode()).hexdigest()
        traces = enumeration.get('terminal_checks', [])
        if (enumeration.get('kind') != 'PUBLIC_DOM_SCROLL_ENUMERATION' or enumeration.get('rounds') != 2
                or type(enumeration.get('steps')) is not int or not 2 <= enumeration['steps'] <= 20
                or enumeration.get('observed_items') != len(ids) or enumeration.get('identity_digest') != expected
                or enumeration.get('explicit_total') is not False or not isinstance(traces, list) or not traces
                or any(not isinstance(t, dict) for t in traces)
                or sum(t.get('bottom') is True for t in traces) < 2
                or any(not isinstance(t.get(k), (int, float)) for t in traces for k in ('top','height','client'))
                or any(t['top'] < 0 or t['client'] <= 0 or t['height'] < t['client']
                       or (t.get('bottom') is True and t['top'] + t['client'] < t['height'] - 2) for t in traces)
                or not traces[-1].get('bottom') or catalog['total_pages'] != 1):
            raise ValueError('滚动遍历证据不完整或身份不一致')
    urls = proof.get('page_urls', [])
    if not urls or any(urlsplit(u).scheme != 'https' or urlsplit(u).hostname != 'channels.weixin.qq.com' for u in urls):
        raise ValueError('目录来源不是官方页面')
    observations = proof.get('observations')
    if not isinstance(observations, list) or len(observations) != len(catalog['items']):
        raise ValueError('可售证据不完整')
    by_id = {}
    for row in observations:
        if (not isinstance(row, dict) or set(row) != {'product_id', 'title', 'sale_state', 'stock', 'page'}
                or row['product_id'] in by_id or row['sale_state'] not in {'AVAILABLE', 'UNAVAILABLE', 'UNKNOWN'}
                or type(row['page']) is not int or not 1 <= row['page'] <= catalog['total_pages']):
            raise ValueError('可售观察格式不正确')
        by_id[row['product_id']] = row
    for item in catalog['items']:
        row = by_id.get(item['product_id'], {})
        if row.get('title') != item['title'] or row.get('stock') != item['stock']:
            raise ValueError('可售观察身份或库存冲突')
    for page in catalog.get('pages', []):
        if any(by_id[i['product_id']]['page'] != page['page'] for i in page['items']):
            raise ValueError('可售观察分页冲突')
    return by_id


def load_live_pool(policy_path, *, now=None, ttl_days=None):
    now = now or datetime.now(timezone.utc)
    ttl = settings.wechat_product_catalog_ttl_days if ttl_days is None else ttl_days
    result = {'ready': False, 'reason': 'CATALOG_UNVERIFIED', 'catalog_digest': None,
              'attestation_digest': None, 'captured_at': None, 'account_id': None,
              'age_seconds': None, 'ttl_seconds': ttl * 86400, 'eligible': [], 'excluded': [],
              'completeness': 'unverified', 'live_verified': False, 'total_items': None, 'exclusion_counts': {}}
    try:
        path = Path(policy_path).with_name('wechat_product_catalog.json')
        raw = path.read_bytes()
        result['catalog_digest'] = hashlib.sha256(raw).hexdigest()
        data, catalog = decode_catalog(raw)
        result.update(captured_at=catalog['captured_at'], account_id=catalog['account_id'],
                      completeness=catalog['completeness'], total_items=len(catalog['items']))
        age = (now - _stamp(catalog['captured_at'])).total_seconds()
        result['age_seconds'] = age
        if age < -300:
            raise ValueError('目录时间在未来')
        if age > result['ttl_seconds']:
            result['reason'] = 'CATALOG_STALE'
            result['excluded'] = [{'product_id': i['product_id'], 'reason': 'CATALOG_STALE'} for i in catalog['items']]
            result['exclusion_counts'] = {'CATALOG_STALE': len(catalog['items'])}
            return result
        proof_raw = attestation_path(policy_path).read_bytes()
        proof = json.loads(proof_raw, object_pairs_hook=_unique_object)
        result['attestation_digest'] = hashlib.sha256(proof_raw).hexdigest()
        if catalog['completeness'] != 'complete' or proof.get('catalog_digest') != result['catalog_digest']:
            raise ValueError('目录完整性或采集摘要未核实')
        observations = validate_observation(dict(catalog, pages=data['pages']), proof)
        config = json.loads(load_policy(policy_path).serialized)
        for row in config.get('library', {}).values():
            if row.get('identity_status') == 'VERIFIED' and row.get('account_id') != catalog['account_id']:
                raise ValueError('目录与人工核实账号冲突')
        configured = list(config['products'].values()) + list(config.get('library', {}).values())
        for item in catalog['items']:
            known = [p for p in configured if p['product_id'] == item['product_id']]
            reason = None
            if any(not p.get('enabled') for p in known): reason = 'DISABLED'
            elif any(p['title'] != item['title'] for p in known): reason = 'IDENTITY_CONFLICT'
            elif item['stock'] == 0: reason = 'OUT_OF_STOCK'
            elif observations[item['product_id']]['sale_state'] != 'AVAILABLE': reason = 'SALE_UNVERIFIED_OR_UNAVAILABLE'
            if reason:
                result['excluded'].append({'product_id': item['product_id'], 'reason': reason})
            else:
                result['eligible'].append({'product_id': item['product_id'], 'title': item['title']})
        result.update(ready=True, reason='POOL_READY', live_verified=True)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        result['reason'] = 'CATALOG_UNVERIFIED'
    result['exclusion_counts'] = dict(Counter(r['reason'] for r in result['excluded']))
    return result


def promote_live_catalog(data, observation, policy_path, *, expected_catalog_digest, expected_policy_digest):
    """先走既有 CAS/归档，再发布与实际写入字节绑定的凭证；中途失败闭锁。"""
    _, catalog = decode_catalog(json.dumps(data, ensure_ascii=False).encode(), import_only=True)
    validate_observation(dict(catalog, pages=data['pages']), observation)
    path = Path(policy_path).with_name('wechat_product_catalog.json')
    report = import_catalog(json.dumps(data, ensure_ascii=False), path, Path(policy_path),
                            expected_catalog_digest=expected_catalog_digest, expected_policy_digest=expected_policy_digest)
    expected = hashlib.sha256((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest()
    proof_path = attestation_path(policy_path)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if catalog_digest(path) != expected:
            raise PolicyConflict('目录在采集凭证落盘前变化；未提升 live 状态')
        if proof_path.exists():
            previous = proof_path.read_bytes()
            archive = proof_path.with_name('wechat_product_catalog_live_history') / (hashlib.sha256(previous).hexdigest() + '.json')
            if not archive.exists():
                atomic_json(archive, {'original_digest': hashlib.sha256(previous).hexdigest(), 'observation': json.loads(previous)})
        atomic_json(proof_path, dict(observation, catalog_digest=expected))
    return dict(report, live_verified=True, catalog_digest=expected,
                attestation_digest=hashlib.sha256(proof_path.read_bytes()).hexdigest())

"""共享任务商品契约：DAL 冻结一次；上传器只消费冻结快照。"""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
import json
import hashlib
import math
from pathlib import Path
from video_processing.core.wechat_product_attachment import attachment_decision, STOP_STATES
from video_processing.core.wechat_product_policy import ProductIdentity, parse_product_policy
from video_processing.utils.wechat_product_config import load_policy, decision_payload, atomic_json
from video_processing.utils.wechat_product_catalog import catalog_view

PUBLISHER_CAPABILITY = 'wechat-product-task-v2'


def product_profile_scope(state_path: Path) -> str:
    """会话路径是内部计数范围；不读取登录态，也不冒充平台账号 ID。"""
    return 'local-profile:' + hashlib.sha256(str(Path(state_path).resolve()).encode()).hexdigest()[:24]


def serializable_source_context(context: dict) -> dict:
    result = dict(context)
    for field in ('view_count', 'like_count'):
        value = result.get(field)
        if isinstance(value, float) and not math.isfinite(value):
            result[field] = repr(value)
            result[field + '_raw_type'] = 'nonfinite_float'
    return result


def manual_product_options(policy_path: Path) -> dict:
    policy = load_policy(policy_path)
    config = json.loads(policy.serialized)
    catalog = catalog_view(policy_path.with_name('wechat_product_catalog.json'), config['products'])
    library = config.get('library', {})
    accounts = {r['account_id'] for r in library.values() if r['identity_status'] == 'VERIFIED' and r['account_id']}
    account = catalog.get('account_id') or (next(iter(accounts)) if len(accounts) == 1 else None)
    by_id = {i['product_id']: i for i in catalog.get('items', [])}
    rows = []
    products = dict(catalog['products'])
    for alias, row in library.items():
        products.setdefault(alias, row)
    for alias, product in products.items():
        lib, item = library.get(alias), by_id.get(product['product_id'], {})
        identity_verified = bool((lib and lib['identity_status'] == 'VERIFIED' and lib['account_id'] == account)
                                 or (catalog.get('account_id') == account and account and item
                                     and item['title'] == product['title']))
        reason = ''
        eligibility_status = 'READY'
        historical_exact = bool(item and item['title'] == product['title'] and not catalog.get('account_id'))
        if not product.get('enabled') or (lib and not lib.get('enabled')):
            reason = '商品已停用'
            eligibility_status = 'DISABLED'
        elif lib and lib.get('identity_status') == 'VERIFIED' and account and lib.get('account_id') != account:
            reason = '已核实商品归属与当前目录账号冲突'
            eligibility_status = 'IDENTITY_CONFLICT'
        elif item.get('stock') == 0:
            reason = '历史清单库存为零，等待商品库存恢复'
            eligibility_status = 'OUT_OF_STOCK'
        elif historical_exact:
            # 历史目录提供精确平台身份；当前会话严格搜索/选中/绑定回读后才证明可挂载。
            pass
        elif not identity_verified:
            reason = '商品身份或所属发布账号未核实'
            eligibility_status = 'IDENTITY_UNVERIFIED'
        rows.append({'alias': alias, 'product_id': product['product_id'], 'title': product['title'],
                     'shop': (lib or {}).get('shop') or item.get('shop', ''),
                     'selectable': not reason, 'reason': reason,
                     'eligibility_status': eligibility_status,
                     'identity_status': 'VERIFIED_CATALOG' if identity_verified else
                     ('HISTORICAL_PENDING_SESSION_CHECK' if historical_exact else 'UNVERIFIED'),
                     'verification_note': '历史精确 ID 与全名，发布时须在当前会话严格核实' if historical_exact else ''})
    return {k: catalog.get(k) for k in ('captured_at', 'completeness', 'source', 'error', 'live_verified')} | {
        'account_id': account, 'products': rows, 'config_digest': policy.digest}


def validate_manual_product(policy_path: Path, alias: str) -> dict:
    row = next((r for r in manual_product_options(policy_path)['products'] if r['alias'] == alias), None)
    if row is None or not row['selectable']:
        raise ValueError(row['reason'] if row else '商品不存在，请重新载入商品清单')
    return row


def selection_from_task(payload: dict):
    if payload.get('require_product') is not True:
        raise ValueError('只有明确要求商品的任务可调用选品器')
    policy = parse_product_policy(payload['policy_snapshot'])
    if policy.digest != payload['config_digest'] or policy.version != payload['config_version']:
        raise ValueError('冻结的商品策略摘要/版本不一致')
    context = payload['context']
    keys = ('category', 'source_channel_id', 'content_type', 'product_topic')
    decision = policy.decide(**{k: context.get(k) for k in keys})
    if payload['product_intent'] == 'PRODUCT':
        identity = ProductIdentity(context['product_id'], context['product_title'])
        decision = replace(decision, reason='MANUAL_EXACT', candidates=(identity,))
    if decision_payload(decision) != payload['product_decision']:
        raise ValueError('冻结的选品决定不一致')
    return policy, decision


def freeze_task_product_decision(db, task_id: str, context: dict, policy_path: Path, *, now=None) -> dict:
    old = db.get_product_task_decision(task_id)
    if old:
        return old
    if context.get('status') in STOP_STATES:
        raise ValueError('已上传/受理或结果不明任务禁止为商品规则重传')
    context = serializable_source_context(context)
    if context.get('legacy_pre_cutover') and not db.is_legacy_product_review(
            context.get('legacy_review_id'), context.get('legacy_manifest_sha256')):
        raise ValueError('旧包兼容需要首次迁移时的审核 ID 与产物摘要')
    production = db.get_product_production(context.get('production_task_id') or task_id)
    outcome = attachment_decision(context, production)
    payload = dict(outcome, task_id=task_id, context=context,
                   frozen_at=(now or datetime.now(timezone.utc)).isoformat(),
                   publisher_capability=PUBLISHER_CAPABILITY, policy_snapshot=None,
                   config_version=None, config_digest=None, product_decision=None)
    if outcome['require_product']:
        policy = load_policy(policy_path)
        payload.update(policy_snapshot=json.loads(policy.serialized), config_version=policy.version, config_digest=policy.digest)
        keys = ('category', 'source_channel_id', 'content_type', 'product_topic')
        decision = policy.decide(**{k: context.get(k) for k in keys})
        if outcome['product_intent'] == 'PRODUCT':
            # 入队已验证身份；发布时再次验证有效性，不允许默认回退另一商品。
            choices = manual_product_options(policy_path)['products']
            matches = [r for r in choices if r['product_id'] == context['product_id'] and r['title'] == context['product_title']]
            if len(matches) != 1:
                payload['selection_block_reason'] = 'MANUAL_PRODUCT_IDENTITY_UNVERIFIED'
            elif matches[0]['eligibility_status'] not in {'READY', 'OUT_OF_STOCK'}:
                payload['selection_block_reason'] = 'MANUAL_PRODUCT_' + matches[0]['eligibility_status']
            elif matches[0]['identity_status'] not in {'VERIFIED_CATALOG', 'HISTORICAL_PENDING_SESSION_CHECK'}:
                payload['selection_block_reason'] = 'MANUAL_PRODUCT_IDENTITY_UNVERIFIED'
            decision = replace(decision, reason='MANUAL_EXACT', candidates=(ProductIdentity(context['product_id'], context['product_title']),))
        payload['product_decision'] = decision_payload(decision)
    else:
        try:
            policy = load_policy(policy_path)
            payload.update(config_version=policy.version, config_digest=policy.digest)
        except (ValueError, OSError):
            payload['policy_status'] = 'UNAVAILABLE_SKIP_HAS_NO_PRODUCT_DEPENDENCY'
    return db.freeze_product_task_decision(task_id, payload)


def write_product_task_arguments(decision: dict, evidence_dir: Path) -> list[str]:
    path = Path(evidence_dir) / 'product_task_decision.json'
    atomic_json(path, decision)
    return ['--product-task-decision', str(path)]


def read_product_task_decision(path: Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or payload.get('publisher_capability') != PUBLISHER_CAPABILITY:
        raise ValueError('商品任务契约未知')
    expected = attachment_decision(payload['context'], payload.get('production'))
    for key in ('attachment_version', 'product_intent', 'require_product', 'reason', 'threshold_percent', 'metrics'):
        if payload.get(key) != expected[key]:
            raise ValueError('商品任务决定与冻结输入不一致')
    if payload['require_product']:
        selection_from_task(payload)
    return payload

"""新内容匹配合同的冻结与纯重放；旧商品合同由原模块继续处理。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| content-match-v1 | 2026-11-02 | Codex | 对应分片对白证据、独立同步、当前池冻结与版本校验；不重算旧任务。 |
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from config.settings import settings
from video_processing.core.wechat_product_attachment import attachment_decision
from video_processing.core.wechat_product_matching import MATCH_VERSION, CONTENT_VERSION, digest, rank_products
from video_processing.core.wechat_product_policy import ProductDecision, ProductIdentity, ProductRole, parse_product_policy
from video_processing.utils.wechat_product_config import load_policy, decision_payload
from video_processing.utils.wechat_product_pool import load_live_pool


def dialogue_text(text):
    lines = []
    for line in text.splitlines():
        if not line.startswith('Dialogue:'):
            continue
        cells = line.split(',', 9)
        if len(cells) != 10 or cells[3].lower() not in {'default', 'english', 'chinese', 'en', 'zh', 'bilingual'}:
            continue
        if re.search(r'\\p[1-9]', cells[9]):
            continue
        lines.append(re.sub(r'\{[^}]*\}', '', cells[9]).replace('\\N', ' ').replace('\\n', ' '))
    return '\n'.join(dict.fromkeys(lines))


def _bounded(text, limit=64000):
    if len(text) <= limit:
        return text
    # 均匀抽取原文片段，避免长片只看到开场；不生成模型摘要。
    size, count = 1000, limit // 1000
    return '\n'.join(text[round(i * (len(text)-size)/(count-1)):round(i * (len(text)-size)/(count-1))+size]
                     for i in range(count))[:limit]


def _english_evidence(result, context):
    """只读哈希绑定的本分片清单/展示计划；不借用同 YouTube ID 的父片字幕。"""
    def bound(path, expected, role):
        path = Path(path)
        if not expected or path.stat().st_size > 2_000_000:
            raise ValueError('英语分片内容缺少有界摘要')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('英语分片内容摘要变化')
        result['sources'].append({'role': role, 'path': str(path), 'sha256': expected})
        return raw.decode('utf-8')
    try:
        title = context.get('matching_title') or {}
        if title:
            result['title'] = bound(title['path'], title['sha256'], 'package_title').strip()[:4000]
        reference = context.get('matching_manifest') or {}
        if reference:
            manifest = json.loads(bound(reference['path'], reference['sha256'], 'package_manifest'))
            timeline = Path(manifest['timeline'])
            plan_path = timeline.parent / 'display_plan.json'
            if plan_path.stat().st_size > 2_000_000:
                raise ValueError('展示计划过大')
            plan = json.loads(plan_path.read_text())
            if digest(plan) != manifest['display_plan_sha256']:
                raise ValueError('展示计划与本分片清单不一致')
            data = json.loads(bound(timeline, plan['timeline_sha256'], 'segment_timeline'))
            result['title'] = result['title'] or str(data.get('headline_zh') or data.get('headline_en') or '')[:4000]
            result['subtitle'] = _bounded('\n'.join(str(data.get(k) or '') for k in ('english_text', 'translation_zh')))
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        result['content_status'] = 'SEGMENT_EVIDENCE_INCOMPLETE'
    return dict(result, digest=digest(result))


def content_evidence(policy_path, task_id, context):
    output = Path(policy_path).parent.parent / 'output'
    result = {'extraction_version': CONTENT_VERSION, 'title': str(context.get('video_title') or context.get('title') or '')[:4000],
              'subtitle': '', 'category': context.get('category'), 'product_topic': context.get('product_topic'),
              'tags': [s[:100] for s in (context.get('tags') or []) if isinstance(s, str)][:100], 'sources': []}
    if context.get('content_type') == 'ENGLISH_WORLD_SHORT':
        return _english_evidence(result, context)
    match = re.fullmatch(r'pipeline:([A-Za-z0-9_-]{1,80}):([0-9]+)', task_id)
    yid = context.get('youtube_id')
    index = context.get('slice_index', 0)
    if match:
        yid, index = match[1], int(match[2])
    if not isinstance(yid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', yid) or type(index) is not int or index < 0:
        return dict(result, digest=digest(result))
    prefix = f'{yid}_s{index}' if index else yid

    def read(path, role):
        try:
            if path.stat().st_size > 2_000_000:
                return ''
            raw = path.read_bytes()
            text = raw.decode('utf-8')
            result['sources'].append({'role': role, 'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
            return text
        except (OSError, UnicodeError):
            return ''

    title = read(output / f'{prefix}_title.txt', 'render_title')
    subhead = read(output / f'{prefix}_subtitle.txt', 'cover_subtitle')
    if title:
        result['title'] = (title.strip() + ' ' + subhead.strip())[:4000]
    ass = read(output / f'{prefix}.ass', 'dialogue_ass')
    result['subtitle'] = _bounded(dialogue_text(ass))
    # 分片不借用父片标题/标签/字幕；非分片才可采用源公开元数据。
    if not index:
        try:
            info = json.loads(read(output / f'{yid}.info.json', 'source_metadata') or '{}')
            if not result['title']:
                result['title'] = str(info.get('title') or '')[:4000]
            result['tags'] = list(dict.fromkeys(result['tags'] + [s[:100] for s in info.get('tags', []) if isinstance(s, str)]))[:100]
        except (ValueError, AttributeError, TypeError):
            pass
    result['digest'] = digest(result)
    return result


def _match(payload):
    policy = parse_product_policy(payload['policy_snapshot'])
    if policy.digest != payload['config_digest'] or policy.version != payload['config_version']:
        raise ValueError('冻结策略版本不一致')
    inputs = payload['matching_snapshot']
    if digest(inputs) != payload['matching_digest']:
        raise ValueError('冻结内容匹配摘要不一致')
    if inputs['algorithm_version'] != MATCH_VERSION or inputs['config_digest'] != digest(inputs['config']):
        raise ValueError('冻结算法或匹配配置摘要不一致')
    content = inputs['content']
    if (content['extraction_version'] != CONTENT_VERSION
            or content['digest'] != digest({k: v for k, v in content.items() if k != 'digest'})):
        raise ValueError('冻结内容提取版本或摘要不一致')
    ranked = rank_products(content, inputs['pool'], inputs['config'], max_attempts=policy.max_attempts,
                           english=payload['context'].get('content_type') == 'ENGLISH_WORLD_SHORT')
    keys = ('category', 'source_channel_id', 'content_type', 'product_topic')
    decision = ProductDecision(ProductRole.DEFAULT, ranked['reason'], rule_version=MATCH_VERSION,
                               config_digest=policy.digest,
                               candidates=tuple(ProductIdentity(**p) for p in ranked['candidates']),
                               max_attempts=policy.max_attempts, timeout_seconds=min(30, policy.timeout_seconds),
                               context=tuple((k, payload['context'].get(k)) for k in keys),
                               video_group='english_world' if payload['context'].get('content_type') == 'ENGLISH_WORLD_SHORT' else 'other',
                               group_reason='当前有效商品池与L1特定主题')
    return policy, decision, ranked


def freeze_matching_payload(policy_path, task_id, context, production, config, *, now=None):
    now = now or datetime.now(timezone.utc)
    pool = load_live_pool(policy_path, now=now)
    sync_result = None
    if pool['reason'] == 'CATALOG_STALE' and Path(policy_path).resolve() == settings.wechat_product_policy_path.resolve():
        from video_processing.core.wechat_session_lock import current_wechat_session
        if current_wechat_session() is None:
            from video_processing.utils.wechat_product_sync import run_catalog_sync
            sync_result = run_catalog_sync(Path(policy_path))
            pool = load_live_pool(policy_path, now=datetime.now(timezone.utc))
        else:
            sync_result = {'reason': 'SYNC_IN_PUBLISH_SESSION_DEFERRED'}
    policy = load_policy(policy_path)
    inputs = {'algorithm_version': MATCH_VERSION, 'content': content_evidence(policy_path, task_id, context),
              'pool': pool, 'config': config, 'config_digest': digest(config), 'sync_result': sync_result}
    payload = dict(attachment_decision(context, production), attachment_version=MATCH_VERSION,
                   admission_mode='MATCH_IF_POOL_READY', threshold_percent=None,
                   task_id=task_id, context=context, frozen_at=now.isoformat(),
                   publisher_capability='wechat-product-task-v2', policy_snapshot=json.loads(policy.serialized),
                   config_version=policy.version, config_digest=policy.digest,
                   matching_snapshot=inputs, matching_digest=digest(inputs))
    _, decision, ranked = _match(payload)
    payload.update(require_product=bool(decision.candidates), reason=ranked['reason'],
                   product_decision=decision_payload(decision), match_scores=ranked['scores'])
    return payload


def validate_matching_payload(payload):
    if payload.get('attachment_version') != MATCH_VERSION or payload.get('admission_mode') != 'MATCH_IF_POOL_READY':
        raise ValueError('未知内容匹配合同')
    expected = attachment_decision(payload['context'], payload.get('production'))
    english = payload['context'].get('content_type') == 'ENGLISH_WORLD_SHORT'
    if not english and expected['product_intent'] != 'AUTO':
        raise ValueError('人工意图不得借用自动匹配合同')
    policy, decision, ranked = _match(payload)
    if (payload.get('require_product') is not bool(decision.candidates) or payload.get('reason') != ranked['reason']
            or payload.get('match_scores') != ranked['scores'] or payload.get('product_decision') != decision_payload(decision)
            or payload.get('threshold_percent') is not None or payload.get('metrics') != expected['metrics']
            or payload.get('product_intent') != expected['product_intent']):
        raise ValueError('内容匹配决定与冻结输入不一致')
    return policy, decision


def matching_receipt_fields(payload):
    if payload.get('attachment_version') != MATCH_VERSION:
        return {}
    pool = payload['matching_snapshot']['pool']
    return {k: pool.get(k) for k in ('catalog_digest', 'attestation_digest', 'captured_at', 'account_id',
                                     'age_seconds', 'ttl_seconds', 'live_verified', 'completeness')} | {
        'matching_version': MATCH_VERSION, 'matching_digest': payload['matching_digest'],
        'content_digest': payload['matching_snapshot']['content']['digest'], 'match_scores': payload['match_scores']}

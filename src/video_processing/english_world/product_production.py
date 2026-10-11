"""独立英语世界的正式制作身份与商品上下文；不在投稿时补登记。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from video_processing.core.wechat_product_attachment import validate_intent
from video_processing.utils.wechat_product_task import product_profile_scope


def _profile_scope(state_path: Path | None) -> str:
    if state_path is None:
        from config.settings import settings
        state_path = settings.default_output_dir / 'wechat_state.json'
    return product_profile_scope(state_path)


def production_task_id(payload: dict) -> str:
    """同一来源片段跨工作目录重试保持身份，不同片段独立计数。"""
    if payload.get('content_type') != 'ENGLISH_WORLD_SHORT':
        raise ValueError('商品制作登记只接受 ENGLISH_WORLD_SHORT')
    provenance = payload.get('source_provenance')
    if not isinstance(provenance, dict):
        raise ValueError('英语世界商品任务缺少来源身份')
    youtube_id = provenance.get('youtube_id')
    if not isinstance(youtube_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', youtube_id):
        raise ValueError('英语世界商品任务缺少合法 YouTube ID')
    interval = []
    for name in ('source_start_seconds', 'source_end_seconds'):
        value = provenance.get(name)
        try:
            if isinstance(value, bool):
                raise ValueError()
            number = Decimal(str(value))
            if not number.is_finite() or number < 0:
                raise ValueError()
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError('英语世界商品任务来源区间无效') from exc
        interval.append(number)
    if interval[1] <= interval[0]:
        raise ValueError('英语世界商品任务来源区间无效')
    raw = json.dumps([youtube_id, *(format(n.normalize(), 'f') for n in interval)], separators=(',', ':'))
    return f'english-world:{youtube_id}:{hashlib.sha256(raw.encode()).hexdigest()[:24]}'


def _require_preproduction(payload: dict) -> None:
    """已有翻译/富化/发表文案的旧包不能通过首次登记改写历史。"""
    if payload.get('publication_text') or payload.get('learning_points') or payload.get('vocabulary_candidates'):
        raise ValueError('必须在翻译或词汇富化前登记；不能为旧制作包补占首条')
    texts = [payload.get('translation_zh')]
    texts.extend(p.get('translation_zh') for p in payload.get('paragraphs', []) if isinstance(p, dict))
    if any(value not in (None, '', '来源预检中') for value in texts):
        raise ValueError('必须在翻译或词汇富化前登记；不能为旧制作包补占首条')


def start_product_production(db, payload: dict, *, product_intent='AUTO', product_id=None,
                             product_title=None, state_path: Path | None = None, now=None) -> dict:
    """正式节点调用：AUTO 原子登记；人工 NONE/PRODUCT 不占自动名额。"""
    validate_intent(product_intent, product_id, product_title)
    task_id = production_task_id(payload)
    previous = payload.get('product_context')
    if previous is not None:
        if not isinstance(previous, dict):
            raise ValueError('正式制作商品上下文无效')
        for key, expected in (('product_intent', product_intent), ('product_id', product_id),
                              ('product_title', product_title)):
            if previous.get(key) != expected:
                raise ValueError('已正式开始制作的商品意图不可变更')
        verify_product_production_context(db, payload, state_path=state_path)
        return payload
    _require_preproduction(payload)
    if product_intent != 'AUTO' and db is not None and db.get_product_production(task_id):
        raise ValueError('本来源片段已经按自动任务正式登记，不得改为人工商品意图')
    provenance = payload['source_provenance']
    context = {
        'task_id': task_id, 'production_task_id': task_id,
        'youtube_id': provenance['youtube_id'], 'content_type': 'ENGLISH_WORLD_SHORT',
        'product_intent': product_intent, 'product_id': product_id, 'product_title': product_title,
        'source_channel_id': provenance.get('channel_id'),
        'view_count': provenance.get('view_count'), 'like_count': provenance.get('like_count'),
        'product_profile_scope': _profile_scope(state_path),
    }
    result = dict(payload, product_context=context)
    if product_intent == 'AUTO':
        result['product_production'] = db.register_product_production(
            task_id, account_id=context['product_profile_scope'], now=now,
        )
    return result


def verify_product_production_context(db, payload: dict, *, state_path: Path | None = None) -> dict:
    """渲染与投稿只验证登记，不创建登记；缺失即明确阻断。"""
    task_id = production_task_id(payload)
    context = payload.get('product_context')
    if not isinstance(context, dict):
        raise ValueError('英语世界缺少正式制作商品上下文，不能在发布时补占首条')
    if (context.get('task_id') != task_id or context.get('production_task_id') != task_id
            or context.get('content_type') != 'ENGLISH_WORLD_SHORT'
            or context.get('youtube_id') != payload['source_provenance']['youtube_id']):
        raise ValueError('英语世界商品上下文与实际来源片段不一致')
    validate_intent(context.get('product_intent'), context.get('product_id'), context.get('product_title'))
    scope = _profile_scope(state_path)
    if context.get('product_profile_scope') != scope:
        raise ValueError('英语世界商品上下文与实际发布会话范围不一致')
    if context['product_intent'] == 'AUTO':
        registered = db.get_product_production(task_id)
        if (not registered or payload.get('product_production') != registered
                or registered.get('account_id') != scope):
            raise ValueError('英语世界正式制作登记缺失或与清单不一致，不能在发布时补登记')
    elif payload.get('product_production') or db.get_product_production(task_id):
        raise ValueError('人工商品任务不得占用自动英语世界首条名额')
    return dict(context)


def attach_product_context_to_manifest(db, payload: dict, manifest_path: Path,
                                      *, state_path: Path | None = None) -> None:
    """仅在本次新渲染生成清单后传播，历史未登记清单不补写。"""
    if 'product_context' not in payload:
        return
    verify_product_production_context(db, payload, state_path=state_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['source_provenance'] = payload['source_provenance']
    manifest['product_context'] = payload['product_context']
    if payload.get('product_production'):
        manifest['product_production'] = payload['product_production']
    from video_processing.utils.wechat_product_config import atomic_json
    atomic_json(manifest_path, manifest)

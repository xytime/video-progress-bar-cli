"""商品挂载资格纯规则；候选/预览不占英语世界制作名额。"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import math

ATTACHMENT_VERSION = 'wechat-product-attachment-v2'
INTENTS = {'AUTO', 'NONE', 'PRODUCT'}
STOP_STATES = {'PUBLISHED', 'UNDER_REVIEW', 'SUBMITTED_BOUND', 'SUBMITTED_UNBOUND', 'UNCERTAIN', 'PUBLISHING'}


def validate_intent(intent, product_id=None, product_title=None):
    if intent not in INTENTS:
        raise ValueError('商品意图必须为 AUTO、NONE 或 PRODUCT')
    if intent == 'PRODUCT':
        if not all(isinstance(v, str) and v.strip() == v and v for v in (product_id, product_title)):
            raise ValueError('人工商品必须包含核实的精确 ID 和完整名称')
    elif product_id or product_title:
        raise ValueError('未指定商品的任务不能包含商品身份')


def metrics(view_count, like_count):
    def raw(value):
        return repr(value) if isinstance(value, float) and not math.isfinite(value) else value
    result = {'view_count': raw(view_count), 'like_count': raw(like_count), 'like_rate_percent': None, 'status': 'UNKNOWN'}
    if view_count is None or like_count is None:
        return result
    try:
        if isinstance(view_count, bool) or isinstance(like_count, bool):
            raise ValueError()
        views, likes = Decimal(str(view_count)), Decimal(str(like_count))
        if not views.is_finite() or not likes.is_finite() or views <= 0 or likes < 0 or likes > views:
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        return dict(result, status='INVALID')
    return dict(result, status='VALID', like_rate_percent=str(likes / views * 100),
                meets_threshold=likes * 100 >= views * 10)


def attachment_decision(context: dict, production: dict | None = None, *, preview=False) -> dict:
    intent = context.get('product_intent') or 'AUTO'
    validate_intent(intent, context.get('product_id'), context.get('product_title'))
    source = metrics(context.get('view_count'), context.get('like_count'))
    if intent == 'NONE':
        required, reason = False, 'SKIP_MANUAL_NONE'
    elif intent == 'PRODUCT':
        required, reason = True, 'ATTACH_MANUAL'
    elif context.get('content_type') == 'ENGLISH_WORLD_SHORT':
        if production is None:
            if context.get('legacy_pre_cutover') is True:
                required, reason = False, 'SKIP_LEGACY_PRE_CUTOVER'
            elif not preview:
                raise ValueError('英语世界任务没有正式制作登记，不能在发布时补占首条')
            else:
                required, reason = None, 'ENGLISH_FIRST_NOT_REGISTERED'
        else:
            required = production['is_first']
            reason = 'ATTACH_ENGLISH_FIRST' if required else 'SKIP_ENGLISH_LATER'
    elif not context.get('youtube_id'):
        required, reason = False, 'SKIP_METRICS_UNKNOWN'
    elif source['status'] != 'VALID':
        required, reason = False, 'SKIP_METRICS_UNKNOWN' if source['status'] == 'UNKNOWN' else 'SKIP_METRICS_INVALID'
    else:
        required = source['meets_threshold']
        reason = 'ATTACH_THRESHOLD' if required else 'SKIP_BELOW_THRESHOLD'
    return {'attachment_version': ATTACHMENT_VERSION, 'product_intent': intent,
            'require_product': required, 'reason': reason, 'threshold_percent': 10,
            'metrics': source, 'production': production, 'preview_only': preview}

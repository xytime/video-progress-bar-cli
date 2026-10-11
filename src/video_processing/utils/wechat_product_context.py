"""预览与发布共享的选品上下文；只读取具名视频的公开元数据。"""
from __future__ import annotations
import json
from pathlib import Path
import re


def video_product_context(output: Path, video: dict) -> dict:
    if video.get('content_type') == 'ENGLISH_WORLD_SHORT':
        return {'content_type': 'ENGLISH_WORLD_SHORT', 'category': None,
                'source_channel_id': None, 'product_topic': None}
    yid = video.get('youtube_id') or ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', yid):
        raise ValueError('非法视频 ID')
    index = video.get('slice_index') or 0
    if type(index) is not int or index < 0:
        raise ValueError('非法分片编号')
    prefix = f'{yid}_s{index}' if index else yid
    info = {}
    info_path = output / f'{yid}.info.json'
    if info_path.exists():
        info = json.loads(info_path.read_text(encoding='utf-8'))
        if not isinstance(info, dict):
            raise ValueError('视频元数据必须为对象')
    category = video.get('category')
    category_path = output / f'{prefix}_category.txt'
    if category_path.exists():
        category = category_path.read_text(encoding='utf-8').strip()
    result = {'content_type': video.get('content_type') or info.get('content_type') or 'GENERAL',
              'source_channel_id': video.get('channel_id') or video.get('source_channel_id') or info.get('channel_id'),
              'category': category,
              'product_topic': video.get('product_topic') or info.get('product_topic')}
    if any(v is not None and not isinstance(v, str) for v in result.values()):
        raise ValueError('选品上下文字段必须为字符串')
    return result


def product_context_arguments(context: dict) -> list[str]:
    """传输固定选品字段；分类快照与平台表单的 category-file 分开。"""
    result = []
    for key in ('content_type', 'source_channel_id', 'product_topic', 'category'):
        if context.get(key):
            result.extend(['--product-category' if key == 'category' else '--' + key.replace('_', '-'), context[key]])
    return result

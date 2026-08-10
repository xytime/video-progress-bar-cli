# -*- coding: utf-8 -*-
"""内容生产类型的稳定标识。

内容类型描述制作形态，不等同于视频号的平台分类（如“教育”“科技”）。本模块
不依赖数据库、发布器或渲染器，供各层以同一常量写入和读取。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-09 | Codex | 新增英语世界短视频的跨流程内容类型标识。 |
"""

from __future__ import annotations


CONTENT_TYPE_GENERAL = "GENERAL"
CONTENT_TYPE_ENGLISH_WORLD_SHORT = "ENGLISH_WORLD_SHORT"
VALID_CONTENT_TYPES = frozenset({
    CONTENT_TYPE_GENERAL,
    CONTENT_TYPE_ENGLISH_WORLD_SHORT,
})


def normalize_content_type(value: str | None) -> str:
    """校验并规范化内容生产类型；空值兼容为通用视频。"""
    normalized = (value or CONTENT_TYPE_GENERAL).strip().upper()
    if normalized not in VALID_CONTENT_TYPES:
        allowed = ", ".join(sorted(VALID_CONTENT_TYPES))
        raise ValueError(f"未知内容类型: {value!r}；仅支持 {allowed}")
    return normalized

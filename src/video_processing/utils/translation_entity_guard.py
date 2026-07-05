# -*- coding: utf-8 -*-
"""翻译实体保真工具。

抽取源内容中应在中文译文里保持可识别的英文实体，并检查整片候选是否
完全丢失这些实体。本模块不调用翻译 API，也不依赖字幕/文案流程。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：抽取受保护英文实体并检查译文是否整片丢失 |
| 1.1.0   | 2026-07-06 | Codex  | 收紧全大写实体过滤，避免标题普通词全大写造成误报 |
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, List, Sequence


_ENTITY_PATTERN = re.compile(
    r"\b(?:[A-Z][A-Z0-9&.-]{1,9}|[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]+)+)\b"
)

_ENTITY_STOPWORDS = {
    "AI", "API", "AUM", "CEO", "CFO", "CTO", "EU", "ETF", "GDP", "GP",
    "IPO", "LP", "LLC", "PE", "SEC", "TV", "UK", "UN", "US", "USD",
    "VC", "YouTube",
}

_ENTITY_ALIASES = {
    "NVIDIA": ("英伟达",),
    "TSMC": ("台积电",),
    "UAE": ("阿联酋",),
}


def extract_protected_entities(
    texts: Sequence[str] | str,
    *,
    min_occurrences: int = 1,
    limit: int = 8,
) -> List[str]:
    """抽取需要在译文中保持可识别的英文实体。"""
    corpus = _join_texts([texts] if isinstance(texts, str) else texts)
    if not corpus:
        return []

    counts: Counter[str] = Counter()
    first_positions: dict[str, int] = {}
    for match in _ENTITY_PATTERN.finditer(corpus):
        entity = _normalize_entity(match.group(0))
        if not _is_protected_entity(entity):
            continue
        counts[entity] += 1
        first_positions.setdefault(entity, match.start())

    ranked = sorted(
        (
            entity
            for entity, count in counts.items()
            if count >= min_occurrences
        ),
        key=lambda entity: (-counts[entity], first_positions[entity], entity),
    )
    return ranked[:limit]


def find_missing_protected_entities(
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
    *,
    protected_entities: Sequence[str] | None = None,
    min_source_occurrences: int = 2,
) -> List[str]:
    """找出源内容中受保护、但整份译文完全不可见的英文实体。"""
    entities = list(protected_entities or extract_protected_entities(
        source_texts,
        min_occurrences=min_source_occurrences,
    ))
    translated_corpus = _join_texts(translated_texts)
    return [
        entity
        for entity in entities
        if not _entity_visible_in_translation(entity, translated_corpus)
    ]


def _entity_visible_in_translation(entity: str, translated_text: str) -> bool:
    if not translated_text:
        return False
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(entity)}(?![A-Za-z0-9])", translated_text, re.IGNORECASE):
        return True
    return any(alias in translated_text for alias in _ENTITY_ALIASES.get(entity, ()))


def _is_protected_entity(entity: str) -> bool:
    if not entity or entity in _ENTITY_STOPWORDS:
        return False
    if len(entity) < 3:
        return False
    if entity.isupper():
        return (
            len(entity) <= 4
            or entity in _ENTITY_ALIASES
            or any(char.isdigit() or char in "&.-" for char in entity)
        )
    return any(char.isupper() for char in entity)


def _normalize_entity(entity: str) -> str:
    return entity.strip(".-")


def _join_texts(texts: Iterable[str]) -> str:
    return "\n".join(text.strip() for text in texts if text and text.strip())

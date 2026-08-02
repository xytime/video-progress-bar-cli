# -*- coding: utf-8 -*-
"""新闻精读卡片的生词难度与密度选择规则。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：以十级难度和全文 25% 密度上限筛选供应商无关的生词候选。 |
| 1.1.0 | 2026-08-03 | Codex | 支持离线词表考试标签，并拒绝低置信度或词典兜底结果进入自动正文标记。 |
| 1.2.0 | 2026-08-03 | Codex | 明确左侧正文微笔记最多十个，右栏可再从中二次筛选最高难度词。 |
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Protocol


MIN_LEARNING_LEVEL = 3
MAX_VOCABULARY_DENSITY = 0.25
MAX_STUDY_NOTE_ITEMS = 10

# 3 级对应 B1/PET：这是面向学习者的展示分级，不假装是某一词典的官方等级。
_CEFR_LEVELS = {
    "a1": 1, "a2": 2, "b1": 3, "b1+": 4, "b2": 5,
    "b2+": 6, "c1": 7, "c1+": 8, "c2": 9, "specialist": 10,
}
_EXAM_LEVELS = {
    "ket": 1, "中考": 2, "pet": 3, "高考": 4, "cet-4": 5,
    "fce": 6, "cet-6": 7, "cae": 8, "master": 9,
}
_FUNCTION_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "that", "the", "their", "this", "to", "was", "were", "with",
})


class VocabularyCandidate(Protocol):
    """筛选器只依赖这三项字段，避免绑定模型、词典或渲染数据结构。"""

    word: str
    meaning_zh: str
    level: str


@dataclass(frozen=True)
class VocabularySelection:
    """选择结果及可审计统计，供 manifest 或质检表直接使用。"""

    items: tuple[VocabularyCandidate, ...]
    lexical_word_count: int
    maximum_items: int
    candidate_count: int

    @property
    def density(self) -> float:
        return len(self.items) / self.lexical_word_count if self.lexical_word_count else 0.0


def difficulty_level(level: str) -> int:
    """将 ``1..10``、CEFR 或离线词表考试标签归一为学习难度。"""
    normalised = level.strip().lower().replace(" ", "")
    if normalised in _CEFR_LEVELS:
        return _CEFR_LEVELS[normalised]
    if normalised in _EXAM_LEVELS:
        return _EXAM_LEVELS[normalised]
    if normalised.isdigit():
        return max(1, min(10, int(normalised)))
    return MIN_LEARNING_LEVEL


def select_vocabulary(
    english_text: str,
    candidates: Iterable[VocabularyCandidate],
    *,
    minimum_level: int = MIN_LEARNING_LEVEL,
    maximum_density: float = MAX_VOCABULARY_DENSITY,
) -> VocabularySelection:
    """从全篇候选词中取学习价值最高者，绝不超过正文可标记词的给定比例。"""
    if not 1 <= minimum_level <= 10:
        raise ValueError("minimum_level 必须在 1 到 10 之间")
    if not 0 < maximum_density <= 1:
        raise ValueError("maximum_density 必须在 0 到 1 之间")

    lexical_word_count = _count_lexical_words(english_text)
    maximum_items = min(MAX_STUDY_NOTE_ITEMS, int(lexical_word_count * maximum_density))
    article_words = _normalise(english_text)
    unique: dict[str, VocabularyCandidate] = {}
    for candidate in candidates:
        key = _normalise(candidate.word)
        if (
            not key
            or not candidate.meaning_zh.strip()
            or not _contains_whole_phrase(article_words, key)
            or difficulty_level(candidate.level) < minimum_level
            or not _has_reliable_offline_evidence(candidate)
        ):
            continue
        current = unique.get(key)
        if current is None or difficulty_level(candidate.level) > difficulty_level(current.level):
            unique[key] = candidate

    ranked = sorted(unique.values(), key=lambda item: (-difficulty_level(item.level), -_word_count(item.word), item.word.lower()))
    return VocabularySelection(tuple(ranked[:maximum_items]), lexical_word_count, maximum_items, len(unique))


def _count_lexical_words(text: str) -> int:
    return sum(word not in _FUNCTION_WORDS for word in re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text.lower()))


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text))


def _normalise(word: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", word.lower()))


def _contains_whole_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _has_reliable_offline_evidence(candidate: VocabularyCandidate) -> bool:
    """保留历史通用候选的兼容性，同时防止未知词被误标成高阶词。"""
    source = str(getattr(candidate, "source", "")).strip().lower()
    confidence = float(getattr(candidate, "confidence", 1.0))
    if not source:
        return True
    return source not in {"unknown", "ecdict-fallback"} and confidence >= 0.85

# -*- coding: utf-8 -*-
"""新闻精读卡片的生词难度与密度选择规则。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：以十级难度筛选供应商无关的生词候选。 |
| 1.1.0 | 2026-08-03 | Codex | 支持离线词表考试标签，并拒绝低置信度或词典兜底结果进入自动正文标记。 |
| 1.2.0 | 2026-08-03 | Codex | 明确左侧正文微笔记最多十个，右栏可再从中二次筛选最高难度词。 |
| 1.3.0 | 2026-08-04 | Codex | 支持按阅读段落保底选择微笔记，避免长正文后段没有左侧学习标记。 |
| 1.3.1 | 2026-08-04 | Codex | 过滤重复出现的低价值短词，避免为了段落覆盖牺牲学习质量。 |
| 1.4.0 | 2026-08-04 | Codex | 将微笔记从全文十项上限改为按阅读屏充足供给；允许有可靠释义的固定短语进入学习池。 |
| 1.5.0 | 2026-08-04 | Codex | 支持每个阅读屏候选段至少保留八个学习点。 |
| 1.6.0 | 2026-08-04 | Codex | 移除全篇数量与密度限制；仅保留候选筛选，实际最少/最多由视觉层按单屏控制。 |
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Protocol


MIN_LEARNING_LEVEL = 3
MIN_STUDY_NOTES_PER_READING_SCREEN = 8

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
    coverage_texts: Iterable[str] | None = None,
    minimum_items_per_coverage: int = 1,
) -> VocabularySelection:
    """从全篇候选词中取学习价值最高者，并为阅读段落保留最少学习标记。"""
    if not 1 <= minimum_level <= 10:
        raise ValueError("minimum_level 必须在 1 到 10 之间")
    if minimum_items_per_coverage < 1:
        raise ValueError("minimum_items_per_coverage 必须为正整数")

    lexical_word_count = _count_lexical_words(english_text)
    article_words = _normalise(english_text)
    unique: dict[str, VocabularyCandidate] = {}
    for candidate in candidates:
        key = _normalise(candidate.word)
        if (
            not key
            or not candidate.meaning_zh.strip()
            or not _contains_whole_phrase(article_words, key)
            or _is_low_value_short_word(article_words, key, candidate)
            or not _is_eligible_learning_item(key, candidate, minimum_level)
            or not _has_reliable_offline_evidence(candidate)
        ):
            continue
        current = unique.get(key)
        if current is None or difficulty_level(candidate.level) > difficulty_level(current.level):
            unique[key] = candidate

    ranked = _rank_candidates(unique.values())
    # 不在候选域施加任何全篇上限；“一屏最少/最多”必须由已知真实排版的视觉层判断。
    maximum_items = len(ranked)
    selected = _select_with_coverage(
        ranked, maximum_items, coverage_texts, minimum_items_per_coverage,
    )
    return VocabularySelection(tuple(selected), lexical_word_count, maximum_items, len(unique))


def _count_lexical_words(text: str) -> int:
    return sum(word not in _FUNCTION_WORDS for word in re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text.lower()))


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text))


def _normalise(word: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", word.lower()))


def _contains_whole_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _is_low_value_short_word(text: str, phrase: str, candidate: VocabularyCandidate) -> bool:
    if " " in phrase or len(phrase) > 3 or difficulty_level(candidate.level) >= 5:
        return False
    return f" {text} ".count(f" {phrase} ") > 2


def _is_eligible_learning_item(
    phrase: str,
    candidate: VocabularyCandidate,
    minimum_level: int,
) -> bool:
    """单词按难度阈值过滤；可靠固定短语可作为整体学习点保留。

    固定短语的教学价值并不等于任一单词的考试级别。例如 ``in the grips
    of`` 的单词均较基础，但整体对学习者仍有价值。未知或低置信度来源仍由
    ``_has_reliable_offline_evidence`` 拦截，避免把猜测性短语带进成片。
    """
    return " " in phrase or difficulty_level(candidate.level) >= minimum_level


def _rank_candidates(candidates: Iterable[VocabularyCandidate]) -> list[VocabularyCandidate]:
    return sorted(
        candidates,
        key=lambda item: (-difficulty_level(item.level), -_word_count(item.word), item.word.lower()),
    )


def _select_with_coverage(
    ranked: list[VocabularyCandidate],
    maximum_items: int,
    coverage_texts: Iterable[str] | None,
    minimum_items_per_coverage: int,
) -> list[VocabularyCandidate]:
    if maximum_items <= 0:
        return []
    if coverage_texts is None:
        return ranked[:maximum_items]

    selected: list[VocabularyCandidate] = []
    selected_keys: set[str] = set()
    for coverage_text in coverage_texts:
        coverage_words = _normalise(coverage_text)
        paragraph_matches = [
            item for item in ranked
            if _normalise(item.word) not in selected_keys
            and _contains_whole_phrase(coverage_words, _normalise(item.word))
        ]
        if not paragraph_matches:
            continue
        for item in paragraph_matches[:minimum_items_per_coverage]:
            selected.append(item)
            selected_keys.add(_normalise(item.word))
            if len(selected) >= maximum_items:
                return selected

    for item in ranked:
        key = _normalise(item.word)
        if key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
        if len(selected) >= maximum_items:
            break
    return selected


def _has_reliable_offline_evidence(candidate: VocabularyCandidate) -> bool:
    """保留历史通用候选的兼容性，同时防止未知词被误标成高阶词。"""
    source = str(getattr(candidate, "source", "")).strip().lower()
    confidence = float(getattr(candidate, "confidence", 1.0))
    if not source:
        return True
    return source not in {"unknown", "ecdict-fallback"} and confidence >= 0.85

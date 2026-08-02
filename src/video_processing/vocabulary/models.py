# -*- coding: utf-8 -*-
"""词汇分级结果的数据契约。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 初始创建：定义供应商无关、JSON 友好的词汇分级输出。 |
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FriendlyTag(str, Enum):
    """面向学习者展示的低压力标签。"""

    BASIC = "基础词"
    PROGRESSIVE = "进阶词"
    NEWS_ADVANCED = "新闻高阶词"


@dataclass(frozen=True)
class WordLevelResult:
    """单词考试分级结果。

    ``recommended_level`` 是按项目自定义优先级取到的最低学习门槛；
    ``covered_syllabi`` 保留所有命中的常见考试/CEFR 标签。
    """

    word: str
    lemma: str
    context_meaning_zh: str
    recommended_level: str
    covered_syllabi: tuple[str, ...]
    friendly_tag: FriendlyTag
    pos: str = ""
    phonetic: str = ""
    source: str = "wordlist"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """返回稳定 JSON 字段，供 CLI、API 或后续流水线直接使用。"""
        return {
            "word": self.word,
            "lemma": self.lemma,
            "context_meaning_zh": self.context_meaning_zh,
            "recommended_level": self.recommended_level,
            "covered_syllabi": list(self.covered_syllabi),
            "friendly_tag": self.friendly_tag.value,
            "pos": self.pos,
            "phonetic": self.phonetic,
            "source": self.source,
            "confidence": self.confidence,
        }

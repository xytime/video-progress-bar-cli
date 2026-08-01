# -*- coding: utf-8 -*-
"""新闻精读卡片的供应商无关输入契约。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：定义独立于采集、AI 与发布流程的新闻精读卡片数据契约。 |
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class StudyWord:
    """一个相对所截片段的逐词时间锚点。"""

    text: str
    start: float
    end: float

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("逐词时间轴不能包含空词")
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"非法逐词时间轴: {self.text!r} {self.start}-{self.end}")


@dataclass(frozen=True)
class VocabularyItem:
    """右栏的一张词汇卡；phonetic/part_of_speech 可以由任意上游补全。"""

    word: str
    meaning_zh: str
    phonetic: str = ""
    part_of_speech: str = ""
    level: str = ""

    def __post_init__(self) -> None:
        if not self.word.strip() or not self.meaning_zh.strip():
            raise ValueError("词汇卡必须包含英文词和中文释义")


@dataclass(frozen=True)
class StudyCardContent:
    """模板渲染所需的纯内容，不包含 URL、模型名或任何供应商细节。"""

    headline_zh: str
    headline_en: str
    english_text: str
    translation_zh: str
    words: tuple[StudyWord, ...]
    vocabulary: tuple[VocabularyItem, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StudyCardContent":
        """从 JSON 友好的字典构造并做最小完整性校验。"""
        words = tuple(
            StudyWord(
                text=str(item["text"]),
                start=float(item["start"]),
                end=float(item["end"]),
            )
            for item in _as_sequence(payload.get("words"), "words")
        )
        vocabulary = tuple(
            VocabularyItem(
                word=str(item["word"]),
                meaning_zh=str(item["meaning_zh"]),
                phonetic=str(item.get("phonetic", "")),
                part_of_speech=str(item.get("part_of_speech", "")),
                level=str(item.get("level", "")),
            )
            for item in _as_sequence(payload.get("vocabulary"), "vocabulary")
        )
        content = cls(
            headline_zh=_required_text(payload, "headline_zh"),
            headline_en=_required_text(payload, "headline_en"),
            english_text=_required_text(payload, "english_text"),
            translation_zh=_required_text(payload, "translation_zh"),
            words=words,
            vocabulary=vocabulary,
        )
        content.validate_word_order()
        return content

    def validate_word_order(self) -> None:
        """保证下游红线只会按单调时间推进。"""
        previous_end = 0.0
        for word in self.words:
            if word.start + 0.001 < previous_end:
                raise ValueError(f"逐词时间轴发生倒退: {word.text!r}")
            previous_end = word.end


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"缺少必填字段: {key}")
    return value


def _as_sequence(value: Any, field_name: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field_name} 必须是对象数组")
    return value

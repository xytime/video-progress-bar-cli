# -*- coding: utf-8 -*-
"""新闻精读卡片的供应商无关输入契约。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：定义独立于采集、AI 与发布流程的新闻精读卡片数据契约。 |
| 1.1.0 | 2026-08-02 | Codex | 增加阅读段落契约，使英文意群、词注与中文段译可严格同步。 |
| 1.2.0 | 2026-08-02 | Codex | 增加全篇生词候选筛选：十级难度从 3 级起，并限制正文标记密度为 25%。 |
| 1.3.0 | 2026-08-03 | Codex | 接受离线词表的学习标签、考试门槛与证据字段，供学习卡以旁路方式展示。 |
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .vocabulary import select_vocabulary


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
    """右栏的一张词汇卡；可携带离线词表的展示与审计信息。"""

    word: str
    meaning_zh: str
    phonetic: str = ""
    part_of_speech: str = ""
    level: str = ""
    friendly_tag: str = ""
    covered_syllabi: tuple[str, ...] = ()
    source: str = ""
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.word.strip() or not self.meaning_zh.strip():
            raise ValueError("词汇卡必须包含英文词和中文释义")


@dataclass(frozen=True)
class StudyParagraph:
    """一个阅读意群：英文读完后，紧跟与其严格对应的中文段译。"""

    english_text: str
    translation_zh: str

    def __post_init__(self) -> None:
        if not self.english_text.strip() or not self.translation_zh.strip():
            raise ValueError("阅读段落必须同时包含英文和中文段译")


@dataclass(frozen=True)
class StudyCardContent:
    """模板渲染所需的纯内容，不包含 URL、模型名或任何供应商细节。"""

    headline_zh: str
    headline_en: str
    english_text: str
    translation_zh: str
    words: tuple[StudyWord, ...]
    vocabulary: tuple[VocabularyItem, ...]
    paragraphs: tuple[StudyParagraph, ...]

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
        vocabulary_candidates = tuple(
            VocabularyItem(
                word=str(item["word"]),
                meaning_zh=str(item["meaning_zh"]),
                phonetic=str(item.get("phonetic", "")),
                part_of_speech=str(item.get("part_of_speech", "")),
                level=str(item.get("recommended_level", item.get("level", ""))),
                friendly_tag=str(item.get("friendly_tag", "")),
                covered_syllabi=tuple(str(label) for label in item.get("covered_syllabi", ())),
                source=str(item.get("source", "")),
                confidence=float(item.get("confidence", 1.0)),
            )
            for item in _as_sequence(
                payload.get("vocabulary_candidates", payload.get("vocabulary")), "vocabulary_candidates"
            )
        )
        english_text = _required_text(payload, "english_text")
        translation_zh = _required_text(payload, "translation_zh")
        paragraph_payload = payload.get("paragraphs")
        paragraphs = (
            tuple(
                StudyParagraph(
                    english_text=_required_text(item, "english_text"),
                    translation_zh=_required_text(item, "translation_zh"),
                )
                for item in _as_sequence(paragraph_payload, "paragraphs")
            )
            if paragraph_payload is not None
            else (StudyParagraph(english_text=english_text, translation_zh=translation_zh),)
        )
        vocabulary = tuple(select_vocabulary(english_text, vocabulary_candidates).items)
        content = cls(
            headline_zh=_required_text(payload, "headline_zh"),
            headline_en=_required_text(payload, "headline_en"),
            english_text=english_text,
            translation_zh=translation_zh,
            words=words,
            vocabulary=vocabulary,
            paragraphs=paragraphs,
        )
        content.validate_word_order()
        content.validate_paragraphs()
        return content

    def validate_word_order(self) -> None:
        """保证下游红线只会按单调时间推进。"""
        previous_end = 0.0
        for word in self.words:
            if word.start + 0.001 < previous_end:
                raise ValueError(f"逐词时间轴发生倒退: {word.text!r}")
            previous_end = word.end

    def validate_paragraphs(self) -> None:
        """段落拆分只能改变阅读层级，不能悄悄篡改逐词朗读正文。"""
        combined = " ".join(paragraph.english_text for paragraph in self.paragraphs)
        if _normalise_english(combined) != _normalise_english(self.english_text):
            raise ValueError("paragraphs 的英文合并结果必须与 english_text 完全一致")


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"缺少必填字段: {key}")
    return value


def _as_sequence(value: Any, field_name: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field_name} 必须是对象数组")
    return value


def _normalise_english(value: str) -> str:
    return " ".join(value.split()).strip().lower()

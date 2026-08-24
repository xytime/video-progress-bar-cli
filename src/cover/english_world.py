"""英语世界短视频封面载荷构建。

将 enriched timeline 中已有的文字、词库和来源信息收敛为可审计的封面输入；
不调用模型，也不生成或猜测学习数据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 新增确定性时间线提取、词汇排序与封面载荷校验。 |
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Mapping


_LEVEL_ORDER = {
    "KET": 1,
    "中考": 2,
    "PET": 3,
    "高考": 4,
    "CET-4": 5,
    "FCE": 6,
    "CET-6": 7,
    "Master": 8,
    "CAE": 9,
}
_SENTENCE_RE = re.compile(r"^.*?[.!?。！？]")


def _first_sentence(text: object, *, fallback: str = "") -> str:
    """取得首个完整句，避免把整段转写塞入封面。"""
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return fallback
    match = _SENTENCE_RE.match(normalized)
    return match.group(0).strip() if match else normalized


def _normalise_ipa(value: object) -> str:
    ipa = str(value or "").strip()
    if not ipa:
        return ""
    return ipa if ipa.startswith("/") else f"/{ipa}/"


def _candidate_items(timeline: Mapping[str, Any], quote_en: str) -> list[dict[str, Any]]:
    """筛掉不可教学展示的伪词条，并按真实课程等级排序。"""
    raw_candidates = timeline.get("vocabulary_candidates") or timeline.get("vocabulary") or []
    if not isinstance(raw_candidates, list):
        return []

    candidates: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_candidates):
        if not isinstance(raw_item, Mapping):
            continue
        word = str(raw_item.get("word") or "").strip()
        meaning = str(raw_item.get("context_meaning_zh") or raw_item.get("meaning_zh") or raw_item.get("meaning") or "").strip()
        level = str(raw_item.get("recommended_level") or "外刊高频").strip()
        friendly_tag = str(raw_item.get("friendly_tag") or "").strip()
        if (
            not word
            or not meaning
            or "'" in word
            or "’" in word
            or not re.search(r"[A-Za-z]", word)
            or not re.search(rf"\b{re.escape(word)}\b", quote_en, re.IGNORECASE)
        ):
            continue
        candidates.append(
            {
                "word": word,
                "ipa": _normalise_ipa(raw_item.get("phonetic") or raw_item.get("ipa")),
                "meaning": meaning,
                "level": " · ".join(part for part in (level, friendly_tag) if part),
                "_rank": _LEVEL_ORDER.get(level, 0),
                "_index": index,
            }
        )

    candidates.sort(key=lambda item: (-item["_rank"], -len(item["word"]), item["_index"]))
    return candidates


def _difficulty_tag(candidates: list[dict[str, Any]]) -> str:
    highest_rank = max((item["_rank"] for item in candidates), default=4)
    if highest_rank >= 7:
        return "★★★★☆ (六级 / 考研 / 雅思)"
    if highest_rank >= 4:
        return "★★★☆☆ (中高考 / 四六级)"
    return "★★☆☆☆ (中考 / KET / PET)"


def _vocab_stat(timeline: Mapping[str, Any], candidates: list[dict[str, Any]]) -> str:
    selection = timeline.get("vocabulary_selection")
    if isinstance(selection, Mapping):
        lexical_word_count = selection.get("lexical_word_count")
        selected_count = selection.get("selected_count")
        if isinstance(lexical_word_count, int) and isinstance(selected_count, int):
            return f"本篇 {lexical_word_count} 词 · {selected_count} 个重点"
    return f"本篇 {len(candidates)} 个可学词"


def build_english_world_cover_payload(timeline: Mapping[str, Any], *, date_str: str | None = None) -> dict[str, Any]:
    """从已富集时间线构建英语世界封面 payload。"""
    if not isinstance(timeline, Mapping):
        raise ValueError("timeline 必须是 JSON object")
    title = str(timeline.get("headline_zh") or "英语时事精读").strip()
    quote_en = _first_sentence(timeline.get("english_text"))
    quote_zh = _first_sentence(timeline.get("translation_zh"))
    if not quote_en or not quote_zh:
        raise ValueError("timeline 缺少可用于封面的中英文首句")

    ranked_candidates = _candidate_items(timeline, quote_en)
    vocab_items = [{key: value for key, value in item.items() if not key.startswith("_")} for item in ranked_candidates[:2]]
    source_provenance = timeline.get("source_provenance")
    source_provenance = source_provenance if isinstance(source_provenance, Mapping) else {}
    publisher = str(source_provenance.get("publisher") or source_provenance.get("source_channel") or "原声精选").strip()

    return {
        "content_type": "ENGLISH_WORLD_SHORT",
        "title": title,
        "subtitle": "● 英语新闻 · 原声双语精读",
        "quote_en": quote_en,
        "quote_zh": quote_zh,
        "highlight_words": [item["word"] for item in vocab_items],
        "vocab_items": vocab_items,
        "difficulty_tag": _difficulty_tag(ranked_candidates),
        "vocab_stat": _vocab_stat(timeline, ranked_candidates),
        "audio_source": f"{publisher} 原声",
        "date_str": date_str or f"{date.today():%Y.%m.%d} 今日外刊打卡",
        "audio_edition": "original_audio_subtitled",
    }


def validate_english_world_cover_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """在渲染前拒绝缺少关键教学字段的外部 payload。"""
    if not isinstance(payload, Mapping):
        raise ValueError("payload 必须是 JSON object")
    normalized = dict(payload)
    normalized["content_type"] = "ENGLISH_WORLD_SHORT"
    for field_name in ("title", "quote_en", "quote_zh", "difficulty_tag", "audio_source", "date_str"):
        if not isinstance(normalized.get(field_name), str) or not normalized[field_name].strip():
            raise ValueError(f"payload 缺少非空字段：{field_name}")
    if not isinstance(normalized.get("highlight_words", []), list):
        raise ValueError("payload.highlight_words 必须是 list")
    if not isinstance(normalized.get("vocab_items", []), list):
        raise ValueError("payload.vocab_items 必须是 list")
    return normalized

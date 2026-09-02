# -*- coding: utf-8 -*-
"""英语世界学习卡最终音频的逐词尾部分析。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-09-01 | Codex | 新增 Whisper 结果的末词完整性与下一词泄漏分析。 |
| 1.1.0 | 2026-09-01 | Codex | 按 Whisper 时间排序输出尾部泄漏词，保证报告稳定可审计。 |
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.IGNORECASE)


def analyse_audio_tail(
    expected_words: Sequence[Mapping[str, Any]],
    observed_words: Sequence[Mapping[str, Any]],
    *,
    output_duration: float,
    tail_seconds: float = 0.18,
    final_word_end_tolerance: float = 0.75,
) -> dict[str, Any]:
    """分析 Whisper 逐词结果，拒绝末词后仍存在的可听单词。"""
    if not expected_words:
        return {"passed": False, "failure_kind": "missing_expected_words", "trailing_words": []}
    expected_final = _token(expected_words[-1].get("text"))
    expected_end = _number(expected_words[-1].get("end"))
    candidates = [
        _normalise_observation(word)
        for word in observed_words
        if _token(word.get("word")) == expected_final
    ]
    candidates = [word for word in candidates if word is not None]
    if not candidates:
        return {
            "passed": False,
            "failure_kind": "final_word_not_recognized",
            "expected_final_word": expected_words[-1].get("text"),
            "expected_speech_end": expected_end,
            "trailing_words": [],
        }
    final_word = min(candidates, key=lambda word: abs(word["end"] - expected_end))
    trailing_words = sorted([
        word for word in (_normalise_observation(item) for item in observed_words)
        if word is not None
        and word["start"] > final_word["start"] + 0.05
        and word["start"] < output_duration - 0.05
    ], key=lambda word: word["start"])
    if trailing_words:
        failure_kind = "next_word_leak"
    elif abs(final_word["end"] - expected_end) > final_word_end_tolerance:
        failure_kind = "final_word_boundary_mismatch"
    else:
        failure_kind = None
    return {
        "passed": failure_kind is None,
        "failure_kind": failure_kind,
        "expected_final_word": expected_words[-1].get("text"),
        "expected_speech_end": round(expected_end, 3),
        "observed_final_word": final_word,
        "output_duration": round(float(output_duration), 3),
        "allowed_tail_seconds": round(float(tail_seconds), 3),
        "trailing_words": trailing_words,
    }


def _normalise_observation(value: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        start = float(value["start"])
        end = float(value["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if end <= start or not _token(value.get("word")):
        return None
    return {
        "word": str(value.get("word", "")).strip(),
        "start": round(start, 3),
        "end": round(end, 3),
        "probability": value.get("probability"),
    }


def _token(value: Any) -> str:
    match = _TOKEN_RE.search(str(value or "").lower())
    return match.group(0) if match else ""


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

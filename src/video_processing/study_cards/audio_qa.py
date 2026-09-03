# -*- coding: utf-8 -*-
"""英语世界学习卡最终音频的逐词尾部分析。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-09-01 | Codex | 新增 Whisper 结果的末词完整性与下一词泄漏分析。 |
| 1.1.0 | 2026-09-01 | Codex | 按 Whisper 时间排序输出尾部泄漏词，保证报告稳定可审计。 |
| 1.2.0 | 2026-09-03 | Codex | 为无结束锚点的自动字幕末词增加一次性、无泄漏的有界时间轴校正。 |
| 1.3.0 | 2026-09-03 | Codex | 末词候选按时间邻近匹配有限单复数等价，避免片头同词遮蔽尾词。 |
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
        if _tokens_equivalent(_token(word.get("word")), expected_final)
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


def repair_final_word_boundary(
    timeline: Mapping[str, Any],
    audio_qa_report: Mapping[str, Any],
    *,
    audio_tail_seconds: float = 0.18,
    minimum_duration_seconds: float = 30.0,
) -> dict[str, Any]:
    """仅以同一末词的实际 Whisper 终点校正错误的字幕框尾部。

    YouTube json3 的末个词有时没有显式结束时间。若它被机械延长到整个字幕
    事件的结束，成片会带入长静音，且最终 Whisper 门禁会给出
    ``final_word_boundary_mismatch``。这不是放宽门禁：只有末词身份一致、没有
    下一词泄漏、修正后的成片仍严格超过最短时长时，才允许一次性缩短末词终点。
    """
    if audio_qa_report.get("state") != "FAIL" or audio_qa_report.get("failure_kind") != "final_word_boundary_mismatch":
        raise ValueError("仅允许修复 final_word_boundary_mismatch 音频 QA 失败")
    trailing_words = audio_qa_report.get("trailing_words")
    if not isinstance(trailing_words, list) or trailing_words:
        raise ValueError("检测到下一词泄漏，禁止缩短末词时间轴")
    raw_words = timeline.get("words")
    if not isinstance(raw_words, list) or not raw_words or not all(isinstance(word, Mapping) for word in raw_words):
        raise ValueError("时间线缺少可校正的逐词 words")
    expected_word = _token(raw_words[-1].get("text"))
    reported_expected_word = _token(audio_qa_report.get("expected_final_word"))
    observed = audio_qa_report.get("observed_final_word")
    if not isinstance(observed, Mapping):
        raise ValueError("音频 QA 缺少 observed_final_word")
    observed_word = _token(observed.get("word"))
    if (
        not expected_word
        or not _tokens_equivalent(expected_word, reported_expected_word)
        or not _tokens_equivalent(expected_word, observed_word)
    ):
        raise ValueError("末词身份不一致，禁止校正时间轴")
    try:
        final_start = float(raw_words[-1]["start"])
        observed_end = float(observed["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("音频 QA 或时间线末词时间不可解析") from exc
    if observed_end <= final_start:
        raise ValueError("观测末词终点未晚于原时间线起点")
    if observed_end + audio_tail_seconds <= minimum_duration_seconds:
        raise ValueError("校正后成片无法保持严格大于最短时长")

    repaired = dict(timeline)
    repaired_words = [dict(word) for word in raw_words]
    repaired_words[-1]["end"] = round(observed_end, 3)
    repaired["words"] = repaired_words
    return repaired


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


def _tokens_equivalent(left: str, right: str) -> bool:
    """对最终一个英语词容忍 Whisper 的单复数转写，不影响正文逐词校验。"""
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) < 4 or len(right) < 4:
        return False
    return left.rstrip("s") == right.rstrip("s") and (left.endswith("s") or right.endswith("s"))


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

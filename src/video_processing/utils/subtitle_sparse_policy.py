"""全片字幕的少量问题容错；只计算证据，不调用模型或改变字幕。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 逐段定位、有效修复覆盖及段数/并集时长三重阈值，保留原始严重度与绑定摘要。 |
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .subtitle_translation_provider import SubtitleTranslationCandidate
from .translation_consistency_guard import evaluate_translation_consistency
from .translation_fluency_guard import evaluate_translation_fluency
from .translation_quality_evaluator import issue_to_dict
from .translation_quality_guard import evaluate_translation_batch


POLICY_VERSION = "subtitle-sparse-quality-v1"
MAX_AFFECTED_SEGMENTS = 3
MAX_SEGMENT_RATIO = 0.05
MAX_DURATION_RATIO = 0.05
REPAIR_STRATEGIES = frozenset({
    "host_vocab_sanitization", "targeted_singleton", "isolated_source_repair",
})
TOLERATED_P0_CODES = frozenset({
    "NUMBER_MAGNITUDE_MISMATCH", "NUMBER_AMOUNT_MISSING", "FINANCE_EVENT_DIRECTION_REVERSAL",
})


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def candidate_fingerprint(segments: list[dict], translations: list[str]) -> str:
    """绑定原文、时间轴和最终正文；词注的独立处置包含在问题摘要中。"""
    if len(segments) != len(translations):
        raise ValueError("subtitle_candidate_count_mismatch")
    rows = [{"text": segment["text"], "start": segment["start"], "end": segment["end"],
             "zh_text": translated} for segment, translated in zip(segments, translations)]
    return hashlib.sha256(_canonical(rows)).hexdigest()


def report_fingerprint(report: dict) -> str:
    """报告自摘要不参与哈希；回执与检查点共用这一配方。"""
    return hashlib.sha256(_canonical({key: value for key, value in report.items()
                                      if key != "summary_sha256"})).hexdigest()


def _union_seconds(intervals: list[tuple[float, float]]) -> float:
    total, stop = 0.0, None
    for start, end in sorted(intervals):
        if stop is None or start > stop:
            total += end - start
        elif end > stop:
            total += end - stop
        stop = end if stop is None else max(stop, end)
    return total


def _source_structure_error(segments: list[dict]) -> str | None:
    if not isinstance(segments, list) or not segments:
        return "source_segments_missing"
    previous_start = -1.0
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str) or not segment["text"].strip():
            return f"source_text_invalid:{index}"
        start, end = segment.get("start"), segment.get("end")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end < start or start < previous_start):
            return f"source_timing_invalid:{index}"
        previous_start = start
    return None


def _history_segments(entry: dict) -> set[int]:
    numbers = entry.get("segment_numbers", [])
    if "segment_number" in entry:
        numbers = list(numbers) + [entry["segment_number"]] if isinstance(numbers, list) else []
    return {number for number in numbers if type(number) is int and number > 0} if isinstance(numbers, list) else set()


def _repair_covers(issue: dict, history: list[dict]) -> bool:
    for entry in history:
        if not isinstance(entry, dict) or entry.get("executed") is not True:
            continue
        strategy = entry.get("strategy")
        if strategy not in REPAIR_STRATEGIES or issue["segment_number"] not in _history_segments(entry):
            continue
        if strategy == "host_vocab_sanitization" and issue["code"] != "VOCAB_ALIGNMENT_MISMATCH":
            continue
        return True
    return False


def _locate(issue: dict, index: int, segment: dict) -> dict:
    return {**issue, "segment_number": index + 1, "source_id": index,
            "start": segment["start"], "end": segment["end"]}


def build_sparse_quality_report(
    segments: list[dict], translations: list[str], *, context_text: str = "",
    vocabs: list[dict] | None = None, repair_history: list[dict] | None = None,
) -> dict:
    """仅在全片问题稀疏且确实经过对应修复时放行，包括获批准的金额/方向问题。

    repair_history 的有效条目需有指定 strategy、executed=True 和 1-based
    segment_numbers；普通重复调用、缓存复核或只移除词注不能充当事实修复。
    全局一致性警告保持既有软警告行为，但不会伪造为一段局部事实错误。
    """
    history = json.loads(_canonical(repair_history or []))
    report = {
        "policy_version": POLICY_VERSION, "status": "invalid_structure", "candidate_sha256": "",
        "issues": [], "global_warnings": [], "removed_vocab_issues": [],
        "affected_segments": [], "affected_segment_count": 0,
        "segment_count": len(segments) if isinstance(segments, list) else 0,
        "segment_ratio": 0.0, "duration_ratio": 0.0, "coverage_seconds": 0.0,
        "affected_seconds": 0.0, "extent_known": True, "repair_complete": False,
        "repair_history": history,
        "thresholds": {"max_affected_segments": MAX_AFFECTED_SEGMENTS,
                       "max_segment_ratio": MAX_SEGMENT_RATIO, "max_duration_ratio": MAX_DURATION_RATIO},
        "tolerated_p0_codes": sorted(TOLERATED_P0_CODES), "reasons": [],
    }
    structure_error = _source_structure_error(segments)
    if not structure_error and not isinstance(translations, list):
        structure_error = "translations_not_list"
    if not structure_error:
        structure_error = SubtitleTranslationCandidate(provider="host", translations=translations).contract_error_for(len(segments))
    if not structure_error and vocabs is not None and (not isinstance(vocabs, list) or (vocabs and len(vocabs) != len(segments))):
        structure_error = "vocab_segment_count_mismatch"
    if structure_error:
        report["reasons"] = [structure_error]
        report["summary_sha256"] = report_fingerprint(report)
        return report

    texts = [segment["text"] for segment in segments]
    report["candidate_sha256"] = candidate_fingerprint(segments, translations)
    summary = evaluate_translation_batch(texts, translations, context_text=context_text,
                                         enable_numeric_checks=True, require_amount_coverage=True)
    issues = []
    for index, (segment, translated, result) in enumerate(zip(segments, translations, summary.results)):
        # 单段调用防止全片 fluency 去重把同一坏表达的重复出现误算成一处。
        local = list(result.issues) + evaluate_translation_fluency([texts[index]], [translated])
        issues.extend(_locate(issue_to_dict(issue), index, segment) for issue in local)
        vocab = (vocabs[index] if vocabs else {}) or {}
        entries = vocab.items() if isinstance(vocab, dict) else [("", "")]
        if any(not isinstance(english, str) or not english.strip()
               or english.casefold() not in texts[index].casefold()
               or not isinstance(chinese, str) or not chinese.strip() or chinese not in translated
               for english, chinese in entries):
            issues.append(_locate({
                "severity": "P2", "code": "VOCAB_ALIGNMENT_MISMATCH",
                "message": "词注未逐字对应本段原文与译文。",
                "source_signal": "vocab_source_substring_check",
                "translation_signal": "vocab_translation_substring_check",
                "suggested_fix": "仅去掉不能对齐的词注，保留正文。",
            }, index, segment))

    report["issues"] = issues
    report["global_warnings"] = [issue_to_dict(issue) for issue in
                                 evaluate_translation_consistency(texts, translations)]
    report["extent_known"] = not bool(report["global_warnings"])
    for entry in history:
        if isinstance(entry, dict) and entry.get("strategy") == "host_vocab_sanitization":
            details = entry.get("details", [])
            if isinstance(details, list):
                report["removed_vocab_issues"].extend(detail for detail in details if isinstance(detail, dict)
                                                       and detail.get("code") == "VOCAB_ALIGNMENT_MISMATCH")
    affected = sorted({issue["segment_number"] for issue in issues})
    coverage = _union_seconds([(segment["start"], segment["end"]) for segment in segments])
    affected_seconds = _union_seconds([(segments[number - 1]["start"], segments[number - 1]["end"])
                                      for number in affected])
    report.update(affected_segments=affected, affected_segment_count=len(affected),
                  segment_ratio=len(affected) / len(segments), coverage_seconds=coverage,
                  affected_seconds=affected_seconds,
                  duration_ratio=affected_seconds / coverage if coverage else (1.0 if affected else 0.0),
                  repair_complete=all(_repair_covers(issue, history) for issue in issues))
    reasons = []
    if len(affected) > MAX_AFFECTED_SEGMENTS:
        reasons.append("affected_segment_count_exceeded")
    if report["segment_ratio"] > MAX_SEGMENT_RATIO + 1e-12:
        reasons.append("affected_segment_ratio_exceeded")
    if report["duration_ratio"] > MAX_DURATION_RATIO + 1e-12:
        reasons.append("affected_duration_ratio_exceeded")
    if any(issue["severity"] == "P0" and issue["code"] not in TOLERATED_P0_CODES for issue in issues):
        reasons.append("unapproved_blocking_issue")
    if issues and not report["repair_complete"]:
        reasons.append("effective_repair_required")
    report["reasons"] = reasons
    report["status"] = ("needs_repair" if reasons else "accepted_with_warnings"
                        if issues or report["global_warnings"] or report["removed_vocab_issues"] else "clean")
    report["summary_sha256"] = report_fingerprint(report)
    return report

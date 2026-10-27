"""全片稀疏字幕容错的边界与绑定证据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 金额/方向容错、有效修复、跨批计数和重叠时间并集的独立回归。 |
"""

import copy

import pytest

from video_processing.utils.subtitle_sparse_policy import (
    build_sparse_quality_report,
    candidate_fingerprint,
    report_fingerprint,
)


def _video(count=100):
    segments = [{"text": "The outlook remains stable.", "start": index * 2, "end": index * 2 + 2}
                for index in range(count)]
    return segments, ["前景保持稳定。"] * count


def _repair(numbers, strategy="isolated_source_repair", executed=True):
    return [{"strategy": strategy, "executed": executed, "segment_numbers": numbers}]


def _wrong_amount(segments, translations, numbers):
    for number in numbers:
        segments[number - 1]["text"] = "The price is $115."
        translations[number - 1] = "价格是1150亿美元。"


def test_clean_report_binds_source_timing_and_final_text_without_mutation():
    segments, translations = _video()
    original = copy.deepcopy(segments)
    report = build_sparse_quality_report(segments, translations)
    assert report["status"] == "clean"
    assert report["issues"] == []
    assert report["candidate_sha256"] == candidate_fingerprint(segments, translations)
    assert report["summary_sha256"] == report_fingerprint(report)
    assert segments == original
    translations[0] = "新译文。"
    assert report["candidate_sha256"] != candidate_fingerprint(segments, translations)


@pytest.mark.parametrize("source,translation,code", [
    ("The price is $115.", "价格是1150亿美元。", "NUMBER_MAGNITUDE_MISMATCH"),
    ("The price is $115.", "价格继续上涨。", "NUMBER_AMOUNT_MISSING"),
    ("The fund announced its final close.", "该基金选择退出市场。", "FINANCE_EVENT_DIRECTION_REVERSAL"),
])
def test_sparse_fact_issue_is_allowed_after_targeted_repair_and_keeps_p0(source, translation, code):
    segments, translations = _video()
    segments[7]["text"], translations[7] = source, translation
    report = build_sparse_quality_report(segments, translations, repair_history=_repair([8]))
    assert report["status"] == "accepted_with_warnings"
    issue = next(issue for issue in report["issues"] if issue["code"] == code)
    assert issue["severity"] == "P0"
    assert issue["segment_number"] == 8
    assert issue["source_id"] == 7
    assert issue["start"] == 14
    assert report["affected_segment_count"] == 1
    assert report["segment_ratio"] == report["duration_ratio"] == 0.01


@pytest.mark.parametrize("history", [None, _repair([1], "retry"), _repair([1], executed=False),
                                     _repair([2]), _repair([1], "host_vocab_sanitization")])
def test_absent_identical_or_unrelated_repair_does_not_unlock_fact_tolerance(history):
    segments, translations = _video()
    _wrong_amount(segments, translations, [1])
    report = build_sparse_quality_report(segments, translations, repair_history=history)
    assert report["status"] == "needs_repair"
    assert "effective_repair_required" in report["reasons"]


def test_three_distinct_segments_at_both_five_percent_boundaries_are_allowed():
    segments, translations = _video(60)
    _wrong_amount(segments, translations, [1, 30, 60])
    report = build_sparse_quality_report(segments, translations, repair_history=_repair([1, 30, 60]))
    assert report["status"] == "accepted_with_warnings"
    assert report["affected_segment_count"] == 3
    assert report["segment_ratio"] == report["duration_ratio"] == 0.05


def test_separate_batches_accumulate_to_whole_video_count_limit():
    segments, translations = _video(200)
    _wrong_amount(segments, translations, [1, 51, 101, 151])
    report = build_sparse_quality_report(segments, translations, repair_history=_repair([1, 51, 101, 151]))
    assert report["status"] == "needs_repair"
    assert report["segment_ratio"] == 0.02
    assert "affected_segment_count_exceeded" in report["reasons"]


def test_less_than_three_segments_still_must_meet_segment_percentage():
    segments, translations = _video(19)
    _wrong_amount(segments, translations, [1])
    report = build_sparse_quality_report(segments, translations, repair_history=_repair([1]))
    assert report["status"] == "needs_repair"
    assert "affected_segment_ratio_exceeded" in report["reasons"]


def test_one_long_bad_segment_cannot_hide_in_a_large_segment_count():
    segments, translations = _video()
    for segment in segments[1:]:
        segment["start"] += 48
        segment["end"] += 48
    segments[0]["end"] = 50
    _wrong_amount(segments, translations, [1])
    report = build_sparse_quality_report(segments, translations, repair_history=_repair([1]))
    assert report["status"] == "needs_repair"
    assert report["segment_ratio"] == 0.01
    assert report["affected_seconds"] == 50
    assert report["coverage_seconds"] == 248
    assert "affected_duration_ratio_exceeded" in report["reasons"]


def test_overlapping_subtitle_intervals_use_union_for_both_numerator_and_denominator():
    segments, translations = _video()
    segments[0]["end"] = 8
    segments[1]["start"], segments[1]["end"] = 0, 8
    _wrong_amount(segments, translations, [1, 2])
    report = build_sparse_quality_report(segments, translations, repair_history=_repair([1, 2]))
    assert report["coverage_seconds"] == 200
    assert report["affected_seconds"] == 8
    assert report["duration_ratio"] == 0.04
    assert report["status"] == "accepted_with_warnings"


def test_repeated_fluency_rule_is_located_for_every_affected_segment():
    segments, translations = _video()
    for index in range(40):
        segments[index]["text"] = "Keep this on your radar."
        translations[index] = "把这个放在你的雷达上。"
    report = build_sparse_quality_report(segments, translations,
                                         repair_history=_repair(list(range(1, 41))))
    assert report["affected_segment_count"] == 40
    assert sum(issue["code"] == "FLUENCY_LITERAL_CALQUE_RADAR" for issue in report["issues"]) == 40
    assert report["status"] == "needs_repair"


def test_split_amount_uses_actual_next_source_without_broad_context_pollution():
    segments, translations = _video()
    segments[0]["text"], translations[0] = "It costs $600", "这需要6000亿美元"
    segments[1]["text"], translations[1] = "billion in total.", "的总成本。"
    segments[5]["text"], translations[5] = "The price is $115 bucks.", "价格是115美元。"
    report = build_sparse_quality_report(segments, translations, context_text="Its fund is $115B.")
    assert not any(issue["segment_number"] in {1, 6} for issue in report["issues"])
    assert report["affected_segments"] == []


def test_global_warning_never_masquerades_as_one_affected_segment():
    segments, translations = _video()
    segments[0]["text"], translations[0] = "The cost is $100.", "成本100美元。"
    segments[1]["text"], translations[1] = "The next cost is $10000.", "下项成本10000美元。"
    report = build_sparse_quality_report(segments, translations)
    assert report["global_warnings"]
    assert report["extent_known"] is False
    assert report["affected_segment_count"] == 0
    assert report["status"] == "accepted_with_warnings"


@pytest.mark.parametrize("translation", ["", "   ", "承接上文",
                                         "Error 500 (Server Error)!!1 That's an error. The server encountered an error and could not complete your request. Please try again in 30 seconds. That's all we know."])
def test_empty_placeholder_and_upstream_error_are_structural_even_when_sparse(translation):
    segments, translations = _video()
    translations[0] = translation
    report = build_sparse_quality_report(segments, translations, repair_history=_repair([1]))
    assert report["status"] == "invalid_structure"


def test_missing_translation_and_invalid_source_timing_stay_structural():
    segments, translations = _video()
    assert build_sparse_quality_report(segments, translations[:-1])["status"] == "invalid_structure"
    segments[0]["end"] = float("nan")
    assert build_sparse_quality_report(segments, translations)["status"] == "invalid_structure"


@pytest.mark.parametrize("segments", [None, [], "not segments"])
def test_missing_or_wrong_typed_source_is_a_reported_structural_rejection(segments):
    report = build_sparse_quality_report(segments, [])
    assert report["status"] == "invalid_structure"
    assert report["reasons"] == ["source_segments_missing"]
    assert report["summary_sha256"] == report_fingerprint(report)


def test_vocab_only_sanitization_is_distinct_from_fact_repair():
    segments, translations = _video()
    vocabs = [{} for _ in segments]
    vocabs[0] = {"nonexistent": "不存在"}
    report = build_sparse_quality_report(segments, translations, vocabs=vocabs,
                                         repair_history=_repair([1], "host_vocab_sanitization"))
    assert report["status"] == "accepted_with_warnings"
    assert report["issues"][0]["code"] == "VOCAB_ALIGNMENT_MISMATCH"
    _wrong_amount(segments, translations, [1])
    report = build_sparse_quality_report(segments, translations, vocabs=vocabs,
                                         repair_history=_repair([1], "host_vocab_sanitization"))
    assert report["status"] == "needs_repair"


def test_removed_vocab_evidence_survives_sanitized_final_candidate():
    segments, translations = _video()
    history = _repair([1], "host_vocab_sanitization")
    history[0]["details"] = [{"code": "VOCAB_ALIGNMENT_MISMATCH", "segment_number": 1}]
    report = build_sparse_quality_report(segments, translations, repair_history=history)
    assert report["status"] == "accepted_with_warnings"
    assert report["removed_vocab_issues"] == history[0]["details"]
    assert report["issues"] == []


def test_warning_summary_hash_changes_with_repair_evidence_and_preserves_source_identity():
    segments, translations = _video()
    _wrong_amount(segments, translations, [1])
    before = build_sparse_quality_report(segments, translations)
    after = build_sparse_quality_report(segments, translations, repair_history=_repair([1]))
    assert before["candidate_sha256"] == after["candidate_sha256"]
    assert before["summary_sha256"] != after["summary_sha256"]
    tampered = {**after, "status": "clean"}
    assert tampered["summary_sha256"] != report_fingerprint(tampered)

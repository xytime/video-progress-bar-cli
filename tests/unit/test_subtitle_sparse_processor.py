"""字幕 processor 与稀疏容错、选中候选和坏例证据的接线回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 原时间轴保持、有效定点修复、候选仲裁与可重验坏例绑定。 |
"""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from video_processing.processors import caption_processor as module
from video_processing.utils import subtitle_bad_cases
from video_processing.utils.subtitle_bad_cases import iter_bad_cases
from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure, fingerprint, validate_quality_warning
from video_processing.utils.subtitle_quality_recovery import prepare_subtitle_candidate, sparse_quality_decision
from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate


def _video(count=100):
    segments = [{"text": "The outlook remains stable.", "start": index * 2, "end": index * 2 + 2}
                for index in range(count)]
    return segments, ["前景保持稳定。"] * count


def _candidate(translations, *, history=None, supports_vocab=True, vocabs=None, provider="gemini"):
    return SubtitleTranslationCandidate(provider=provider, translations=translations,
        vocabs=vocabs or [{} for _ in translations], supports_vocab=supports_vocab,
        repair_history=history or [])


def _repair(numbers):
    return [{"strategy": "isolated_source_repair", "executed": True, "segment_numbers": numbers}]


def _processor(tmp_path):
    path = tmp_path / "video.mp4"
    path.touch()
    return module.AutoCaptionProcessor(path, output_path=tmp_path / "captioned.mp4")


def _settings(tmp_path, providers):
    return SimpleNamespace(project_root=tmp_path, subtitle_translation_provider_order_list=providers,
                           enable_deepseek_vocab_fallback=False, enable_translation_numeric_guard=True,
                           enable_translation_quality_fail_open=False)


def test_targeted_callback_receives_global_numbers_and_preserves_source_and_other_text():
    segments, translations = _video()
    segments[53]["text"], translations[53] = "The price is $115.", "价格是1150亿美元。"
    before = copy.deepcopy(segments)
    original_translations = list(translations)
    calls = []

    def repair(candidate, targets):
        calls.append(targets)
        assert targets == [54]
        assert candidate.repair_history[-1]["strategy"] == "quality_observation"
        corrected = list(candidate.translations)
        corrected[53] = "价格是115美元。"
        return replace(candidate, translations=corrected,
                       repair_history=[*candidate.repair_history, *_repair(targets)])

    candidate = prepare_subtitle_candidate(_candidate(translations), segments,
                                           context_text="", repair=repair)
    assert calls == [[54]]
    assert segments == before
    assert candidate.translations[53] == "价格是115美元。"
    assert candidate.translations[:53] == original_translations[:53]
    assert candidate.translations[54:] == original_translations[54:]
    assert candidate.quality_report["status"] == "clean"


def test_remaining_sparse_fact_error_after_actual_repair_is_a_warning_with_original_severity():
    segments, translations = _video()
    segments[4]["text"], translations[4] = "The price is $115.", "价格是1150亿美元。"
    calls = []

    def repair(candidate, targets):
        calls.append(targets)
        return replace(candidate, repair_history=[*candidate.repair_history, *_repair(targets)])

    candidate = prepare_subtitle_candidate(_candidate(translations), segments, context_text="", repair=repair)
    decision = sparse_quality_decision(candidate, final_provider=True)
    assert calls == [[5]]
    assert decision.accepted
    assert decision.status == "accepted_with_warnings"
    assert any(issue.severity == "P0" for issue in decision.warning_issues)
    assert decision.blocking_issues == []


def test_large_repeated_fluency_failure_is_not_hidden_by_old_global_dedupe():
    segments, translations = _video()
    for index in range(40):
        segments[index]["text"] = "Keep this on your radar."
        translations[index] = "把这个放在你的雷达上。"
    calls = []

    def repair(candidate, targets):
        calls.append(targets)
        return replace(candidate, repair_history=[*candidate.repair_history, *_repair(targets)])

    candidate = prepare_subtitle_candidate(_candidate(translations), segments, context_text="", repair=repair)
    assert calls == [list(range(1, 11))]
    assert candidate.quality_report["affected_segment_count"] == 40
    assert candidate.quality_report["status"] == "needs_repair"
    assert not sparse_quality_decision(candidate, final_provider=True).accepted


def test_incomplete_repair_result_never_replaces_full_candidate():
    segments, translations = _video()
    segments[0]["text"], translations[0] = "The price is $115.", "价格是1150亿美元。"

    def incomplete(candidate, targets):
        return replace(candidate, translations=candidate.translations[:-1],
                       repair_history=[*candidate.repair_history, *_repair(targets)])

    candidate = prepare_subtitle_candidate(_candidate(translations), segments, context_text="", repair=incomplete)
    assert len(candidate.translations) == 100
    assert candidate.translations == translations
    assert candidate.quality_report["status"] == "needs_repair"


def test_repair_cannot_change_non_targeted_segments():
    segments, translations = _video()
    segments[0]["text"], translations[0] = "The price is $115.", "价格是1150亿美元。"

    def unrelated_changes(candidate, targets):
        changed = list(candidate.translations)
        changed[0], changed[50] = "价格是115美元。", "未经授权的重新翻译。"
        return replace(candidate, translations=changed,
                       repair_history=[*candidate.repair_history, *_repair(targets)])

    candidate = prepare_subtitle_candidate(_candidate(translations), segments, context_text="", repair=unrelated_changes)
    assert candidate.translations == translations
    assert candidate.quality_report["status"] == "needs_repair"


def test_plain_provider_keeps_post_translation_vocab_alignment(tmp_path, monkeypatch):
    processor = _processor(tmp_path)
    segments, translations = _video()
    candidate = prepare_subtitle_candidate(_candidate(translations, supports_vocab=False, provider="Google"),
                                           segments, context_text="")
    calls = []
    monkeypatch.setattr(processor, "_align_vocab_after_plain_translation", lambda *args: calls.append(args))
    processor._apply_selected_translation_candidate(segments, candidate,
                                                     [segment["text"] for segment in segments], "context")
    assert candidate.supports_vocab is False
    assert len(calls) == 1


def test_clean_later_provider_is_selected_without_retaining_other_candidates_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "settings", _settings(tmp_path, ["gemini", "codex"]))
    processor = _processor(tmp_path)
    segments, wrong = _video()
    segments[0]["text"], wrong[0] = "The price is $115.", "价格是1150亿美元。"
    clean = list(wrong)
    clean[0] = "价格是115美元。"
    original_source = copy.deepcopy(segments)

    def build(provider, texts, context):
        return _candidate(wrong, history=_repair([1])) if provider == "gemini" else _candidate(clean, provider="codex")

    monkeypatch.setattr(processor, "_build_translation_candidate", build)
    result = processor._translate_segments(segments)
    selected = processor._selected_subtitle_candidate
    assert selected.provider == "codex"
    assert selected.quality_report["status"] == "clean"
    assert result[0]["zh_text"] == "价格是115美元。"
    assert [{key: segment[key] for key in ("text", "start", "end")} for segment in result] == original_source
    assert [event["selected"] for event in processor._translation_quality_audit] == [False, True]
    warning = processor._build_subtitle_quality_evidence(selected, original_source, "a" * 64, "b" * 64)
    assert warning is None
    assert list(iter_bad_cases(tmp_path / "output" / "subtitle_bad_cases")) == []


def test_selected_warning_saves_bound_case_and_revalidates_against_applied_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "settings", _settings(tmp_path, ["gemini"]))
    processor = _processor(tmp_path)
    source, translations = _video()
    source[0]["text"], translations[0] = "The price is $115.", "价格是1150亿美元。"
    original = copy.deepcopy(source)
    candidate = prepare_subtitle_candidate(_candidate(translations, history=_repair([1])), source, context_text="")
    processor._apply_selected_translation_candidate(source, candidate,
                                                     [segment["text"] for segment in source], "")
    warning = processor._build_subtitle_quality_evidence(candidate, original, "a" * 64, "b" * 64)
    assert warning["status"] == "accepted_with_warnings"
    stored = list(iter_bad_cases(tmp_path / "output" / "subtitle_bad_cases"))
    assert len(stored) == 1
    assert stored[0]["review"] == {"status": "unreviewed", "ground_truth": False}
    assert stored[0]["payload"]["source_segments"] == original
    assert stored[0]["payload"]["translations"] == translations
    validated = validate_quality_warning(warning, segments=source, input_sha256="a" * 64,
                                         asr_sha256=fingerprint(original), contract_sha256="b" * 64)
    assert validated == warning
    # 相同候选恢复不生成新的坏例，仍可复核。
    processor._build_subtitle_quality_evidence(candidate, original, "a" * 64, "b" * 64)
    assert len(list(iter_bad_cases(tmp_path / "output" / "subtitle_bad_cases"))) == 1


def test_repaired_clean_case_is_saved_without_warning_release(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "settings", _settings(tmp_path, ["gemini"]))
    processor = _processor(tmp_path)
    source, translations = _video()
    candidate = prepare_subtitle_candidate(_candidate(translations, history=_repair([1])), source, context_text="")
    warning = processor._build_subtitle_quality_evidence(candidate, source, "a" * 64, "b" * 64)
    assert warning is None
    stored = list(iter_bad_cases(tmp_path / "output" / "subtitle_bad_cases"))
    assert len(stored) == 1
    assert stored[0]["payload"]["report"]["status"] == "clean"


def test_bad_case_persistence_failure_prevents_warning_release(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "settings", _settings(tmp_path, ["gemini"]))
    processor = _processor(tmp_path)
    source, translations = _video()
    source[0]["text"], translations[0] = "The price is $115.", "价格是1150亿美元。"
    candidate = prepare_subtitle_candidate(_candidate(translations, history=_repair([1])), source, context_text="")

    def unavailable(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(subtitle_bad_cases, "save_bad_case", unavailable)
    with pytest.raises(SubtitleTranslationFailure, match="subtitle_bad_case_persistence"):
        processor._build_subtitle_quality_evidence(candidate, source, "a" * 64, "b" * 64)

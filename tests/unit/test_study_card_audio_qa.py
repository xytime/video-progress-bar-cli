"""英语世界学习卡音频收尾校正的纯逻辑测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-03 | Codex | 覆盖仅在末词身份一致、无下一词泄漏时的有界时间轴校正。 |
"""

from __future__ import annotations

import pytest

from video_processing.study_cards.audio_qa import analyse_audio_tail, repair_final_word_boundary


def _timeline() -> dict:
    return {
        "words": [
            {"text": "rabita", "start": 32.101, "end": 32.521},
            {"text": "Islands", "start": 32.521, "end": 34.731},
        ],
    }


def _mismatch_report(*, trailing_words: list[dict] | None = None) -> dict:
    return {
        "state": "FAIL",
        "failure_kind": "final_word_boundary_mismatch",
        "expected_final_word": "Islands",
        "observed_final_word": {"word": "Islands.", "start": 32.360, "end": 32.760},
        "trailing_words": trailing_words or [],
    }


def test_repair_final_word_boundary_uses_observed_end_without_mutating_input():
    timeline = _timeline()

    repaired = repair_final_word_boundary(timeline, _mismatch_report())

    assert timeline["words"][-1]["end"] == 34.731
    assert repaired["words"][-1] == {"text": "Islands", "start": 32.521, "end": 32.76}


def test_repair_final_word_boundary_rejects_any_next_word_leak():
    with pytest.raises(ValueError, match="下一词泄漏"):
        repair_final_word_boundary(
            _timeline(),
            _mismatch_report(trailing_words=[{"word": "since", "start": 33.1, "end": 33.4}]),
        )


def test_repair_final_word_boundary_rejects_wrong_observed_terminal_word():
    report = _mismatch_report()
    report["observed_final_word"]["word"] = "since"

    with pytest.raises(ValueError, match="末词身份不一致"):
        repair_final_word_boundary(_timeline(), report)


def test_audio_tail_uses_terminal_singular_whisper_word_over_early_exact_duplicate():
    report = analyse_audio_tail(
        [{"text": "Islands", "start": 32.521, "end": 32.760}],
        [
            {"word": "Islands", "start": 3.88, "end": 4.38},
            {"word": "Island.", "start": 32.36, "end": 32.72},
        ],
        output_duration=32.94,
    )

    assert report["passed"] is True
    assert report["observed_final_word"]["word"] == "Island."

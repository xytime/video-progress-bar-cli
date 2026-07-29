"""配音再制时长闭环单元测试。"""

import pytest

from video_processing.dubbing.service import DubbingService
from video_processing.dubbing.subtitle_pages import build_semantic_pages, wrap_page_lines
from video_processing.dubbing.timing import decide_timing, next_synthesis_speed


def test_speed_recalculation_is_clamped_to_natural_range():
    assert next_synthesis_speed(1.08, 8_000, 4_000, minimum=0.96, maximum=1.28) == 1.28
    assert next_synthesis_speed(1.08, 1_000, 8_000, minimum=0.96, maximum=1.28) == 0.96


@pytest.mark.parametrize(
    ("actual", "target", "strategy", "rewrite"),
    [
        (10_200, 10_000, "micro_tempo", False),
        (9_000, 10_000, "natural_pause", False),
        (11_000, 10_000, "bounded_tempo", False),
        (11_300, 10_000, "needs_rewrite", True),
    ],
)
def test_decision_blocks_extreme_tempo(actual, target, strategy, rewrite):
    decision = decide_timing(actual, target)
    assert decision.strategy == strategy
    assert decision.requires_rewrite is rewrite


def test_invalid_timing_is_rejected():
    with pytest.raises(ValueError):
        decide_timing(0, 1_000)


def test_actual_subtitles_follow_minimax_timestamps_after_tempo():
    entries = DubbingService._actual_subtitles(
        [{"text": "普通话", "time_begin": 100, "time_end": 1_100}], 2_000, 1.1, "回退", 900,
    )
    assert entries == [{"start_ms": 2091, "end_ms": 3000, "text": "普通话"}]


def test_semantic_pages_keep_full_sentences_and_only_split_long_ones_at_pauses():
    pages = build_semantic_pages(
        [{"start_ms": 0, "end_ms": 9_000, "text": "第一句完整。第二句很长，不过可以在这里停顿，然后继续表达。"}],
        max_chars=12,
    )

    assert [page["text"] for page in pages] == ["第一句完整。", "第二句很长，", "不过可以在这里停顿，", "然后继续表达。"]
    assert pages[0]["start_ms"] == 0
    assert pages[-1]["end_ms"] == 9_000


def test_semantic_pages_do_not_force_break_a_long_sentence_without_pause():
    pages = build_semantic_pages(
        [{"start_ms": 0, "end_ms": 4_000, "text": "这是没有自然停顿但必须保持完整的一句话。"}],
        max_chars=8,
    )

    assert pages == [{"start_ms": 0, "end_ms": 4_000, "text": "这是没有自然停顿但必须保持完整的一句话。"}]


def test_visual_line_wrap_preserves_one_semantic_page_and_never_exceeds_safe_width():
    text = "这是一条完整的字幕句子，即使较长也只在当前页面内折成多行展示。"

    lines = wrap_page_lines(text, max_line_chars=12).splitlines()

    assert "".join(lines) == text
    assert max(len(line) for line in lines) <= 13
    assert lines[0].endswith("，")


def test_visual_line_wrap_does_not_split_percentage_or_english_ticker():
    lines = wrap_page_lines("该股单日上涨百分之四百六十六，CXMT成为焦点。", max_line_chars=12).splitlines()

    assert all("百分之四百六十六" not in line or line == "百分之四百六十六，" for line in lines)
    assert any("CXMT" in line for line in lines)

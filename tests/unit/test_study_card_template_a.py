"""模板 A 的布局与输入契约测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：覆盖逐词时间线、单词映射和 30 秒约束。 |
| 1.1.0 | 2026-08-02 | Codex | 覆盖长样片测试豁免和语音锚定的正文滚动计划。 |
| 1.1.1 | 2026-08-02 | Codex | 覆盖红线使用的滚动偏移预计算，避免与正文滚动脱节。 |
"""

from pathlib import Path

import pytest

from video_processing.study_cards import StudyCardContent, StudyCardRenderer, VocabularyItem
from video_processing.study_cards.renderer import ScrollStep
from video_processing.study_cards.template_a import RecordUnderlineTemplate, _highlighted_token_indices, _learning_label


def _payload():
    return {
        "headline_zh": "测试新闻标题",
        "headline_en": "A short test headline",
        "english_text": "A fin whale was spotted near Victoria today.",
        "translation_zh": "今天在维多利亚附近发现了一头长须鲸。",
        "words": [
            {"text": "A", "start": 0.0, "end": 0.2},
            {"text": "fin", "start": 0.2, "end": 0.5},
            {"text": "whale", "start": 0.5, "end": 0.9},
            {"text": "was", "start": 0.9, "end": 1.1},
            {"text": "spotted", "start": 1.1, "end": 1.5},
            {"text": "near", "start": 1.5, "end": 1.8},
            {"text": "Victoria", "start": 1.8, "end": 2.3},
            {"text": "today.", "start": 2.3, "end": 2.7},
        ],
        "vocabulary": [{"word": "species", "meaning_zh": "物种", "phonetic": "/ˈspiːʃiːz/"}],
    }


def test_template_maps_each_timeline_word_to_a_page_coordinate(tmp_path: Path):
    content = StudyCardContent.from_mapping(_payload())
    template = RecordUnderlineTemplate()
    assets = template.render_static(content, tmp_path)

    mapped = template.map_word_boxes(content.words, assets.word_boxes)

    assert len(mapped) == len(content.words)
    assert all(box.width > 0 and box.y > 0 for _, box in mapped)


def test_rejects_time_axis_that_does_not_match_page_text(tmp_path: Path):
    payload = _payload()
    payload["words"][2]["text"] = "dolphin"
    content = StudyCardContent.from_mapping(payload)
    template = RecordUnderlineTemplate()
    assets = template.render_static(content, tmp_path)

    with pytest.raises(ValueError, match="不一致"):
        template.map_word_boxes(content.words, assets.word_boxes)


def test_rejects_paragraphs_that_rewrite_the_spoken_english():
    payload = _payload()
    payload["paragraphs"] = [{
        "english_text": "A dolphin was spotted near Victoria today.",
        "translation_zh": "今天在维多利亚附近发现了一只海豚。",
    }]

    with pytest.raises(ValueError, match="paragraphs"):
        StudyCardContent.from_mapping(payload)


def test_renderer_rejects_more_than_thirty_seconds_before_touching_source(tmp_path: Path):
    content = StudyCardContent.from_mapping(_payload())

    with pytest.raises(ValueError, match="不超过 30 秒"):
        StudyCardRenderer().render(tmp_path / "missing.mp4", content, tmp_path / "out.mp4", duration=30.1)


def test_renderer_stops_shortly_after_the_final_included_word():
    content = StudyCardContent.from_mapping(_payload())

    duration = StudyCardRenderer._resolve_render_duration(content, requested_duration=5.0)

    assert duration == pytest.approx(2.88)


def test_long_duration_is_only_accepted_with_the_explicit_test_flag(tmp_path: Path):
    content = StudyCardContent.from_mapping(_payload())

    with pytest.raises(FileNotFoundError):
        StudyCardRenderer().render(
            tmp_path / "missing.mp4", content, tmp_path / "out.mp4", duration=30.1, allow_long_test=True,
        )


def test_scroll_plan_moves_body_before_a_word_leaves_the_reading_area(tmp_path: Path):
    template = RecordUnderlineTemplate()
    content = StudyCardContent.from_mapping(_payload())
    boxes = tuple(
        template.map_word_boxes(content.words, template.render_static(content, tmp_path).word_boxes)
    )
    shifted = [(word, type(box)(box.text, box.x, box.y + 1000, box.width)) for word, box in boxes]

    steps = StudyCardRenderer._build_scroll_steps(shifted)

    assert steps
    assert steps[0].end <= shifted[0][0].end
    assert steps[0].to_offset > 0


def test_scroll_offset_for_underlines_matches_piecewise_scroll_plan():
    steps = [
        ScrollStep(start=10.0, end=10.4, from_offset=0, to_offset=400),
        ScrollStep(start=20.0, end=20.4, from_offset=400, to_offset=900),
    ]

    assert StudyCardRenderer._scroll_offset_at(5.0, steps) == 0
    assert StudyCardRenderer._scroll_offset_at(10.2, steps) == 200
    assert StudyCardRenderer._scroll_offset_at(15.0, steps) == 400
    assert StudyCardRenderer._scroll_offset_at(20.2, steps) == 650
    assert StudyCardRenderer._scroll_offset_at(25.0, steps) == 900


def test_underline_alpha_expression_grows_with_the_current_word_progress():
    expression = StudyCardRenderer._underline_alpha_expression(120, 1.2, 1.8)

    assert expression == "if(between(T\\,1.200\\,1.800)*lte(X\\,120*(T-1.200)/0.600)\\,255\\,0)"


def test_word_card_learning_label_prefers_offline_friendly_tag_and_exam_level():
    item = VocabularyItem("grocery", "食品杂货店", level="CET-4", friendly_tag="进阶词")

    assert _learning_label(item) == "进阶词 · CET-4"


def test_phrase_vocabulary_marks_every_word_but_shows_the_note_once():
    highlights = _highlighted_token_indices(
        ["ripe", "conditions", "for", "a", "heat", "wave"],
        (
            VocabularyItem("ripe conditions", "有利条件"),
            VocabularyItem("heat wave", "热浪"),
        ),
    )

    assert highlights[0] == ("有利条件", True)
    assert highlights[1] == ("有利条件", False)
    assert highlights[4] == ("热浪", True)
    assert highlights[5] == ("热浪", False)


def test_template_accepts_a_real_mini_program_qr(tmp_path: Path):
    from PIL import Image

    qr_path = tmp_path / "mini-program-qr.png"
    Image.new("RGB", (300, 300), "white").save(qr_path)
    assets = RecordUnderlineTemplate(qr_path).render_static(StudyCardContent.from_mapping(_payload()), tmp_path)

    assert assets.base_image.is_file()

"""模板 A 的布局与输入契约测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：覆盖逐词时间线、单词映射和 30 秒约束。 |
| 1.1.0 | 2026-08-02 | Codex | 覆盖长样片测试豁免和语音锚定的正文滚动计划。 |
| 1.1.1 | 2026-08-02 | Codex | 覆盖红线使用的滚动偏移预计算，避免与正文滚动脱节。 |
| 1.2.0 | 2026-08-03 | Codex | 覆盖滚动静音暂停、右栏词卡正文锚点与影子跟读 Banner 资产。 |
| 1.3.0 | 2026-08-03 | Codex | 覆盖连续原声滚动、右栏最高难度五词和词卡释义清洗。 |
"""

from pathlib import Path

import pytest

from video_processing.study_cards import StudyCardContent, StudyCardRenderer, VocabularyItem
from video_processing.study_cards.renderer import ScrollStep
from video_processing.study_cards.template_a import (
    RecordUnderlineTemplate,
    _highlighted_token_indices,
    _learning_label,
    _meaning_line,
    _right_vocabulary_items,
    _vocabulary_anchor_y,
)


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


def test_scroll_plan_uses_paragraph_boundaries_without_audio_pauses(tmp_path: Path):
    template = RecordUnderlineTemplate()
    payload = _payload()
    payload["paragraphs"] = [
        {"english_text": "A fin whale was spotted", "translation_zh": "发现长须鲸。"},
        {"english_text": "near Victoria today.", "translation_zh": "地点在维多利亚附近。"},
    ]
    content = StudyCardContent.from_mapping(payload)
    boxes = tuple(
        template.map_word_boxes(content.words, template.render_static(content, tmp_path).word_boxes)
    )
    shifted = [(word, type(box)(box.text, box.x, box.y + 1000, box.width)) for word, box in boxes]

    steps = StudyCardRenderer()._build_scroll_steps(content, shifted)

    assert steps
    assert steps[0].start == pytest.approx(shifted[5][0].start - 0.04)
    assert steps[0].end - steps[0].start == pytest.approx(0.62)
    assert steps[0].to_offset > 0


def test_scroll_plan_is_limited_to_three_natural_boundary_moves():
    boxes = [
        (
            type("Word", (), {"text": f"w{index}", "start": float(index), "end": float(index) + 0.2})(),
            type("Box", (), {"text": f"w{index}", "x": 54, "y": 800 + index * 420, "width": 80})(),
        )
        for index in range(7)
    ]
    payload = {
        "headline_zh": "测试新闻标题",
        "headline_en": "A short test headline",
        "english_text": " ".join(f"w{index}" for index in range(7)),
        "translation_zh": "测试。",
        "words": [
            {"text": f"w{index}", "start": float(index), "end": float(index) + 0.2}
            for index in range(7)
        ],
        "paragraphs": [
            {"english_text": f"w{index}", "translation_zh": "测试。"}
            for index in range(7)
        ],
        "vocabulary": [{"word": "w3", "meaning_zh": "测试", "level": "PET"}],
    }

    steps = StudyCardRenderer()._build_scroll_steps(StudyCardContent.from_mapping(payload), boxes)

    assert len(steps) <= 3


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


def test_underline_progress_width_tracks_the_current_word_progress():
    assert StudyCardRenderer._underline_progress_width(120, 1.2, 1.8, 1.1) == 0
    assert StudyCardRenderer._underline_progress_width(120, 1.2, 1.8, 1.5) == 60
    assert StudyCardRenderer._underline_progress_width(120, 1.2, 1.8, 1.9) == 120


def test_word_card_learning_label_prefers_offline_friendly_tag_and_exam_level():
    item = VocabularyItem("grocery", "食品杂货店", level="CET-4", friendly_tag="进阶词")

    assert _learning_label(item) == "进阶词 · CET-4"


def test_right_vocabulary_uses_the_highest_difficulty_five_left_notes():
    items = (
        VocabularyItem("ket", "基础", level="KET"),
        VocabularyItem("pet", "进阶", level="PET"),
        VocabularyItem("gaokao", "高考", level="高考"),
        VocabularyItem("cet4", "四级", level="CET-4"),
        VocabularyItem("fce", "FCE", level="FCE"),
        VocabularyItem("cet6", "六级", level="CET-6"),
        VocabularyItem("cae", "高级", level="CAE"),
    )

    assert [item.word for item in _right_vocabulary_items(items)] == ["cae", "cet6", "fce", "cet4", "gaokao"]


def test_word_card_meaning_removes_duplicate_part_of_speech_and_keeps_more_definition():
    item = VocabularyItem(
        "affect",
        "vt. vt. 影响; 感动; 侵袭; 使感染",
        part_of_speech="vt.",
        level="PET",
    )

    assert _meaning_line(item) == "vt. 影响；感动；侵袭；使感染"


def test_vocabulary_card_anchor_uses_the_first_matching_body_word(tmp_path: Path):
    template = RecordUnderlineTemplate()
    content = StudyCardContent.from_mapping(_payload())
    assets = template.render_static(content, tmp_path)
    spotted_box = next(box for box in assets.word_boxes if box.text == "spotted")

    assert _vocabulary_anchor_y(VocabularyItem("spotted", "发现"), assets.word_boxes) == spotted_box.y - 53


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


def test_template_builds_feature_banner_from_reference_image(tmp_path: Path):
    from PIL import Image

    banner_path = tmp_path / "feature.png"
    Image.new("RGB", (1127, 1396), "#10263C").save(banner_path)
    assets = RecordUnderlineTemplate(banner_path).render_static(StudyCardContent.from_mapping(_payload()), tmp_path)

    assert assets.base_image.is_file()
    assert assets.feature_image.is_file()

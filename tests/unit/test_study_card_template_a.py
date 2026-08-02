"""模板 A 的布局与输入契约测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：覆盖逐词时间线、单词映射和 30 秒约束。 |
"""

from pathlib import Path

import pytest

from video_processing.study_cards import StudyCardContent, StudyCardRenderer
from video_processing.study_cards.template_a import RecordUnderlineTemplate


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

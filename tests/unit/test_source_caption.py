"""原文字幕与翻译失败的行为边界，不加载模型。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 验证关闭翻译/同语种、翻译缺失、换行、时间与输入不变性 |
"""

import pytest

from video_processing.utils.source_caption import build_source_caption_event


@pytest.mark.parametrize("target", [None, "", "en"])
def test_source_caption_only_when_translation_not_requested(target):
    segment = {"start": .12, "end": 2.34, "text": "Hello world from the test."}
    before = dict(segment)
    event = build_source_caption_event(segment, "en", target, 22, 31, 12)
    assert event.plaintext.replace("\n", " ") == segment["text"]
    assert "\\N" in event.text and "\n" not in event.text
    assert event.text.startswith("{\\fs22}")
    assert (event.start, event.end, event.marginv) == (120, 2340, 31)
    assert segment == before


def test_requested_translation_missing_is_not_english_fallback():
    segment = {"start": 0, "end": 1, "text": "Source text", "zh_text": ""}
    assert build_source_caption_event(segment, "en", "zh-CN", 22, 31, 40) is None


def test_empty_source_does_not_create_blank_event():
    assert build_source_caption_event({"text": "  "}, "en", None, 22, 31, 40) is None


@pytest.mark.parametrize("target,translation,expected", [
    (None, "", "Source text"), ("en", "", "Source text"),
    ("zh-CN", "中文译文", "中文译文"), ("zh-CN", "", ""),
])
def test_standard_processor_preserves_translation_boundary(tmp_path, monkeypatch, target, translation, expected):
    import pysubs2
    from video_processing.processors.caption_processor import AutoCaptionProcessor

    source = tmp_path / "synthetic.mp4"
    source.write_bytes(b"synthetic input; resolution supplied by this unit fixture")
    processor = AutoCaptionProcessor(source, target_lang=target, src_lang="en")
    monkeypatch.setattr(processor, "_get_video_resolution", lambda: (640, 480))
    output = processor._generate_ass_file([{"start": 0, "end": 1, "text": "Source text", "zh_text": translation}])
    subtitles = pysubs2.load(str(output))
    assert " ".join(s.plaintext for s in subtitles) == expected

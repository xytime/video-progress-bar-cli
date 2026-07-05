# -*- coding: utf-8 -*-
"""Unit tests for caption translation quality guard integration.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：验证字幕处理器接入事实保真守门器后 P0 阻断、P1 放行 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖 P0 质量失败时 Gemini→Aliyun→Google 自动降级 |
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from video_processing.core.base import VideoProcessingError
from video_processing.processors.caption_processor import AutoCaptionProcessor


def _processor() -> AutoCaptionProcessor:
    return AutoCaptionProcessor(
        input_path=Path("dummy.mp4"),
        output_path=Path("dummy_output.mp4"),
        src_lang="en",
        target_lang="zh-CN",
    )


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
def test_caption_translation_guard_blocks_p0_event_reversal(_mock_validate_input):
    processor = _processor()
    source_texts = [
        "MGX announced the final close of Fund I at $49 billion, exceeding its initial target."
    ]
    segments = [
        {"text": source_texts[0], "zh_text": "490亿主权基金撤退，主权投资基金选择退出市场。"}
    ]

    with pytest.raises(VideoProcessingError, match="Translation quality guard blocked"):
        processor._guard_translation_quality(source_texts, segments, provider="UnitTest")


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
def test_caption_translation_guard_warns_but_allows_p1_ambiguous_close(_mock_validate_input):
    processor = _processor()
    source_texts = ["MGX announced that it has closed its Fund I at $49 billion."]
    segments = [{"text": source_texts[0], "zh_text": "MGX宣布第一期基金已以490亿美元关闭。"}]

    processor._guard_translation_quality(source_texts, segments, provider="UnitTest")


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_aliyun")
@patch("video_processing.processors.caption_processor.extract_vocab_batch")
def test_translate_segments_falls_back_when_gemini_quality_blocked(
    mock_extract_vocab_batch,
    mock_aliyun,
    mock_google,
    _mock_validate_input,
):
    processor = _processor()
    source = "MGX announced the final close of Fund I at $49 billion."
    segments = [{"text": source}]
    mock_extract_vocab_batch.side_effect = [
        [{"translation": "490亿主权基金撤退。", "vocab": {}}],
        None,
    ]
    mock_aliyun.return_value = ["MGX一期基金最终募集规模达490亿美元。"]

    result = processor._translate_segments(segments)

    assert result[0]["zh_text"] == "MGX一期基金最终募集规模达490亿美元。"
    mock_aliyun.assert_called_once()
    mock_google.assert_not_called()


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_aliyun")
@patch("video_processing.processors.caption_processor.extract_vocab_batch", return_value=None)
def test_translate_segments_falls_back_when_aliyun_quality_blocked(
    _mock_extract_vocab_batch,
    mock_aliyun,
    mock_google,
    _mock_validate_input,
):
    processor = _processor()
    source = "MGX announced the final close of Fund I at $49 billion."
    segments = [{"text": source}]
    mock_aliyun.return_value = ["490亿主权基金撤退。"]
    mock_google.return_value = ["MGX一期基金最终募集规模达490亿美元。"]

    result = processor._translate_segments(segments)

    assert result[0]["zh_text"] == "MGX一期基金最终募集规模达490亿美元。"
    mock_aliyun.assert_called_once()
    mock_google.assert_called_once()


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_aliyun", return_value=None)
@patch("video_processing.processors.caption_processor.extract_vocab_batch", return_value=None)
def test_translate_segments_blocks_when_final_provider_quality_blocked(
    _mock_extract_vocab_batch,
    _mock_aliyun,
    mock_google,
    _mock_validate_input,
):
    processor = _processor()
    source = "MGX announced the final close of Fund I at $49 billion."
    segments = [{"text": source}]
    mock_google.return_value = ["490亿主权基金撤退。"]

    with pytest.raises(VideoProcessingError, match="Translation quality guard blocked Google output"):
        processor._translate_segments(segments)

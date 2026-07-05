# -*- coding: utf-8 -*-
"""Unit tests for caption translation quality guard integration.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：验证字幕处理器接入事实保真守门器后 P0 阻断、P1 放行 |
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

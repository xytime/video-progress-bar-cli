# -*- coding: utf-8 -*-
"""Unit tests for caption translation quality guard integration.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：验证字幕处理器接入事实保真守门器后 P0 阻断、P1 放行 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖 P0 质量失败时 Gemini→Aliyun→Google 自动降级 |
| 1.2.0   | 2026-07-05 | Codex  | 覆盖 *.translation_quality.json 审计报告落盘与 fallback/fail 动作 |
| 1.3.0   | 2026-07-05 | Codex  | 覆盖 settings 配置字幕翻译供应商顺序 |
| 1.4.0   | 2026-07-05 | Codex  | 覆盖 DeepSeek provider 顺序接入 |
| 1.5.0   | 2026-07-05 | Codex  | 覆盖质量审计报告写入全片上下文摘要 |
| 1.6.0   | 2026-07-06 | Codex  | 覆盖非最终 provider 出现 warning 时继续尝试更干净候选 |
| 1.7.0   | 2026-07-06 | Codex  | 固定默认 provider order，避免本地 .env 启用 DeepSeek 污染既有 fallback 测试 |
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from video_processing.core.base import VideoProcessingError
from video_processing.processors.caption_processor import AutoCaptionProcessor


class _SettingsOrder:
    def __init__(self, providers):
        self.subtitle_translation_provider_order_list = providers


def _processor() -> AutoCaptionProcessor:
    return AutoCaptionProcessor(
        input_path=Path("dummy.mp4"),
        output_path=Path("dummy_output.mp4"),
        src_lang="en",
        target_lang="zh-CN",
    )


def _processor_for(path: Path) -> AutoCaptionProcessor:
    return AutoCaptionProcessor(
        input_path=path,
        output_path=path.with_name("dummy_output.mp4"),
        src_lang="en",
        target_lang="zh-CN",
    )


@pytest.fixture(autouse=True)
def _default_provider_order(monkeypatch):
    """隔离本地 .env 中的 provider 顺序，保持单测只验证显式声明的 provider。"""
    import video_processing.processors.caption_processor as caption_processor

    monkeypatch.setattr(
        caption_processor,
        "settings",
        _SettingsOrder(["gemini", "aliyun", "google"]),
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
@patch("video_processing.processors.caption_processor.extract_vocab_batch")
def test_translate_segments_writes_quality_report_for_fallback(
    mock_extract_vocab_batch,
    mock_aliyun,
    _mock_google,
    _mock_validate_input,
    tmp_path,
):
    input_path = tmp_path / "video.mp4"
    input_path.touch()
    processor = _processor_for(input_path)
    source = "MGX announced the final close of Fund I at $49 billion."
    mock_extract_vocab_batch.side_effect = [
        [{"translation": "490亿主权基金撤退。", "vocab": {}}],
        None,
    ]
    mock_aliyun.return_value = ["MGX一期基金最终募集规模达490亿美元。"]

    processor._translate_segments([{"text": source}])

    report = json.loads(input_path.with_suffix(".translation_quality.json").read_text(encoding="utf-8"))
    assert [event["provider"] for event in report["events"]] == ["Gemini", "Aliyun"]
    assert report["events"][0]["status"] == "blocked"
    assert report["events"][0]["action"] == "fallback"
    assert report["events"][0]["blocking_issues"][0]["code"] == "FINANCE_EVENT_DIRECTION_REVERSAL"
    assert report["events"][0]["quality_context"]["facts"]
    assert report["events"][1]["status"] == "passed"
    assert report["events"][1]["action"] == "accept"


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._align_vocab_after_plain_translation")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_aliyun")
@patch("video_processing.processors.caption_processor.extract_vocab_batch")
def test_translate_segments_tries_next_provider_after_warning(
    mock_extract_vocab_batch,
    mock_aliyun,
    mock_google,
    _mock_align_vocab,
    _mock_validate_input,
    tmp_path,
):
    input_path = tmp_path / "video.mp4"
    input_path.touch()
    processor = _processor_for(input_path)
    source = "MGX announced that it has closed its Fund I at $49 billion."
    mock_extract_vocab_batch.return_value = [
        {"translation": "MGX宣布第一期基金已以490亿美元关闭。", "vocab": {}}
    ]
    mock_aliyun.return_value = ["MGX宣布一期基金最终募集规模达490亿美元。"]

    result = processor._translate_segments([{"text": source}])

    assert result[0]["zh_text"] == "MGX宣布一期基金最终募集规模达490亿美元。"
    mock_aliyun.assert_called_once()
    mock_google.assert_not_called()

    report = json.loads(input_path.with_suffix(".translation_quality.json").read_text(encoding="utf-8"))
    assert [event["provider"] for event in report["events"]] == ["Gemini", "Aliyun"]
    assert [event["selected"] for event in report["events"]] == [False, True]
    assert report["events"][0]["warning_issues"][0]["code"] == "FINANCE_TERM_AMBIGUOUS_CLOSE"


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor.translate_batch_deepseek", return_value=None)
@patch("video_processing.processors.caption_processor.extract_vocab_batch")
def test_translate_segments_uses_warning_candidate_when_later_providers_unavailable(
    mock_extract_vocab_batch,
    _mock_deepseek,
    _mock_validate_input,
    tmp_path,
):
    input_path = tmp_path / "video.mp4"
    input_path.touch()
    processor = _processor_for(input_path)
    source = "MGX announced that it has closed its Fund I at $49 billion."
    mock_extract_vocab_batch.return_value = [
        {"translation": "MGX宣布第一期基金已以490亿美元关闭。", "vocab": {}}
    ]

    with patch(
        "video_processing.processors.caption_processor.settings",
        _SettingsOrder(["gemini", "deepseek"]),
    ):
        result = processor._translate_segments([{"text": source}])

    assert result[0]["zh_text"] == "MGX宣布第一期基金已以490亿美元关闭。"
    report = json.loads(input_path.with_suffix(".translation_quality.json").read_text(encoding="utf-8"))
    assert [event["provider"] for event in report["events"]] == ["Gemini"]
    assert report["events"][0]["selected"] is True
    assert report["events"][0]["warning_issues"][0]["code"] == "FINANCE_TERM_AMBIGUOUS_CLOSE"


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._align_vocab_after_plain_translation")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_aliyun")
@patch("video_processing.processors.caption_processor.extract_vocab_batch")
def test_translate_segments_respects_provider_order_without_gemini(
    mock_extract_vocab_batch,
    mock_aliyun,
    mock_google,
    _mock_align_vocab,
    _mock_validate_input,
):
    processor = _processor()
    source = "MGX announced the final close of Fund I at $49 billion."
    mock_aliyun.return_value = ["MGX一期基金最终募集规模达490亿美元。"]

    with patch(
        "video_processing.processors.caption_processor.settings",
        _SettingsOrder(["aliyun", "google"]),
    ):
        result = processor._translate_segments([{"text": source}])

    assert result[0]["zh_text"] == "MGX一期基金最终募集规模达490亿美元。"
    mock_extract_vocab_batch.assert_not_called()
    mock_aliyun.assert_called_once()
    mock_google.assert_not_called()


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._align_vocab_after_plain_translation")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_deepseek")
def test_translate_segments_can_use_deepseek_provider(
    mock_deepseek,
    mock_google,
    _mock_align_vocab,
    _mock_validate_input,
):
    processor = _processor()
    source = "MGX announced the final close of Fund I at $49 billion."
    mock_deepseek.return_value = ["MGX一期基金最终募集规模达490亿美元。"]

    with patch(
        "video_processing.processors.caption_processor.settings",
        _SettingsOrder(["deepseek", "google"]),
    ):
        result = processor._translate_segments([{"text": source}])

    assert result[0]["zh_text"] == "MGX一期基金最终募集规模达490亿美元。"
    mock_deepseek.assert_called_once()
    mock_google.assert_not_called()


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._align_vocab_after_plain_translation")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_deepseek", return_value=None)
def test_translate_segments_falls_back_when_deepseek_unavailable(
    _mock_deepseek,
    mock_google,
    _mock_align_vocab,
    _mock_validate_input,
):
    processor = _processor()
    source = "MGX announced the final close of Fund I at $49 billion."
    mock_google.return_value = ["MGX一期基金最终募集规模达490亿美元。"]

    with patch(
        "video_processing.processors.caption_processor.settings",
        _SettingsOrder(["deepseek", "google"]),
    ):
        result = processor._translate_segments([{"text": source}])

    assert result[0]["zh_text"] == "MGX一期基金最终募集规模达490亿美元。"
    mock_google.assert_called_once()


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
    tmp_path,
):
    input_path = tmp_path / "video.mp4"
    input_path.touch()
    processor = _processor_for(input_path)
    source = "MGX announced the final close of Fund I at $49 billion."
    segments = [{"text": source}]
    mock_google.return_value = ["490亿主权基金撤退。"]

    with pytest.raises(VideoProcessingError, match="Translation quality guard blocked Google output"):
        processor._translate_segments(segments)


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_aliyun", return_value=None)
@patch("video_processing.processors.caption_processor.extract_vocab_batch", return_value=None)
def test_translate_segments_writes_quality_report_for_final_failure(
    _mock_extract_vocab_batch,
    _mock_aliyun,
    mock_google,
    _mock_validate_input,
    tmp_path,
):
    input_path = tmp_path / "video.mp4"
    input_path.touch()
    processor = _processor_for(input_path)
    source = "MGX announced the final close of Fund I at $49 billion."
    mock_google.return_value = ["490亿主权基金撤退。"]

    with pytest.raises(VideoProcessingError):
        processor._translate_segments([{"text": source}])

    report = json.loads(input_path.with_suffix(".translation_quality.json").read_text(encoding="utf-8"))
    assert len(report["events"]) == 1
    assert report["events"][0]["provider"] == "Google"
    assert report["events"][0]["status"] == "blocked"
    assert report["events"][0]["action"] == "fail"

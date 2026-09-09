# -*- coding: utf-8 -*-
"""字幕翻译质量守门器回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-09 | Codex | 硬合同在 fail-open 下仍回退或失败，审计记录占位符段号 |
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


def _processor(path: Path = Path("dummy.mp4")) -> AutoCaptionProcessor:
    return AutoCaptionProcessor(
        input_path=path,
        output_path=path.with_name("dummy_output.mp4"),
        src_lang="en",
        target_lang="zh-CN",
    )


@pytest.fixture(autouse=True)
def _default_provider_order(monkeypatch):
    import video_processing.processors.caption_processor as module
    monkeypatch.setattr(module, "settings", _SettingsOrder(["gemini", "google"]))


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
def test_guard_blocks_finance_event_reversal(_mock_validate_input):
    processor = _processor()
    with pytest.raises(VideoProcessingError, match="Translation quality guard blocked"):
        processor._guard_translation_quality(
            ["MGX announced the final close of Fund I at $49 billion."],
            [{"text": "source", "zh_text": "490亿主权基金撤退，主权投资基金选择退出市场。"}],
            provider="UnitTest",
        )


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.extract_vocab_batch")
def test_gemini_quality_block_falls_back_to_google(mock_gemini, mock_google, _mock_validate_input):
    mock_gemini.return_value = [{"translation": "490亿主权基金撤退。", "vocab": {}}]
    mock_google.return_value = ["MGX一期基金最终募集规模达490亿美元。"]
    result = _processor()._translate_segments([{"text": "MGX announced the final close of Fund I at $49 billion."}])
    assert result[0]["zh_text"] == "MGX一期基金最终募集规模达490亿美元。"
    mock_google.assert_called_once()


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._align_vocab_after_plain_translation")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_deepseek")
def test_deepseek_is_used_before_google(mock_deepseek, mock_google, _mock_align, _mock_validate_input):
    mock_deepseek.return_value = ["MGX一期基金最终募集规模达490亿美元。"]
    with patch("video_processing.processors.caption_processor.settings", _SettingsOrder(["deepseek", "google"])):
        result = _processor()._translate_segments([{"text": "MGX announced the final close of Fund I at $49 billion."}])
    assert result[0]["zh_text"] == "MGX一期基金最终募集规模达490亿美元。"
    mock_google.assert_not_called()


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._align_vocab_after_plain_translation")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.translate_batch_deepseek", return_value=None)
def test_google_remains_terminal_fallback(_mock_deepseek, mock_google, _mock_align, _mock_validate_input):
    mock_google.return_value = ["MGX一期基金最终募集规模达490亿美元。"]
    with patch("video_processing.processors.caption_processor.settings", _SettingsOrder(["deepseek", "google"])):
        result = _processor()._translate_segments([{"text": "MGX announced the final close of Fund I at $49 billion."}])
    assert result[0]["zh_text"] == "MGX一期基金最终募集规模达490亿美元。"
    mock_google.assert_called_once()


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.extract_vocab_batch", return_value=None)
def test_final_google_quality_failure_blocks_publish(_mock_gemini, mock_google, _mock_validate_input):
    mock_google.return_value = ["490亿主权基金撤退。"]
    with pytest.raises(VideoProcessingError, match="Translation quality guard blocked Google output"):
        _processor()._translate_segments([{"text": "MGX announced the final close of Fund I at $49 billion."}])


@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
@patch("video_processing.processors.caption_processor._google_batch_fallback")
@patch("video_processing.processors.caption_processor.extract_vocab_batch")
def test_report_records_gemini_then_google(mock_gemini, mock_google, _mock_validate_input, tmp_path):
    path = tmp_path / "video.mp4"
    path.touch()
    mock_gemini.return_value = [{"translation": "490亿主权基金撤退。", "vocab": {}}]
    mock_google.return_value = ["MGX一期基金最终募集规模达490亿美元。"]
    _processor(path)._translate_segments([{"text": "MGX announced the final close of Fund I at $49 billion."}])
    report = json.loads(path.with_suffix(".translation_quality.json").read_text(encoding="utf-8"))
    assert [event["provider"] for event in report["events"]] == ["Gemini", "Google"]
    assert report["events"][0]["action"] == "fallback"
    assert report["events"][1]["action"] == "accept"


@pytest.mark.parametrize("fallback_valid", [True, False])
@patch("video_processing.processors.caption_processor.AutoCaptionProcessor._validate_input")
def test_placeholder_hard_gate_survives_fail_open(_validate, tmp_path, monkeypatch, fallback_valid):
    import video_processing.processors.caption_processor as module
    from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate

    module.settings.enable_translation_quality_fail_open = True
    processor = _processor(tmp_path / "video.mp4")
    def candidate(provider, texts, context):
        text = "但通过这段视频，你会理解这一问题。" if provider == "google" and fallback_valid else "（承接上文）"
        return SubtitleTranslationCandidate(provider, [text], supports_vocab=True)
    monkeypatch.setattr(processor, "_build_translation_candidate", candidate)
    segments = [{"text": "But in this video, you will understand why.", "start": 7.2, "end": 11.6}]
    if fallback_valid:
        result = processor._translate_segments(segments)
        assert result[0]["zh_text"].startswith("但通过")
        assert (result[0]["start"], result[0]["end"]) == (7.2, 11.6)
    else:
        with pytest.raises(VideoProcessingError, match="All subtitle translation providers failed"):
            processor._translate_segments(segments)
        assert "zh_text" not in segments[0]
    report = json.loads((tmp_path / "video.translation_quality.json").read_text())
    event = report["events"][0]
    assert event["selected"] is False
    assert event["blocking_issues"][0]["code"] == "TRANSLATION_PLACEHOLDER"
    assert "index=0" in event["blocking_issues"][0]["message"]

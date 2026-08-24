"""agy 字幕首选 provider 的边界测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 验证 Schema 调用、ID 对齐及不合格 vocabulary 的本地过滤 |
"""

from unittest.mock import patch

from video_processing.processors.caption_processor import AutoCaptionProcessor


def _processor() -> AutoCaptionProcessor:
    processor = AutoCaptionProcessor.__new__(AutoCaptionProcessor)
    processor._last_provider_error = ""
    return processor


@patch("video_processing.processors.caption_processor.run_agy_structured")
def test_agy_subtitle_candidate_keeps_alignment_and_filters_non_substring_vocab(mock_agy):
    mock_agy.return_value = {
        "items": [
            {"id": 1, "translation": "市场波动正在加剧。", "vocab": {"volatility": "波动", "bad": "不存在"}},
            {"id": 0, "translation": "基金最终募集规模达490亿美元。", "vocab": {"final close": "最终募集", "fund": "基金"}},
        ]
    }

    candidate = _processor()._build_agy_candidate(
        ["The fund held its final close at $49 billion.", "Market volatility is intensifying."],
        "Global context: finance",
    )

    assert candidate is not None
    assert candidate.translations == ["基金最终募集规模达490亿美元。", "市场波动正在加剧。"]
    assert candidate.vocabs == [{"final close": "最终募集", "fund": "基金"}, {"volatility": "波动"}]
    assert candidate.supports_vocab is True
    assert mock_agy.call_args.kwargs["model"]


@patch("video_processing.processors.caption_processor.run_agy_structured")
def test_agy_subtitle_candidate_rejects_incomplete_ids(mock_agy):
    mock_agy.return_value = {"items": [{"id": 0, "translation": "第一句。", "vocab": {}}]}
    processor = _processor()

    candidate = processor._build_agy_candidate(["First.", "Second."], "")

    assert candidate is None
    assert "misaligned" in processor._last_provider_error

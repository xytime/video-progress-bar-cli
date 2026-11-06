"""队列异常根因修复回归：烧录误拦、翻译预算、瞬态服务、抽样边界、题材误伤。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-06 | Grok Bot | 覆盖 caption overlay / budget / sampling / unrest / delivery 过期清理。 |
"""
import math
from types import SimpleNamespace

import pytest

from video_processing.processors import burned_caption_repair as repair
from video_processing.processors.caption_overlay_roles import non_dialogue_rows
from video_processing.utils.subtitle_provider_window import (
    adaptive_translation_budget_seconds, require_single_video_budget, ABSOLUTE_TRANSLATION_BUDGET_SECONDS)
from video_processing.utils.caption_sampling_contract import windows
from video_processing.core.social_unrest import DEFAULT_RULES, classify
from video_processing import social_unrest_review as review
from video_processing.processors.vocabulary_outro_layout import fit


def test_stable_news_lower_third_is_overlay_not_uncertain():
    fps = 30
    frames = []
    for i in range(120):
        rows = [dict(text='ONE-ON-ONE WITH GUEST', confidence=1,
                     box=[.05, .70, .90, .73])]
        if 40 <= i <= 80:
            rows.append(dict(text='hello from the studio today', confidence=1,
                             box=[.15, .55, .85, .60]))
        frames.append(rows)
    segments = [dict(start=1.3, end=2.8, text='hello from the studio today')]
    ignored = non_dialogue_rows(frames, segments, fps, repair._caption_text_matches)
    assert any(frames[i][n]['text'].startswith('ONE-ON-ONE') for i, n in ignored)
    selected, center = repair._classify(frames, segments, fps, preserve_large_text=True)
    assert center is not None
    assert any(selected)


def test_low_dialogue_ratio_title_card_does_not_hard_stop():
    fps = 30
    frames = [[dict(text='ELECTION NIGHT', confidence=1, box=[.2, .55, .8, .62])]
              for _ in range(90)]
    segments = [dict(start=0, end=3, text='thanks for joining us tonight')]
    selected, center = repair._classify(frames, segments, fps, preserve_large_text=True)
    assert center is None and not any(selected)


def test_uncertain_error_message_includes_frame_and_ocr():
    from video_processing.utils.subtitle_failure_receipt import SubtitleReviewRequired
    with pytest.raises(SubtitleReviewRequired, match=r'第 7 帧\(t=0\.23s\).*OCR=') as raised:
        raise SubtitleReviewRequired(
            "第 7 帧(t=0.23s) 原字幕位置或文字不确定，OCR='mystery line' box=[0.2, 0.55, 0.8, 0.6] "
            "conf=1.00 dialogue_ratio=93.1%；停止出片",
            code='caption_frame_uncertain')
    assert 'caption_frame_uncertain' in str(raised.value)


def test_adaptive_budget_allows_mid_length_videos():
    config = SimpleNamespace(
        subtitle_provider_budget_allocation_enabled=True,
        subtitle_translation_total_timeout_seconds=600,
        subtitle_translation_quality_reserve_seconds=120,
        codex_subtitle_batch_size=50,
        codex_text_request_timeout_seconds=120,
    )
    for segments in (208, 213, 227, 231, 237, 257, 400, 687):
        budget = require_single_video_budget(segments, config)
        assert budget <= ABSOLUTE_TRANSLATION_BUDGET_SECONDS
        assert budget >= adaptive_translation_budget_seconds(segments, config)
        available = budget - 120
        required = math.ceil(segments / 50) * 120
        assert required <= available


def test_adaptive_budget_still_blocks_extreme_lengths():
    config = SimpleNamespace(
        subtitle_provider_budget_allocation_enabled=True,
        subtitle_translation_total_timeout_seconds=600,
        subtitle_translation_quality_reserve_seconds=120,
        codex_subtitle_batch_size=50,
        codex_text_request_timeout_seconds=120,
    )
    with pytest.raises(ValueError, match='translation_budget_preflight|超出单片预算'):
        require_single_video_budget(5000, config)


def test_sampling_clamps_small_asr_overrun():
    fps = 30
    count = 300  # 10.0s
    segments = [dict(start=0.0, end=9.5, text='hello'),
                dict(start=9.5, end=11.005, text='tail overrun')]  # +1.005s
    planned = windows(segments, fps, count)
    assert planned and planned[-1]['end'] <= count / fps + 1e-9


def test_sampling_still_rejects_huge_overrun():
    with pytest.raises(ValueError, match='SAMPLE_TIMELINE_INVALID'):
        windows([dict(start=0, end=20, text='too far')], 30, 300)


def test_vocabulary_fit_truncates_long_english():
    face, lines = fit('relationship between the body and its surrounding space ' * 3,
                      'en', 792, 60, 36, allow_truncate=True)
    assert lines and lines[0].endswith('…')
    assert face.getlength(lines[0]) <= 792


def test_wall_street_strike_price_not_social_unrest():
    for text in (
        'Wall Street debates the AI boom and strike price of options',
        'Options traders watch the strike price near Wall Street open',
        'The model shows a striking similarity to prior AI results',
    ):
        assert classify(review.text_documents(title=text), DEFAULT_RULES) is None, text


def test_uprising_requires_external_context():
    # uprising alone (also listed as term) must not self-satisfy via context.
    assert classify(review.text_documents(title='An uprising began quietly'), DEFAULT_RULES) is None
    hit = classify(review.text_documents(title='An uprising against the regime'), DEFAULT_RULES)
    assert hit and hit['family'] == 'mobilization'

"""长片翻译批次进度与分窗续翻。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-06 | Grok Bot | 覆盖进度落盘、剩余段预检与分窗选择。 |
"""
from types import SimpleNamespace

import pytest

from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.utils.subtitle_failure_receipt import SubtitleReviewRequired
from video_processing.utils.subtitle_provider_window import require_single_video_budget
from video_processing.utils.translation_batch_progress import (
    apply_progress_to_segments, cue_fingerprint, load_progress, max_segments_for_budget,
    progress_path, save_progress, select_work_indices,
)
from config.settings import settings


def _config():
    return SimpleNamespace(
        subtitle_provider_budget_allocation_enabled=True,
        subtitle_translation_total_timeout_seconds=600,
        subtitle_translation_quality_reserve_seconds=120,
        codex_subtitle_batch_size=50,
        codex_text_request_timeout_seconds=120,
    )


def test_progress_roundtrip_and_remaining(tmp_path):
    segments = [dict(start=i, end=i + 0.5, text=f'word {i}') for i in range(5)]
    fp = cue_fingerprint(segments)
    path = progress_path(tmp_path, 'vid123', fp)
    translations = ['译0', None, '译2', None, None]
    save_progress(path, youtube_id='vid123', source_fp=fp, segments=segments,
                  translations=translations, done_indices=[0, 2])
    loaded = load_progress(path, fp, 5)
    assert loaded and loaded['done_count'] == 2
    remaining = apply_progress_to_segments(segments, loaded['translations'])
    assert remaining == [1, 3, 4]
    assert segments[0]['zh_text'] == '译0'


def test_max_window_fits_under_absolute_cap():
    n = max_segments_for_budget(_config())
    require_single_video_budget(n, _config())
    with pytest.raises((ValueError, SubtitleReviewRequired)):
        require_single_video_budget(max(n + 80, 614), _config())


def test_select_work_indices_windowed_vs_full():
    remaining = list(range(20))
    work, partial = select_work_indices(remaining, 7, True)
    assert partial and work == list(range(7))
    work, partial = select_work_indices(remaining, 7, False)
    assert not partial and work == remaining
    work, partial = select_work_indices(list(range(5)), 7, True)
    assert not partial and work == list(range(5))


def test_remaining_progress_passes_preflight_when_short(tmp_path, monkeypatch):
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'media')
    processor = AutoCaptionProcessor(video)
    monkeypatch.setattr(type(processor), '_start_translation_audit',
                        lambda self: pytest.fail('should reuse progress'))
    monkeypatch.setattr(settings, 'subtitle_translation_windowed_resume_enabled', False, raising=False)
    segments = [dict(start=i, end=i + 0.4, text=f'Text {i}') for i in range(10)]
    fp = cue_fingerprint(segments)
    path = progress_path(settings.default_output_dir, 'video', fp)
    translations = [f'译{i}' for i in range(10)]
    save_progress(path, youtube_id='video', source_fp=fp, segments=segments,
                  translations=translations, done_indices=list(range(10)))
    out = processor._translate_segments(segments)
    assert all(seg.get('zh_text') for seg in out)

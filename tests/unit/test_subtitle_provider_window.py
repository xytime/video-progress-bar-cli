"""故障供应商不能耗尽兜底及完整质量核验的整片时间预算。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 验证份额转让、异常恢复、原时间轴与完整质量阻断。 |
| 1.1.0 | 2026-11-01 | Grok Bot | CLI 优先顺序下 Codex 居中不独占剩余期限。 |
"""
from types import SimpleNamespace

import pytest

from video_processing.utils.subtitle_provider_window import candidate_deadline, translation_provider_window


def deadline(providers, index, now=0, end=600):
    return candidate_deadline(end, providers, index, now=now, total_seconds=600,
                              quality_seconds=120, fallback_seconds=300)


def test_slow_providers_leave_fallback_and_quality_time():
    providers = ['gemini', 'deepseek', 'google', 'codex']
    now, windows = 0, []
    for index in range(len(providers)):
        next_at = deadline(providers, index, now)
        windows.append(next_at - now)
        now = next_at
    assert windows == [60, 60, 60, 300]
    assert 600 - now == 120


def test_fast_auth_or_network_failures_donate_unused_time():
    providers = ['gemini', 'deepseek', 'google', 'codex']
    assert deadline(providers, 1, now=5) == 92.5
    assert deadline(providers, 3, now=15) == 480


def test_unavailable_fallback_does_not_reserve_idle_time():
    assert deadline(['gemini', 'google'], 0) == 240
    assert deadline(['gemini', 'google'], 1, now=240) == 480


def test_cli_first_order_shares_time_fairly_when_codex_is_not_last():
    providers = ['agy', 'codex', 'grok', 'deepseek', 'gemini', 'google']
    assert deadline(providers, 0) == 80
    assert deadline(providers, 1, now=80) == 160
    # agy 快速失败时未用份额顺延给 Codex，但 Codex 不能吞掉后续供应商的时间。
    assert deadline(providers, 1, now=10) == 10 + 470 / 5


def test_no_new_candidate_request_during_quality_reserve():
    assert deadline(['codex'], 0, now=490) == 490
    assert deadline(['codex'], 0, now=610) == 600


def test_reserves_scale_to_shorter_total_budget():
    assert candidate_deadline(30, ['gemini','codex'], 0, now=0, total_seconds=30,
                              quality_seconds=120, fallback_seconds=300) == 9


@pytest.mark.parametrize('raises', [False, True])
def test_window_restores_overall_deadline_even_on_failure(monkeypatch, raises):
    import video_processing.utils.subtitle_provider_window as module
    monkeypatch.setattr(module.time, 'monotonic', lambda: 100)
    processor = SimpleNamespace(_translation_deadline=700)
    config = SimpleNamespace(subtitle_provider_budget_allocation_enabled=True,
        subtitle_translation_total_timeout_seconds=600, subtitle_translation_quality_reserve_seconds=120,
        subtitle_translation_fallback_reserve_seconds=300)
    try:
        with translation_provider_window(processor, ['gemini', 'deepseek', 'google', 'codex'], 0, config) as available:
            assert available and processor._translation_deadline == 160
            if raises:
                raise ConnectionError('network interruption')
    except ConnectionError:
        assert raises
    assert processor._translation_deadline == 700


def test_flag_rollback_preserves_original_deadline():
    processor = SimpleNamespace(_translation_deadline=700)
    with translation_provider_window(processor, ['gemini'], 0, SimpleNamespace()) as available:
        assert available and processor._translation_deadline == 700


@pytest.mark.parametrize('valid', [True, False])
def test_real_orchestrator_reserves_fallback_but_keeps_quality_gate(tmp_path, monkeypatch, valid):
    import video_processing.processors.caption_processor as module
    from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate
    from video_processing.core.base import VideoProcessingError
    config = SimpleNamespace(subtitle_translation_provider_order_list=['gemini','deepseek','google','codex'],
        subtitle_provider_budget_allocation_enabled=True, subtitle_translation_total_timeout_seconds=600,
        subtitle_translation_quality_reserve_seconds=120, subtitle_translation_fallback_reserve_seconds=300)
    monkeypatch.setattr(module, 'settings', config)
    now, calls = [100.], []
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    source = tmp_path / 'source.mp4'
    source.touch()
    processor = module.AutoCaptionProcessor(source, tmp_path / 'unused.mp4')
    def build(provider, texts, context):
        calls.append((provider, processor._translation_deadline-now[0]))
        now[0] = processor._translation_deadline
        if provider != 'codex':
            processor._last_provider_error = 'network interrupted'
            return None
        translation = 'MGX一期基金最终募集规模达490亿美元。' if valid else '490亿主权基金撤退。'
        return SubtitleTranslationCandidate('codex', [translation], supports_vocab=True)
    monkeypatch.setattr(processor, '_build_translation_candidate', build)
    segments = [{'text':'MGX announced the final close of Fund I at $49 billion.', 'start':0., 'end':4.}]
    if valid:
        translated = processor._translate_segments(segments)
        assert translated[0]['zh_text'] == 'MGX一期基金最终募集规模达490亿美元。'
        assert translated[0]['start'] == 0. and translated[0]['end'] == 4.
        assert processor._translation_quality_audit[-1]['selected']
    else:
        with pytest.raises(VideoProcessingError):
            processor._translate_segments(segments)
        assert 'zh_text' not in segments[0]
        assert not any(e['selected'] for e in processor._translation_quality_audit)
    assert calls == [('gemini',60),('deepseek',60),('google',60),('codex',300)]
    assert processor._translation_deadline == 700 and now[0] == 580

"""真实宿主路径的有界成本校准；只替换模型执行与时钟，不放宽质量门。"""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from video_processing.utils import codex_text_provider as text_provider
from video_processing.utils.subtitle_provider_inventory import codex_inventory
from tests.unit.test_subtitle_translation_throughput import (
    _processor_fixture, _write_codex_cache, _codex_state_path,
)


def _measured(path, seconds):
    saved = json.loads(path.read_text())
    saved['execution'] = dict(identity=path.stem, duration_ms=seconds * 1000,
        payload_sha256=hashlib.sha256(json.dumps(saved['payload'], ensure_ascii=False,
            sort_keys=True, allow_nan=False).encode()).hexdigest())
    path.write_text(json.dumps(saved))


def test_cost_requires_valid_bound_payload_and_same_or_larger_batch(tmp_path):
    texts, context, binding = ['Hello world.'] * 11, 'Whole source.', {'input': 'source'}
    options = dict(model='gpt-5.6-luna', effort='medium', batch_size=5,
        seconds_per_batch=120, binding=binding)
    tail = _write_codex_cache(tmp_path, texts, context, binding, offset=10)
    _measured(tail, 1)
    assert codex_inventory(tmp_path, texts, context, **options)['estimated_seconds'] == 240
    first = _write_codex_cache(tmp_path, texts, context, binding)
    _measured(first, 12)
    inventory = codex_inventory(tmp_path, texts, context, **options)
    assert inventory['estimated_seconds'] == 18
    assert inventory['observed_batches'] == 2
    assert not inventory['calibration_available']
    saved = json.loads(first.read_text())
    saved['payload']['items'][0]['translation'] = '你好世界！'
    first.write_text(json.dumps(saved))
    assert codex_inventory(tmp_path, texts, context, **options)['estimated_seconds'] == 120
    assert codex_inventory(tmp_path, texts, context, **dict(options, effort='low'))['cached_batches'] == 0


def _real_host_processor(tmp_path, monkeypatch, seconds=8, interrupt_second=False):
    import video_processing.processors.caption_processor as processor_module
    now, executed = [100.0], []
    monkeypatch.setattr(text_provider.time, 'monotonic', lambda: now[0])
    def execute(args, prompt, directory, timeout):
        data = json.loads(prompt.split('源字幕 JSON: ', 1)[1])
        if interrupt_second and len(executed) == 1:
            raise KeyboardInterrupt('controlled test interruption')
        executed.append([row['id'] for row in data])
        now[0] += seconds
        payload = dict(items=[dict(id=row['id'], translation='你好世界。', vocab=[]) for row in data])
        Path(args[args.index('--output-last-message') + 1]).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(args, 0, json.dumps(dict(type='turn.completed', usage={})), '')
    monkeypatch.setattr(text_provider, '_execute', execute)
    def build(processor, provider, texts, context):
        return processor_module.AutoCaptionProcessor._build_codex_candidate(processor, texts, context)
    processor = _processor_fixture(tmp_path, monkeypatch, ['codex'], build)
    return processor, now, executed, execute


def test_cold_calibration_completes_full_candidate_with_quality_reserve(tmp_path, monkeypatch):
    processor, now, calls, _ = _real_host_processor(tmp_path, monkeypatch)
    segments = [dict(text='Hello world.')] * 31
    result = processor._translate_segments(segments)
    assert len(calls) == 7 and now[0] == 156
    assert len(result) == 31 and all(row['zh_text'] == '你好世界。' for row in result)
    events = processor._translation_throughput_events
    assert events[0]['probe'] and events[0]['estimated_ms'] == 840000
    assert events[2]['cost_basis'] == 'validated_batch_max_x1.5'
    assert events[2]['estimated_ms'] == 72000
    assert processor._translation_quality_audit[-1]['selected']
    ledger = next((tmp_path / 'output').glob('subtitle_candidate_cache/subtitle-attempt-budget-v1/*/budget.json'))
    assert json.loads(ledger.read_text())['used_seconds'] == 56


def test_slow_calibration_stops_before_second_request_and_never_applies_partial(tmp_path, monkeypatch):
    from video_processing.utils.subtitle_failure_receipt import SubtitleTranslationFailure
    processor, now, calls, _ = _real_host_processor(tmp_path, monkeypatch, seconds=100)
    segments = [dict(text='Hello world.') for _ in range(31)]
    with pytest.raises(SubtitleTranslationFailure):
        processor._translate_segments(segments)
    assert len(calls) == 1
    assert all('zh_text' not in row for row in segments)
    assert processor._translation_throughput_events[-1]['action'] == 'batch_not_admitted'
    assert processor._translation_throughput_events[-1]['estimated_ms'] == 900000
    with pytest.raises(SubtitleTranslationFailure):
        processor._translate_segments(segments)
    assert len(calls) == 1


def test_interruption_reuses_batch_without_shrinking_cumulative_limit(tmp_path, monkeypatch):
    from video_processing.utils.translation_context import build_translation_context
    processor, now, calls, _ = _real_host_processor(tmp_path, monkeypatch, interrupt_second=True)
    segments = [dict(text='Hello world.') for _ in range(31)]
    with pytest.raises(KeyboardInterrupt):
        processor._translate_segments(segments)
    assert calls == [list(range(5))]
    assert all('zh_text' not in row for row in segments)
    state_path = _codex_state_path(tmp_path / 'output' / 'codex_text_cache',
        [row['text'] for row in segments], build_translation_context([row['text'] for row in segments]).to_prompt_context())
    before = json.loads(state_path.read_text())
    assert before['total_timeout'] == 600 and before['calibration_claimed']
    processor, now2, resumed, _ = _real_host_processor(tmp_path, monkeypatch)
    result = processor._translate_segments(segments)
    assert resumed[0] == list(range(5, 10)) and len(resumed) == 6
    assert len(result) == 31 and processor._translation_quality_audit[-1]['selected']
    after = json.loads(state_path.read_text())
    assert after['total_timeout'] == 600 and after['elapsed_seconds'] >= before['elapsed_seconds'] + 48


def test_claimed_calibration_cannot_repeat_after_cache_loss_or_binding_change(tmp_path, monkeypatch):
    from video_processing.utils.subtitle_recovery_state import SubtitleRecoveryState
    from video_processing.utils.codex_text_provider import CodexTextError
    arguments = dict(texts=['Hello world.'], context='Source', model='gpt-5.6-luna', effort='medium',
        batch_size=5, max_attempts=2, max_requests=5, total_timeout=600, request_timeout=120)
    with SubtitleRecoveryState(tmp_path, **arguments) as state:
        state.claim_calibration()
    with SubtitleRecoveryState(tmp_path, **arguments) as state:
        with pytest.raises(CodexTextError, match='candidate_not_admitted_budget'):
            state.claim_calibration()

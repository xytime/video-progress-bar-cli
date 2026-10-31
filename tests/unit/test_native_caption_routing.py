"""原字幕分流验证：完整、部分、假阳性、证据失效及实际处理器恢复边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.2 | 2026-10-30 | Codex | 尾段越界须在任何画面读取或供应商请求前拒绝，不花费已知无效全片的批次预算。 |
| 1.0.1 | 2026-10-30 | Codex | 实际图像与真实结构化缓存证明等价扫描零重复调用，字幕事实变化仍失效。 |
| 1.0.0 | 2026-10-27 | Codex | 宿主三态、OCR/语义失败关闭、缓存与无重复烧录。 |
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_processing.utils import native_caption_source as native
from video_processing.utils.file_utils import read_subtitle_text, write_json_atomically
from video_processing.utils.render_source_binding import digest
from video_processing.utils.source_caption_contract import (
    VERSION, decide, decision_path, evidence_path, fingerprint, validate_decision,
)
from video_processing.processors import native_caption_router as router
from tests.unit.test_caption_checkpoints import processor


@pytest.fixture
def evidence():
    return dict(source_sha256='source', fps=10, frame_count=40, width=360, height=640, error='',
                segments=[dict(start=0, end=2, text='Bonds still matter.'),
                          dict(start=2, end=4, text='Prices are rising.')],
                runs=[dict(id=0, text='债券仍然重要', chinese=True, confidence=.99, first=0, last=20),
                      dict(id=1, text='價格正在上漲', chinese=True, confidence=.99, first=20, last=40)],
                reviews=[dict(segment_id=0, decision='COMPLETE', run_ids=[0], visual_verified_run_ids=[0], reason='verified'),
                         dict(segment_id=1, decision='COMPLETE', run_ids=[1], visual_verified_run_ids=[1], reason='verified')])


def save_evidence(output, evidence):
    entry = dict(version=VERSION, source_sha256=evidence['source_sha256'],
                 asr_sha256=fingerprint(evidence['segments']), evidence_sha256=fingerprint(evidence),
                 **decide(evidence))
    write_json_atomically(evidence_path(output), evidence)
    write_json_atomically(decision_path(output), dict(entry=entry, sha256=fingerprint(entry)))


def test_simplified_traditional_bilingual_complete(evidence):
    assert decide(evidence)['decision'] == 'PRESERVE'
    assert '價格正在上漲' in decide(evidence)['review_text']
    evidence['runs'].append(dict(id=2, text='Bonds still matter.', chinese=False,
                                 confidence=.99, first=0, last=20))
    assert decide(evidence)['decision'] == 'PRESERVE'


def test_equivalent_scan_reuses_semantic_cache_but_changed_ocr_invalidates(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from config.settings import settings
    from video_processing.utils import codex_text_provider as provider
    from tests.unit.test_codex_text_provider import _executor

    source = tmp_path / 'source.avi'
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 64))
    assert writer.isOpened()
    try:
        for _ in range(4):
            writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    finally:
        writer.release()
    segments = [dict(start=0., end=.4, text='Bonds still matter.')]
    scanned = dict(fps=10., frame_count=4, width=64, height=64,
                   runs=[dict(id=0, text='债券仍然重要', chinese=True, confidence=.99,
                              box=[.1, .7, .9, .9], first=0, last=4)])
    reviews = [dict(segment_id=0, decision='COMPLETE', run_ids=[0],
                    visual_verified_run_ids=[0], reason='verified')]
    calls = []
    monkeypatch.setattr(provider, '_execute', _executor(payload=dict(reviews=reviews), calls=calls))
    monkeypatch.setattr(settings, 'codex_text_model', 'gpt-5.6-luna')
    directory = tmp_path / 'semantic'
    directory.mkdir()
    assert router.review(source, segments, scanned, directory, lambda _: None) == reviews
    monkeypatch.setattr(settings, 'native_caption_semantic_paging_enabled', True)
    optimized = dict(deepcopy(scanned), frame_evidence=dict(contract='strict-identical-pixels'))
    assert router.review(source, segments, optimized, directory, lambda _: None) == reviews
    assert len(calls) == 1
    optimized['runs'][0]['text'] = '价格正在上涨'
    router.review(source, segments, optimized, directory, lambda _: None)
    assert len(calls) == 2


def test_late_timeline_overrun_is_rejected_before_any_batch(tmp_path, monkeypatch):
    scanned = dict(fps=30., frame_count=1747, width=360, height=640, runs=[])
    segments = [dict(start=float(i), end=float(i + 1), text='Speech.') for i in range(21)]
    segments[-1] = dict(start=56.64, end=58.72, text="That's your expertise.")
    calls = []
    monkeypatch.setattr(router, 'run_codex_structured', lambda *a, **k: calls.append('model'))
    monkeypatch.setattr(router.cv2, 'VideoCapture', lambda *a, **k: calls.append('decode'))
    with pytest.raises(ValueError, match='SOURCE_TIMELINE_UNCERTAIN'):
        router.review(tmp_path / 'unused.mp4', segments, scanned, tmp_path, lambda _: None)
    assert calls == []


@pytest.mark.parametrize('damage', ['partial', 'gap', 'low_confidence', 'unknown_run', 'duplicate',
                                   'missing_review', 'bad_time', 'not_chinese', 'uncertain', 'ocr_failure',
                                   'missing_visual'])
def test_incomplete_or_untrusted_evidence_cannot_preserve_or_generate(evidence, damage):
    if damage == 'partial': evidence['reviews'][1].update(decision='ABSENT', run_ids=[])
    if damage == 'gap': evidence['runs'][1]['last'] = 30
    if damage == 'low_confidence': evidence['runs'][1]['confidence'] = .2
    if damage == 'unknown_run': evidence['reviews'][1]['run_ids'] = [17]
    if damage == 'duplicate': evidence['reviews'][1]['run_ids'] = [1, 1]
    if damage == 'missing_review': evidence['reviews'].pop()
    if damage == 'bad_time': evidence['segments'][1]['end'] = 5
    if damage == 'not_chinese': evidence['runs'][1]['chinese'] = False
    if damage == 'uncertain': evidence['reviews'][1]['decision'] = 'UNCERTAIN'
    if damage == 'ocr_failure': evidence['error'] = 'OCR_UNAVAILABLE'
    if damage == 'missing_visual': evidence['reviews'][0]['visual_verified_run_ids'] = []
    assert decide(evidence)['decision'] == 'REVIEW'


@pytest.mark.parametrize('caption', ['Only English captions', '董事长致辞', '企业平台战略'])
def test_only_english_title_or_slide_requires_negative_semantic_evidence(evidence, caption):
    evidence['runs'][0]['text'] = caption
    for item in evidence['reviews']:
        item.update(decision='ABSENT', run_ids=[])
    assert decide(evidence)['decision'] == 'GENERATE'
    evidence['reviews'][0]['decision'] = 'UNCERTAIN'
    assert decide(evidence)['decision'] == 'REVIEW'


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / 'original_video/demo.mp4'
    path.parent.mkdir()
    path.write_bytes(b'source')
    monkeypatch.setattr(native, 'APPROVALS', tmp_path / 'absent.json')
    return path


def test_automatic_preserve_final_selection_and_review_text(source, evidence):
    from video_processing.pipeline_manager import PipelineManager
    output = source.parent.parent / 'demo_vertical.mp4'
    evidence['source_sha256'] = digest(source)
    save_evidence(output, evidence)
    native.preserve(source, output)
    assert output.read_bytes() == source.read_bytes()
    assert native.requested(output)
    assert 'Bonds still matter.' in read_subtitle_text(output.parent, 'demo')
    assert PipelineManager._get_published_video_path(SimpleNamespace(_OUT_DIR=output.parent), 'demo') == output
    # 宿主证据不可只改决定/哈希来跳过内容校验。
    evidence['runs'][0]['last'] = 1
    save_evidence(output, evidence)
    with pytest.raises(ValueError):
        native.validate_preserved(output, source)


def test_corrupted_decision_cannot_fall_back_to_stale_ass(source, evidence):
    output = source.parent.parent / 'demo_vertical.mp4'
    evidence['source_sha256'] = digest(source)
    save_evidence(output, evidence)
    native.preserve(source, output)
    decision_path(output).write_text('{}')
    (output.parent / 'demo.ass').write_text('stale')
    with pytest.raises((ValueError, KeyError)):
        read_subtitle_text(output.parent, 'demo')


def test_cropped_source_binding_survives_submission_lookup(source, evidence):
    output = source.parent.parent / 'demo_vertical.mp4'
    cropped = source.parent.parent / 'speech_opening' / 'demo' / 'trimmed.mp4'
    cropped.parent.mkdir(parents=True)
    cropped.write_bytes(b'cropped with native captions')
    evidence['source_sha256'] = digest(cropped)
    save_evidence(output, evidence)
    native.preserve(cropped, output)
    assert native.preserved_source(output, source) == cropped.resolve()
    assert native.validate_preserved(output, cropped)
    with pytest.raises(ValueError):
        native.validate_preserved(output, source)


def test_cached_decision_reused_without_scanning_or_provider(source, evidence, monkeypatch):
    output = source.parent.parent / 'demo_vertical.mp4'
    evidence['source_sha256'] = digest(source)
    save_evidence(output, evidence)
    def fail(*args): raise AssertionError('must not rescan')
    monkeypatch.setattr(router, 'scan', fail)
    assert router.route(source, output, evidence['segments']) == 'PRESERVE'
    source.write_bytes(b'new source')
    with pytest.raises(router.NativeCaptionReviewRequired):
        router.route(source, output, evidence['segments'])


@pytest.mark.parametrize('failing_stage', ['scan', 'review'])
def test_failed_scanner_or_provider_records_review_not_generate(source, evidence, monkeypatch, failing_stage):
    output = source.parent.parent / 'demo_vertical.mp4'
    monkeypatch.setattr(router, 'scan', lambda *args: evidence)
    def fail(*args): raise ValueError('OCR_UNAVAILABLE')
    monkeypatch.setattr(router, failing_stage, fail)
    with pytest.raises(router.NativeCaptionReviewRequired, match='OCR_UNAVAILABLE'):
        router.route(source, output, evidence['segments'])
    assert validate_decision(output)['decision'] == 'REVIEW'
    assert not output.exists()


def test_processor_preserves_before_translation_and_ass(source, evidence):
    p = processor(source)
    p.output_path = source.parent.parent / 'demo_vertical.mp4'
    p.preserve_source_chinese = True
    evidence['source_sha256'] = digest(source)
    evidence['segments'] = evidence['segments'][:1]
    evidence['reviews'] = evidence['reviews'][:1]
    save_evidence(p.output_path, evidence)
    assert p.process() == p.output_path
    assert p.calls == ['audio', 'model', 'asr']
    assert not source.with_suffix('.ass').exists()
    again = processor(source)
    again.output_path, again.preserve_source_chinese = p.output_path, True
    again.process()
    assert again.calls == []


def test_generate_route_continues_normal_translation(source, evidence):
    p = processor(source)
    p.output_path = source.parent.parent / 'demo_vertical.mp4'
    p.preserve_source_chinese = True
    evidence['source_sha256'] = digest(source)
    evidence['segments'] = evidence['segments'][:1]
    evidence['reviews'] = [dict(segment_id=0, decision='ABSENT', run_ids=[], reason='English only')]
    save_evidence(p.output_path, evidence)
    p.process()
    assert p.calls == ['audio', 'model', 'asr', 'translation', 'layout', 'render']


def test_review_failure_keeps_asr_for_explicit_retry(source, evidence, monkeypatch):
    p = processor(source)
    p.output_path = source.parent.parent / 'demo_vertical.mp4'
    p.preserve_source_chinese = True
    def blocked(*args): raise router.NativeCaptionReviewRequired('partial captions')
    monkeypatch.setattr(router, 'route', blocked)
    with pytest.raises(router.NativeCaptionReviewRequired): p.process()
    assert p.calls == ['audio', 'model', 'asr']
    assert list(source.parent.glob('.caption-checkpoints/*/asr.json'))
    assert not p.output_path.exists()


def test_long_landscape_preserve_requires_layout_review(source, evidence, monkeypatch):
    output = source.parent.parent / 'demo_vertical.mp4'
    evidence['width'], evidence['height'] = 1920, 1080
    monkeypatch.setattr(router, 'scan', lambda *args: evidence)
    monkeypatch.setattr(router, 'review', lambda *args: evidence['reviews'])
    with pytest.raises(router.NativeCaptionReviewRequired, match='横屏'):
        router.route(source, output, evidence['segments'])

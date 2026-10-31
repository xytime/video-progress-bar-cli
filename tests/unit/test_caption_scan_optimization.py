"""全帧优化：严格相等证据、旧缓存连续性和有完整前缀的分块恢复。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-29 | Codex | 文件传输夹具与旧 v3 缓存兼容，保留原完整帧失效及续扫断言。 |
| 1.0.0 | 2026-10-29 | Codex | 无实际 OCR/模型的同像素、失效、断点及编码回归。 |
"""
from contextlib import nullcontext
import hashlib
import json
import subprocess
import sys

import cv2
import numpy as np
import pytest

from video_processing.processors import native_caption_router as native
from video_processing.processors import burned_caption_repair as burned
from video_processing.utils.caption_scan_runtime import (
    ExactFrameReuse, ObservationChunks, checksum, validate_observation, checkpoint_elapsed,
)
from video_processing.utils.source_caption_contract import fingerprint
from video_processing.utils import caption_scan_runtime as runtime


def make_video(tmp_path):
    source = tmp_path / 'repeated.avi'
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 64))
    assert writer.isOpened()
    for value in (0, 0, 30, 30, 60, 60, 90, 90):
        writer.write(np.full((64, 64, 3), value, dtype=np.uint8))
    writer.release()
    directory = tmp_path / 'scan'
    directory.mkdir()
    return source, directory


@pytest.fixture
def native_scan(tmp_path, monkeypatch):
    source, directory = make_video(tmp_path)
    monkeypatch.setattr(burned, '_probe', lambda _: (64, 64, 10., .8))
    monkeypatch.setattr(native, 'vision_worker', lambda: nullcontext(None))
    monkeypatch.setattr(native, 'file_worker', lambda _: nullcontext(None))
    return source, directory


def test_exact_pixel_reuse_is_not_similarity_and_never_reuses_failure():
    reuse = ExactFrameReuse()
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    assert reuse.lookup(frame) is None
    reuse.commit(frame, [], 0, reused=False)
    assert reuse.lookup(frame.copy()) == []
    reuse.commit(frame, [], 1, reused=True)
    changed = frame.copy()
    changed[7, 7, 2] = 1
    assert reuse.lookup(changed) is None
    # 未 commit 的失败帧不能替换上一条成功识别。
    assert reuse.lookup(frame) == []
    assert reuse.lookup(frame.astype(np.float32)) is None
    assert reuse.evidence(2)['reuse_spans'] == [dict(first=1, last=2, observed_frame=0,
        pixel_sha256=hashlib.sha256(memoryview(frame)).hexdigest())]


@pytest.mark.parametrize('response', ['not-json', '{}', '[]', '{"error":"VISION_FAILED","rows":[],"faces":[]}'])
def test_worker_failure_or_missing_rows_never_becomes_successful_empty_evidence(response):
    for observe in (native.observe,):
        worker = subprocess.Popen([sys.executable,'-u','-c',
            'import sys; sys.stdin.readline(); print('+repr(response)+', flush=True)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            with pytest.raises(ValueError):
                observe(worker, np.zeros((8,8,3),dtype=np.uint8))
        finally:
            worker.stdin.close()
            worker.wait(timeout=5)
            worker.stdout.close()


def test_checkpoint_elapsed_rejects_invalid_evidence():
    assert checkpoint_elapsed(None) == 0 and checkpoint_elapsed({'scan_wall_seconds':12.5}) == 12.5
    for value in (-1, True, float('inf'), '12'):
        with pytest.raises(ValueError, match='OCR_CHECKPOINT_BUDGET_INVALID'):
            checkpoint_elapsed({'scan_wall_seconds':value})


def test_native_full_frame_scan_reuses_only_exact_pixels_and_preserves_runs(native_scan, monkeypatch):
    source, directory = native_scan
    calls = []
    def observe(worker, frame, **kwargs):
        calls.append(round(float(frame.mean())))
        return [dict(text='完整中文字幕', box=[-.001, .1, .9, .2], confidence=.7)]
    monkeypatch.setattr(native, 'observe', observe)
    result = native._scan_frames(source, directory, lambda _: None, optimized=True)
    assert calls == [0, 30, 60, 90]
    assert result['frame_count'] == 8
    assert result['runs'][0]['first'] == 0 and result['runs'][0]['last'] == 8
    assert result['runs'][0]['confidence'] == .7
    assert len(result['runs'][0]['boundary_adjustments']) == 8
    spans = result['frame_evidence']['reuse_spans']
    assert [(s['first'], s['last'], s['observed_frame']) for s in spans] == [(1,2,0),(3,4,2),(5,6,4),(7,8,6)]
    calls.clear()
    assert native._scan_frames(source, directory, lambda _: None, optimized=True) == result
    assert calls == []


@pytest.mark.parametrize('optimized', [False,True])
def test_native_resume_keeps_consumed_wall_budget(native_scan, monkeypatch, optimized):
    source, directory = native_scan
    calls = []
    def observe(worker, frame, **kwargs):
        value = round(float(frame.mean()))
        calls.append(value)
        if value == 60:
            raise ValueError('OCR_BUDGET_EXCEEDED')
        return []
    monkeypatch.setattr(native, 'observe', observe)
    with pytest.raises(ValueError):
        native._scan_frames(source, directory, lambda _:None, optimized=optimized)
    path = directory/'checkpoints'/'manifest.json' if optimized else directory/'partial-scan.json'
    data = json.loads(path.read_text())
    metadata = data['state'].setdefault('metadata', {}) if optimized else data['state']
    metadata['scan_wall_seconds'] = 999999.
    data['sha256'] = fingerprint(data['state'])
    path.write_text(json.dumps(data))
    before = calls.copy()
    with pytest.raises(ValueError, match='OCR_BUDGET_EXCEEDED'):
        native._scan_frames(source, directory, lambda _:None, optimized=optimized)
    assert calls == before  # 预算耗尽后不能以新 owner/新进程重新获得扫描额度。


def test_native_resume_first_frame_is_observed_and_invalid_map_cannot_pass(native_scan, monkeypatch):
    source, directory = native_scan
    calls, failing = [], [True]
    def observe(worker, frame, **kwargs):
        value = round(float(frame.mean()))
        calls.append(value)
        if value == 60 and failing[0]:
            raise ValueError('OCR_BUDGET_EXCEEDED')
        return []
    monkeypatch.setattr(native, 'observe', observe)
    with pytest.raises(ValueError, match='OCR_BUDGET_EXCEEDED'):
        native._scan_frames(source, directory, lambda _: None, optimized=True)
    state = json.loads((directory/'checkpoints'/'manifest.json').read_text())['state']
    assert state['frame_count'] == 4
    failing[0] = False
    calls.clear()
    result = native._scan_frames(source, directory, lambda _: None, optimized=True)
    assert calls == [60,90]
    assert result['frame_count'] == 8
    envelope = json.loads((directory/'scan.json').read_text())
    envelope['scan']['frame_evidence']['reuse_spans'][0]['observed_frame'] = 1
    envelope['sha256'] = fingerprint(envelope['scan'])
    (directory/'scan.json').write_text(json.dumps(envelope))
    calls.clear()
    native._scan_frames(source, directory, lambda _: None, optimized=True)
    # 非法完整映射被拒绝，完整校验的分块仍可重建结果，不再调用 OCR。
    assert calls == []


@pytest.mark.parametrize('partial', [False, True])
def test_enabling_optimization_does_not_discard_legacy_cache_or_partial(native_scan, monkeypatch, partial):
    source, directory = native_scan
    calls, failing = [], [partial]
    def observe(worker, frame, **kwargs):
        value = round(float(frame.mean()))
        calls.append(value)
        if value == 60 and failing[0]:
            raise ValueError('OCR_BUDGET_EXCEEDED')
        return []
    monkeypatch.setattr(native, 'observe', observe)
    if partial:
        with pytest.raises(ValueError):
            native._scan_frames(source, directory, lambda _: None)
    else:
        native._scan_frames(source, directory, lambda _: None)
    previous = (directory/('partial-scan.json' if partial else 'scan.json')).read_bytes()
    failing[0] = False
    calls.clear()
    monkeypatch.setattr(native.settings, 'native_caption_scan_optimization_enabled', True)
    assert native.scan(source, directory, lambda _: None)['frame_count'] == 8
    assert calls == ([60,60,90,90] if partial else [])
    assert not (directory/'native-scan-v3-exact').exists()
    if not partial:
        assert (directory/'scan.json').read_bytes() == previous


@pytest.mark.parametrize('compression', [0,1,3,9])
def test_png_experiment_keeps_all_pixels(compression):
    frame = np.random.default_rng(9).integers(0, 256, (48, 64, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode('.png', frame, [cv2.IMWRITE_PNG_COMPRESSION, compression])
    assert ok and np.array_equal(frame, cv2.imdecode(encoded, cv2.IMREAD_COLOR))


@pytest.mark.parametrize('partial', [False, True])
def test_file_transport_keeps_previous_exact_scan_namespace(native_scan, monkeypatch, partial):
    source, directory = native_scan
    previous = directory / 'native-scan-v3-exact'
    previous.mkdir()
    calls, failing = [], [partial]
    def observe(worker, frame, **kwargs):
        value = round(float(frame.mean()))
        calls.append(value)
        if value == 60 and failing[0]:
            raise ValueError('OCR_BUDGET_EXCEEDED')
        return []
    monkeypatch.setattr(native, 'observe', observe)
    if partial:
        with pytest.raises(ValueError):
            native._scan_frames(source, previous, lambda _:None, optimized=True, file_transport=False)
    else:
        native._scan_frames(source, previous, lambda _:None, optimized=True, file_transport=False)
    failing[0] = False
    calls.clear()
    monkeypatch.setattr(native.settings, 'native_caption_scan_optimization_enabled', True)
    assert native.scan(source, directory, lambda _:None)['frame_count'] == 8
    assert calls == ([60,90] if partial else [])
    assert not (directory/'native-scan-v4-file').exists()


def test_chunk_integrity_contiguous_prefix_and_orphan_rejection(tmp_path):
    identity, timeline = dict(version='test'), dict(expected=610)
    observations = [dict(rows=[], faces=[]) for _ in range(610)]
    store = ObservationChunks(tmp_path/'chunks', identity, timeline)
    store.save(observations)
    assert [e['last']-e['first'] for e in store.entries] == [300,300,10]
    # 未被 manifest 引用的文件不影响恢复前缀。
    (tmp_path/'chunks'/'orphan.json').write_text('invalid')
    assert ObservationChunks(tmp_path/'chunks', identity, timeline).load(validate_observation) == observations
    target = tmp_path/'chunks'/store.entries[1]['file']
    value = json.loads(target.read_text())
    value['observations'][0]['faces'] = [[0.,0.,1.,1.]]
    target.write_text(json.dumps(value))
    assert ObservationChunks(tmp_path/'chunks', identity, timeline).load(validate_observation) == []

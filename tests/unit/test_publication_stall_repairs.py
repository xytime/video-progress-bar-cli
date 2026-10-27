"""断流修复：真实维护凭据、边缘框、逐帧扫描续接与损坏断点拒绝。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-28 | Codex | 最小环境及合成视频断点回归，不访问发布器。 |
"""
from contextlib import nullcontext
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from video_processing import pipeline_manager as pm
from video_processing.processors import native_caption_router as router
from video_processing.processors import burned_caption_repair
from video_processing.utils.subprocess_env import build_subprocess_env


@pytest.mark.parametrize('explicit', [False, True])
def test_environment_prepared_before_real_maintenance_wrapper(monkeypatch, isolated_running_maintenance, explicit):
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    monkeypatch.setattr(pm, '_build_subprocess_env', lambda: build_subprocess_env(
        include_proxies=False, include_gemini=False, include_telegram=False))
    manager = pm.PipelineManager.__new__(pm.PipelineManager)
    def inspect(cmd, yid, slice_index, **options):
        env = options['env']
        if explicit:
            assert env['PATH'] == '/explicit/tools'
        else:
            assert str(Path.home() / '.local/bin') in env['PATH'].split(':')
        fd = int(env['MAINTENANCE_CHILD_FD'])
        assert fd in options['pass_fds']
        assert os.fstat(fd).st_size > 0
        assert env['MAINTENANCE_CHILD_RECEIPT']
        return 'verified'
    monkeypatch.setattr(manager, '_run_tracked_impl', inspect)
    with isolated_running_maintenance.admit('test', 'env-check') as ticket:
        ticket.start()
        with ticket.bind():
            args = {'env': {'PATH': '/explicit/tools'}} if explicit else {}
            assert manager._run_tracked(['python', 'copywriter.py'], 'synthetic', **args) == 'verified'


# 2026-10-27 四个真实失败帧的 Vision 坐标，不含来源正文。
@pytest.mark.parametrize('box', [
    [-.002354157422490566, .30059499253898525, 1.0009584303155465, .5198541486601331],
    [.015509769383022575, .9426619326746428, .9985643119245264, 1.001772409910225],
    [.6014953179215331, .44716042386211186, 1.0093732876633543, .7140269382799722],
    [-.000202896640778355, -.0019031906998459025, .06895289774131699, .02690319105555905],
])
def test_real_vision_edge_coordinates_preserve_confidence_and_raw_box(box):
    row = router.normalize_row(dict(text='原始文字', box=box, confidence=.30000001192092896))
    assert row['raw_box'] == box
    assert all(0 <= v <= 1 for v in row['box'])
    assert row['confidence'] == .30000001192092896


@pytest.mark.parametrize('box,confidence', [
    ([-.02, 0, 1, 1], .9), ([0, 0, 1.02, 1], .9),
    ([.7, 0, .2, 1], .9), ([-.005, 0, -.001, 1], .9),
    ([0, 0, float('nan'), 1], .9), ([0, 0, 1, 1], float('inf')),
    ([0, 0, 1, 1], 1.1), ([0, 0], .9),
])
def test_invalid_geometry_or_confidence_stays_blocked(box, confidence):
    with pytest.raises(ValueError, match='OCR_INVALID_ROW'):
        router.normalize_row(dict(text='文字', box=box, confidence=confidence))


@pytest.fixture
def scan_fixture(tmp_path, monkeypatch):
    source = tmp_path / 'sample.avi'
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 64))
    assert writer.isOpened()
    for i in range(8):
        writer.write(np.full((64, 64, 3), i * 25, dtype=np.uint8))
    writer.release()
    directory = tmp_path / 'scan'
    directory.mkdir()
    monkeypatch.setattr(burned_caption_repair, '_probe', lambda _: (64, 64, 10., .8))
    monkeypatch.setattr(router, 'vision_worker', lambda: nullcontext(None))
    return source, directory


def test_resumed_scan_matches_uninterrupted_without_skipped_or_duplicate_frames(scan_fixture, monkeypatch):
    source, directory = scan_fixture
    visited = []
    fail = [True]
    def observe(worker, frame, **kwargs):
        index = round(float(frame.mean()) / 25)
        visited.append(index)
        if index == 3 and fail[0]:
            raise ValueError('OCR_BUDGET_EXCEEDED')
        return [dict(text='连续字幕', box=[-.002, .1, .9, .2], confidence=.9)]
    monkeypatch.setattr(router, 'observe', observe)
    with pytest.raises(ValueError, match='OCR_BUDGET_EXCEEDED'):
        router.scan(source, directory, lambda _: None)
    checkpoint = json.loads((directory / 'partial-scan.json').read_text())
    assert checkpoint['state']['frame_count'] == 3
    fail[0] = False
    visited.clear()
    resumed = router.scan(source, directory, lambda _: None)
    assert visited == [3, 4, 5, 6, 7]
    assert resumed['runs'][0]['first'] == 0 and resumed['runs'][0]['last'] == 8
    assert len(resumed['runs'][0]['boundary_adjustments']) == 8
    clean = directory.parent / 'clean'
    clean.mkdir()
    assert router.scan(source, clean, lambda _: None) == resumed


@pytest.mark.parametrize('damage', ['checksum', 'source', 'scanner', 'timeline', 'legacy'])
def test_invalid_checkpoint_restarts_without_trusting_old_frames(scan_fixture, monkeypatch, damage):
    source, directory = scan_fixture
    visited = []
    fail = [True]
    def observe(worker, frame, **kwargs):
        index = round(float(frame.mean()) / 25)
        visited.append(index)
        if index == 2 and fail[0]:
            raise ValueError('OCR_TIMEOUT')
        return []
    monkeypatch.setattr(router, 'observe', observe)
    with pytest.raises(ValueError):
        router.scan(source, directory, lambda _: None)
    path = directory / 'partial-scan.json'
    data = json.loads(path.read_text())
    if damage == 'checksum': data['sha256'] = 'bad'
    elif damage == 'source': data['identity']['source_sha256'] = 'different'
    elif damage == 'scanner': data['identity']['scan_version'] = 'old'
    elif damage == 'timeline':
        data['state']['timeline']['fps'] = 12
        data['sha256'] = router.fingerprint(data['state'])
    else: data = dict(identity=data['identity'], frame_count=2, runs=[])
    path.write_text(json.dumps(data))
    visited.clear()
    fail[0] = False
    assert router.scan(source, directory, lambda _: None)['frame_count'] == 8
    assert visited == list(range(8))


def test_round_deadline_does_not_commit_over_budget_frame(scan_fixture, monkeypatch):
    import time
    source, directory = scan_fixture
    def slow_observe(worker, frame, **kwargs):
        time.sleep(.02)
        return []
    monkeypatch.setattr(router, 'observe', slow_observe)
    monkeypatch.setattr(router, 'MAX_SCAN_SECONDS', .01)
    with pytest.raises(ValueError, match='OCR_BUDGET_EXCEEDED'):
        router.scan(source, directory, lambda _: None)
    checkpoint = json.loads((directory / 'partial-scan.json').read_text())
    assert checkpoint['state']['frame_count'] == 0
    assert checkpoint['state']['runs'] == []


def test_bad_row_does_not_partially_commit_frame(scan_fixture, monkeypatch):
    source, directory = scan_fixture
    def invalid_observe(worker, frame, **kwargs):
        return [dict(text='正常框', box=[0, 0, .5, .5], confidence=.9),
                dict(text='异常框', box=[0, 0, 2, 1], confidence=.9)]
    monkeypatch.setattr(router, 'observe', invalid_observe)
    with pytest.raises(ValueError, match='OCR_INVALID_ROW'):
        router.scan(source, directory, lambda _: None)
    checkpoint = json.loads((directory / 'partial-scan.json').read_text())
    assert checkpoint['state']['frame_count'] == 0
    assert checkpoint['state']['runs'] == []

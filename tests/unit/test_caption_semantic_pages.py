"""验证真实图片/结构化缓存、完整分页证明及累计预算；模型判定使用可控故障注入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 超量证据、损坏/中断缓存、预算及原质量门回归。 |
"""
from copy import deepcopy
import json
import subprocess
import sys

import cv2
import numpy as np
import pytest

from config.settings import settings
from video_processing.processors import native_caption_router as router
from video_processing.utils import codex_text_provider as provider
from video_processing.utils.caption_review_frames import ReviewFrames
from video_processing.utils.caption_scan_runtime import ScanMetrics
from video_processing.utils.caption_visual_pages import CONTRACT, group_rows, page_groups
from video_processing.utils.source_caption_contract import decide
from tests.unit.test_codex_text_provider import _executor


@pytest.fixture
def sample(tmp_path, monkeypatch):
    source = tmp_path / 'source.avi'
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 64))
    assert writer.isOpened()
    for index in range(80):
        writer.write(np.full((64, 64, 3), index, dtype=np.uint8))
    writer.release()
    monkeypatch.setattr(settings, 'native_caption_semantic_paging_enabled', True)
    monkeypatch.setattr(settings, 'codex_text_model', 'gpt-5.6-luna')
    evidence = dict(fps=10., frame_count=80, width=64, height=64, error='',
                    segments=[dict(start=0., end=8., text='Complete source speech.')],
                    runs=[dict(id=i, text=f'完整中文字幕{i}', box=[.1, .7, .9, .9],
                               chinese=True, confidence=.99, first=i, last=(i + 1 if i < 71 else 80))
                          for i in range(72)])
    return source, evidence, tmp_path


def controlled_model(calls, classification='DIALOGUE_CHINESE', interrupt_at=None):
    def execute(args, prompt, directory, timeout):
        data = json.loads(prompt.split('\n', 1)[1])
        if interrupt_at is not None and len(calls) == interrupt_at:
            raise RuntimeError('simulated transport loss')
        calls.append(dict(data=data, image_count=args.count('--image'), timeout=timeout))
        if 'visual_groups' in data:
            payload = dict(context_clear=True, groups=[dict(group_id=g['group_id'], classification=classification,
                                                           exact_text=True, reason='visible evidence')
                                                      for g in data['visual_groups']])
        else:
            payload = dict(reviews=[dict(segment_id=data['segment_id'],
                                        decision='COMPLETE' if data['verified_run_ids'] else 'ABSENT',
                                        run_ids=data['verified_run_ids'],
                                        visual_verified_run_ids=data['verified_run_ids'], reason='whole segment')])
        return _executor(payload=payload)(args, prompt, directory, timeout)
    return execute


def run(sample):
    source, evidence, directory = sample
    return router.review(source, evidence['segments'], evidence, directory, lambda _: None)


def test_all_72_groups_use_five_bounded_requests_and_cached_replay_decodes_nothing(sample, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, '_execute', controlled_model(calls))
    reviews = run(sample)
    assert [c['image_count'] for c in calls] == [23, 23, 24, 12, 3]
    assert [g['group_id'] for c in calls[:-1] for g in c['data']['visual_groups']] == list(range(72))
    assert all(0 < c['timeout'] <= settings.codex_text_request_timeout_seconds for c in calls)
    assert calls[-1]['timeout'] < calls[0]['timeout']
    assert decide(dict(sample[1], reviews=reviews))['decision'] == 'PRESERVE'
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *_: pytest.fail('cached replay must not decode'))
    assert run(sample) == reviews
    assert len(calls) == 5


def test_same_frame_image_is_shared_without_dropping_any_group(sample, monkeypatch):
    for row in sample[1]['runs']:
        row['first'] = row['id'] // 3
        row['last'] = row['first'] + 1 if row['id'] < 71 else 80
    calls = []
    monkeypatch.setattr(provider, '_execute', controlled_model(calls))
    reviews = run(sample)
    assert [c['image_count'] for c in calls] == [9, 10, 10, 6, 3]
    assert [g['group_id'] for c in calls[:-1] for g in c['data']['visual_groups']] == list(range(72))
    for call in calls[:-1]:
        frame_to_image = {}
        rows = {r['id']: r for r in call['data']['rows']}
        for group in call['data']['visual_groups']:
            frame = rows[group['run_ids'][0]]['first']
            assert frame_to_image.setdefault(frame, group['image_index']) == group['image_index']
    assert decide(dict(sample[1], reviews=reviews))['decision'] == 'PRESERVE'


def test_partial_page_cache_survives_interruption_without_repeating_finished_requests(sample, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, '_execute', controlled_model(calls, interrupt_at=2))
    with pytest.raises(RuntimeError, match='transport loss'):
        run(sample)
    monkeypatch.setattr(provider, '_execute', controlled_model(calls))
    reviews = run(sample)
    assert len(calls) == 5
    assert decide(dict(sample[1], reviews=reviews))['decision'] == 'PRESERVE'


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'unknown', 'unclear', 'uncertain', 'not_exact',
                                   'binding', 'absent_conflict', 'unknown_selected', 'proof_missing'])
def test_bad_page_proof_fails_host_contract(sample, monkeypatch, damage):
    monkeypatch.setattr(provider, '_execute', controlled_model([]))
    reviews = run(sample)
    review = reviews[0]
    proof = review['visual_page_proof']
    if damage == 'missing': proof['pages'].pop()
    if damage == 'duplicate': proof['pages'][1] = deepcopy(proof['pages'][0])
    if damage == 'unknown': proof['pages'][0]['groups'][0]['group_id'] = 12345
    if damage == 'unclear': proof['pages'][0]['context_clear'] = False
    if damage == 'uncertain': proof['pages'][0]['groups'][0]['classification'] = 'UNCERTAIN'
    if damage == 'not_exact': proof['pages'][0]['groups'][0]['exact_text'] = False
    if damage == 'binding': proof['group_run_ids'][0] = [999]
    if damage == 'absent_conflict': review.update(decision='ABSENT', run_ids=[])
    if damage == 'unknown_selected': review['run_ids'].append(999)
    if damage == 'proof_missing': review.pop('visual_page_proof')
    assert decide(dict(sample[1], reviews=reviews))['decision'] == 'REVIEW'


@pytest.mark.parametrize('damage', ['confidence', 'gap', 'partial'])
def test_original_quality_thresholds_still_reject(sample, monkeypatch, damage):
    monkeypatch.setattr(provider, '_execute', controlled_model([]))
    reviews = run(sample)
    if damage == 'confidence': sample[1]['runs'][0]['confidence'] = .49
    if damage == 'gap': sample[1]['runs'][-1]['last'] = 74
    if damage == 'partial': reviews[0]['run_ids'] = [0]
    assert decide(dict(sample[1], reviews=reviews))['decision'] == 'REVIEW'


def test_absence_requires_every_page_to_exclude_chinese_dialogue(sample, monkeypatch):
    monkeypatch.setattr(provider, '_execute', controlled_model([], classification='NON_DIALOGUE'))
    assert decide(dict(sample[1], reviews=run(sample)))['decision'] == 'GENERATE'


def test_uncertain_page_stops_without_asking_for_positive_semantic_verdict(sample, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, '_execute', controlled_model(calls, classification='UNCERTAIN'))
    with pytest.raises(ValueError, match='VISUAL_PAGE_UNCERTAIN'):
        run(sample)
    assert len(calls) == 1


def test_disabled_flag_keeps_legacy_behavior(sample, monkeypatch):
    monkeypatch.setattr(settings, 'native_caption_semantic_paging_enabled', False)
    monkeypatch.setattr(provider, '_execute', lambda *_: pytest.fail('must not request'))
    with pytest.raises(ValueError, match='VISUAL_REVIEW_BUDGET_EXCEEDED'):
        run(sample)


def test_exhausted_or_corrupt_budget_cannot_create_new_requests(sample, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, '_execute', controlled_model(calls, interrupt_at=1))
    with pytest.raises(RuntimeError):
        run(sample)
    budget = next(sample[2].glob('semantic-pages-budget/**/budget.json'))
    budget.write_text('{}')
    monkeypatch.setattr(provider, '_execute', lambda *_: pytest.fail('budget must block'))
    with pytest.raises(ValueError, match='SEMANTIC_BUDGET_EXCEEDED'):
        run(sample)
    assert len(calls) == 1


def test_process_death_keeps_reserved_budget_and_checked_images(sample, monkeypatch):
    source, evidence, directory = sample
    fixture = directory / 'fixture.json'
    fixture.write_text(json.dumps(evidence))
    code = '''
import json, os, sys
from pathlib import Path
from config.settings import settings
from video_processing.processors import native_caption_router as router
from video_processing.utils import codex_text_provider as provider
settings.native_caption_semantic_paging_enabled = True
settings.codex_text_model = 'gpt-5.6-luna'
provider._execute = lambda *args: os._exit(73)
source, directory = map(Path, sys.argv[1:])
data = json.loads((directory / 'fixture.json').read_text())
router.review(source, data['segments'], data, directory, lambda _: None)
'''
    outcome = subprocess.run([sys.executable, '-c', code, str(source), str(directory)], timeout=15)
    assert outcome.returncode == 73
    state = json.loads(next(directory.glob('semantic-pages-budget/**/budget.json')).read_text())
    assert state['used_seconds'] == state['total_seconds']
    assert list(directory.glob('review-frames-v1/*/frame-*.jpg'))
    monkeypatch.setattr(provider, '_execute', lambda *_: pytest.fail('crash must not refill budget'))
    with pytest.raises(ValueError, match='SEMANTIC_BUDGET_EXCEEDED'):
        run(sample)


def test_regular_and_oversized_segments_keep_order_and_existing_regular_cache(sample, monkeypatch):
    source, evidence, directory = sample
    evidence['segments'] = [dict(start=0., end=.1, text='Start.'),
                            dict(start=.1, end=7.9, text='Middle.'),
                            dict(start=7.9, end=8., text='End.')]
    calls = []
    paged = controlled_model(calls)

    def execute(args, prompt, directory, timeout):
        data = json.loads(prompt.split('\n', 1)[1])
        if isinstance(data, dict):
            return paged(args, prompt, directory, timeout)
        calls.append(dict(data=data))
        payload = dict(reviews=[dict(segment_id=row['segment_id'], decision='COMPLETE',
                                    run_ids=[r['id'] for r in row['rows']],
                                    visual_verified_run_ids=[r['id'] for r in row['rows']], reason='verified')
                               for row in data])
        return _executor(payload=payload)(args, prompt, directory, timeout)

    monkeypatch.setattr(provider, '_execute', execute)
    reviews = run(sample)
    assert [r['segment_id'] for r in reviews] == [0, 1, 2]
    assert ['review_contract' in r for r in reviews] == [False, True, False]
    assert decide(dict(evidence, reviews=reviews))['decision'] == 'PRESERVE'
    count = len(calls)
    assert run(sample) == reviews
    assert len(calls) == count


def test_frames_cache_checks_corruption_and_source_identity_and_lock(sample):
    source, evidence, directory = sample
    metrics = ScanMetrics('TEST')
    with ReviewFrames(source, directory, 80, metrics) as frames:
        path = frames.image(10)
        original = path.read_bytes()
        assert frames.image(10).read_bytes() == original
        with pytest.raises(BlockingIOError):
            with ReviewFrames(source, directory, 80, ScanMetrics('DUPLICATE')):
                pytest.fail('duplicate writer')
        path.write_bytes(b'corrupt')
        assert frames.image(10).read_bytes() == original
    assert metrics.values['image_decodes'] == 2
    assert metrics.values['image_cache_hits'] == 1
    with pytest.raises(ValueError, match='REVIEW_SOURCE_CHANGED'):
        with ReviewFrames(source, directory, 80, metrics) as frames:
            frames.image(10)
            source.write_bytes(source.read_bytes() + b'changed')
    assert not frames.manifest.exists()
    with ReviewFrames(source, directory, 80, metrics) as new_frames:
        assert new_frames.directory != frames.directory


def test_all_pages_preserve_duplicate_text_group_run_ids():
    rows = [dict(id=i, text='字幕', box=[.1, .7, .9, .9]) for i in range(100)]
    groups = group_rows(rows)
    assert [[r['id'] for r in g] for g in groups] == [list(range(100))]
    assert page_groups(groups) == [[0]]

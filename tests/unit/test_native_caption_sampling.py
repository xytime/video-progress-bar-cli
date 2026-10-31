"""抽检正向分流、局部漏检边界、检查点和严格回退的隔离回归。"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from video_processing.utils.caption_sampling_contract import MODE, windows, sample_frames, decide_sampled
from video_processing.utils.source_caption_contract import decide, validate_decision
from video_processing.processors import native_caption_sampling as sampling
from video_processing.processors import native_caption_router as router
from video_processing.processors import burned_caption_repair as repair
from tests.unit.test_native_caption_routing import save_evidence


@pytest.fixture
def evidence():
    segments = [dict(start=i, end=i + 3, text=f'Sentence {i}.') for i in range(0, 120, 3)]
    planned = windows(segments, 30, 3600)
    sampled, reviews = {}, []
    for window in planned:
        frames = sample_frames(window, segments, 30, 3600)
        matches = []
        for frame in frames:
            sampled[frame] = dict(frame=frame, image_sha256='a' * 64,
                rows=[dict(text=f'债券价格{frame // 90}', confidence=.99, box=[.1, .8, .9, .9],
                           raw_box=[.1, .8, .9, .9])])
            matches.append(dict(frame=frame, row_ids=[0]))
        reviews.append(dict(window_id=window['id'], supplemented=False, decision='MATCH',
                            matches=matches, reason='actual image and speech match'))
    return dict(source_sha256='source', inspection_mode=MODE, segments=segments, error='',
                fps=30, frame_count=3600, width=360, height=640, sample_windows=planned,
                samples=[sampled[f] for f in sorted(sampled)], sample_reviews=reviews)


def test_three_windows_use_only_45_frames_and_explicitly_disclaim_full_coverage(evidence):
    assert len(evidence['samples']) == 45
    result = decide(evidence)
    assert result['decision'] == 'PRESERVE'
    assert result['inspection_mode'] == MODE
    assert result['full_timeline_verified'] is False
    assert 'Sentence 60.' in result['review_text']  # 未抽到的对白仍提供完整内容审查正文。


def test_unsampled_gap_is_explicit_accepted_risk_not_fabricated_coverage(evidence):
    assert not any(25 <= s['frame'] / 30 < 45 for s in evidence['samples'])
    # 即便真实字幕在这个未检查区间缺失，合同也只能作抽样结论；不得造 runs。
    assert 'runs' not in evidence
    assert decide(evidence)['full_timeline_verified'] is False


@pytest.mark.parametrize('damage', ['missing_window', 'wrong_window', 'missing_frame', 'extra_frame',
    'missing_review', 'missing_match', 'unknown_row', 'duplicate_row', 'low_confidence', 'nan',
    'english', 'static_title', 'partial', 'uncertain', 'absent', 'not_dialogue', 'missing_image',
    'bad_timeline', 'false_supplement', 'unknown_mode'])
def test_incomplete_or_negative_sample_evidence_never_generates(evidence, damage):
    review, row = evidence['sample_reviews'][0], evidence['samples'][0]['rows'][0]
    if damage == 'missing_window': evidence['sample_windows'].pop()
    if damage == 'wrong_window': evidence['sample_windows'][0]['start'] = 2
    if damage == 'missing_frame': evidence['samples'].pop()
    if damage == 'extra_frame': evidence['samples'].append(dict(evidence['samples'][0], frame=900))
    if damage == 'missing_review': evidence['sample_reviews'].pop()
    if damage == 'missing_match': review['matches'].pop()
    if damage == 'unknown_row': review['matches'][0]['row_ids'] = [99]
    if damage == 'duplicate_row': review['matches'][0]['row_ids'] = [0, 0]
    if damage == 'low_confidence': row['confidence'] = .49
    if damage == 'nan': row['confidence'] = float('nan')
    if damage == 'english': row['text'] = 'English only'
    if damage == 'static_title':
        for sample in evidence['samples']: sample['rows'][0]['text'] = '董事长致辞'
    if damage in {'partial', 'uncertain', 'absent', 'not_dialogue'}: review['decision'] = damage.upper()
    if damage == 'missing_image': evidence['samples'][0]['image_sha256'] = ''
    if damage == 'bad_timeline': evidence['segments'][-1]['end'] = 500
    if damage == 'false_supplement': review['supplemented'] = True
    if damage == 'unknown_mode': evidence['inspection_mode'] = 'invented'
    assert decide(evidence)['decision'] == 'REVIEW'


def test_short_source_merges_windows_and_silence_is_not_negative_evidence():
    segments = [dict(start=5, end=7, text='One'), dict(start=10, end=13, text='Two')]
    planned = windows(segments, 30, 900)
    assert planned == [dict(id=0, start=5, end=13)]
    frames = sample_frames(planned[0], segments, 30, 900)
    assert len(frames) == 5
    assert all(not 7 <= f / 30 < 10 for f in frames)


@pytest.mark.parametrize('captions', ['债券价格上涨', '債券價格上漲', 'Bonds 债券价格上涨'])
def test_simplified_traditional_and_bilingual(evidence, captions):
    for sample in evidence['samples']:
        sample['rows'][0]['text'] = captions + str(sample['frame'] // 90)
    assert decide_sampled(evidence)['decision'] == 'PRESERVE'


def test_sampled_receipt_uses_existing_preserve_and_cannot_fall_back_to_stale_ass(tmp_path, evidence, monkeypatch):
    from video_processing.utils import native_caption_source as native
    from video_processing.utils.render_source_binding import digest
    source = tmp_path / 'demo.mp4'
    source.write_bytes(b'native video')
    output = tmp_path / 'demo_vertical.mp4'
    monkeypatch.setattr(native, 'APPROVALS', tmp_path / 'none.json')
    evidence['source_sha256'] = digest(source)
    save_evidence(output, evidence)
    native.preserve(source, output)
    assert native.validate_preserved(output, source)['inspection_mode'] == MODE
    assert source.read_bytes() == output.read_bytes()
    assert not output.with_suffix('.ass').exists()
    evidence['sample_reviews'][0]['decision'] = 'PARTIAL'
    save_evidence(output, evidence)
    with pytest.raises(ValueError): native.validate_preserved(output, source)


@pytest.mark.parametrize('accepted', [True, False])
def test_route_uses_sample_only_for_positive_and_calls_full_scan_otherwise(tmp_path, evidence, monkeypatch, accepted):
    source, output = tmp_path / 'demo.mp4', tmp_path / 'demo_vertical.mp4'
    source.write_bytes(b'video')
    monkeypatch.setattr(router.settings, 'native_caption_sampling_enabled', True)
    monkeypatch.setattr(sampling, 'attempt', lambda *args: evidence if accepted else None)
    calls = []
    def full(*args):
        calls.append('full')
        raise ValueError('FULL_PATH_SENTINEL')
    monkeypatch.setattr(router, 'scan', full)
    if accepted:
        evidence['source_sha256'] = router.digest(source)
        assert router.route(source, output, evidence['segments']) == 'PRESERVE'
        assert calls == []
    else:
        with pytest.raises(router.NativeCaptionReviewRequired, match='FULL_PATH_SENTINEL'):
            router.route(source, output, evidence['segments'])
        assert calls == ['full']


def test_rollback_does_not_reuse_sample_decision_for_new_routing(tmp_path, evidence, monkeypatch):
    source, output = tmp_path / 'demo.mp4', tmp_path / 'demo_vertical.mp4'
    source.write_bytes(b'video')
    evidence['source_sha256'] = router.digest(source)
    save_evidence(output, evidence)
    monkeypatch.setattr(router.settings, 'native_caption_sampling_enabled', False)
    def full(*args): raise ValueError('FULL_PATH_SENTINEL')
    monkeypatch.setattr(router, 'scan', full)
    with pytest.raises(router.NativeCaptionReviewRequired, match='FULL_PATH_SENTINEL'):
        router.route(source, output, evidence['segments'])


@pytest.mark.parametrize('changed', ['source', 'asr'])
def test_source_or_asr_change_invalidates_sample_decision(tmp_path, evidence, monkeypatch, changed):
    source, output = tmp_path / 'demo.mp4', tmp_path / 'demo_vertical.mp4'
    source.write_bytes(b'video')
    evidence['source_sha256'] = router.digest(source)
    save_evidence(output, evidence)
    if changed == 'source': source.write_bytes(b'changed video')
    else: evidence['segments'][0]['text'] = 'Different sentence.'
    monkeypatch.setattr(router.settings, 'native_caption_sampling_enabled', True)
    calls = []
    def sample(*args):
        calls.append('fresh')
        raise ValueError('FRESH_SAMPLE_REQUIRED')
    monkeypatch.setattr(sampling, 'attempt', sample)
    with pytest.raises(router.NativeCaptionReviewRequired, match='FRESH_SAMPLE_REQUIRED'):
        router.route(source, output, evidence['segments'])
    assert calls == ['fresh']


@pytest.mark.parametrize('code', ['authentication', 'quota', 'unavailable', 'invalid_output'])
def test_sample_provider_failure_is_review_never_generate_or_silent_retry(tmp_path, evidence, monkeypatch, code):
    from video_processing.utils.codex_text_provider import CodexTextError
    source, output = tmp_path / 'demo.mp4', tmp_path / 'demo_vertical.mp4'
    source.write_bytes(b'video')
    monkeypatch.setattr(router.settings, 'native_caption_sampling_enabled', True)
    def failed(*args): raise CodexTextError(code)
    monkeypatch.setattr(sampling, 'attempt', failed)
    def forbidden(*args): raise AssertionError('provider failure must not start full OCR')
    monkeypatch.setattr(router, 'scan', forbidden)
    with pytest.raises(router.NativeCaptionReviewRequired, match=code):
        router.route(source, output, evidence['segments'])
    assert validate_decision(output)['decision'] == 'REVIEW'


class Reader:
    """真实窗口/宿主逻辑下的确定性帧读入边界。"""
    source_samples = {}
    calls = []
    def __init__(self, *args): self.ocr_calls = self.cache_hits = 0
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, frame):
        self.calls.append(frame)
        self.ocr_calls += 1
        return deepcopy(self.source_samples.get(frame, dict(frame=frame, image_sha256='a' * 64,
            rows=[dict(text=f'债券{frame // 90}', confidence=.99, box=[.1,.8,.9,.9])])) )


@pytest.mark.parametrize('response', ['MATCH', 'UNCERTAIN', 'PARTIAL', 'ABSENT', 'NOT_DIALOGUE'])
def test_attempt_supplements_only_uncertain_once(tmp_path, evidence, monkeypatch, response):
    Reader.source_samples = {s['frame']: s for s in evidence['samples']}
    Reader.calls = []
    monkeypatch.setattr(sampling, 'SampleReader', Reader)
    monkeypatch.setattr(repair, '_probe', lambda _: (360, 640, 30., 120.))
    calls = []
    def review(window, samples, *args, supplemented=False):
        calls.append((window['id'], supplemented))
        return dict(window_id=window['id'], supplemented=supplemented,
            decision='MATCH' if supplemented else response, reason='test',
            matches=[dict(frame=s['frame'], row_ids=[0]) for s in samples])
    monkeypatch.setattr(sampling, 'review_window', review)
    result = sampling.attempt(tmp_path / 'source', tmp_path, evidence['segments'], 's', router.normalize_row)
    if response in {'MATCH', 'UNCERTAIN'}:
        assert result and decide(result)['decision'] == 'PRESERVE'
        assert len(Reader.calls) == (63 if response == 'UNCERTAIN' else 45)
        assert len(calls) == (6 if response == 'UNCERTAIN' else 3)
    else:
        assert result is None
        assert calls == [(0, False)]
        assert len(Reader.calls) == 15


def test_no_chinese_goes_to_full_without_semantic_calls(tmp_path, evidence, monkeypatch):
    Reader.source_samples = {s['frame']: dict(s, rows=[]) for s in evidence['samples']}
    Reader.calls = []
    monkeypatch.setattr(sampling, 'SampleReader', Reader)
    monkeypatch.setattr(repair, '_probe', lambda _: (360, 640, 30., 120.))
    def forbidden(*args, **kwargs): raise AssertionError('no positive evidence')
    monkeypatch.setattr(sampling, 'review_window', forbidden)
    assert sampling.attempt(tmp_path / 'source', tmp_path, evidence['segments'], 's', router.normalize_row) is None


@pytest.mark.parametrize('row_id', [0, 1, 2, 3])
def test_semantic_review_uses_explicit_row_ids_and_rejects_wrong_reference(tmp_path, monkeypatch, row_id):
    from video_processing.utils.render_source_binding import digest
    image = tmp_path / 'frame-15.png'
    image.write_bytes(b'actual image transport boundary')
    sample = dict(frame=15, image_sha256=digest(image), rows=[
        dict(text='English', confidence=1), dict(text='低置信度', confidence=.3),
        dict(text='债券价格上涨', confidence=.9)])
    def provider(prompt, **kwargs):
        data = json.loads(prompt.split('\n', 1)[1])
        assert [r['row_id'] for r in data['samples'][0]['rows']] == [0, 1, 2]
        assert [r['eligible'] for r in data['samples'][0]['rows']] == [False, False, True]
        payload = kwargs['validate'](dict(decision='MATCH', reason='test',
            matches=[dict(frame=15, row_ids=[row_id])]))
        return SimpleNamespace(payload=payload, cached=False, duration_ms=1)
    monkeypatch.setattr(sampling, 'run_codex_structured', provider)
    args = (dict(id=0, start=0, end=15), [sample], [dict(start=0, end=15, text='Bonds rose.')], 30, tmp_path)
    if row_id == 2:
        assert sampling.review_window(*args)['decision'] == 'MATCH'
    else:
        with pytest.raises(ValueError): sampling.review_window(*args)


class Capture:
    def __init__(self, _): self.frame = 0
    def set(self, _, frame): self.frame = frame; return True
    def read(self): return True, np.zeros((16, 16, 3), dtype='uint8')
    def get(self, _): return self.frame + 1
    def release(self): pass


def test_real_sample_cache_resumes_and_corruption_recomputes_only_one_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(sampling.cv2, 'VideoCapture', Capture)
    @contextmanager
    def worker(*args): yield object()
    monkeypatch.setattr(sampling, 'file_worker', worker)
    calls = []
    def observe(*args, metrics):
        calls.append(1)
        metrics.values['encode_seconds'] += .1
        metrics.values['vision_seconds'] += .2
        if len(calls) == 2: raise ValueError('OCR_TIMEOUT')
        return dict(rows=[dict(text='中文', confidence=.9, box=[-.01,.8,.9,1.01])])
    monkeypatch.setattr(sampling, 'observe_file', observe)
    with sampling.SampleReader(tmp_path / 'source', tmp_path, router.normalize_row) as reader:
        first = reader.read(15)
        with pytest.raises(ValueError, match='OCR_TIMEOUT'): reader.read(45)
    assert (tmp_path / 'frame-15.json').exists()
    assert not (tmp_path / 'frame-45.json').exists()
    with sampling.SampleReader(tmp_path / 'source', tmp_path, router.normalize_row) as reader:
        assert reader.read(15) == first
        reader.read(45)
        assert reader.cache_hits == 1 and reader.ocr_calls == 1
        assert reader.values == dict(encode_seconds=.1, vision_seconds=.2)
    (tmp_path / 'frame-15.png').write_bytes(b'corrupt')
    with sampling.SampleReader(tmp_path / 'source', tmp_path, router.normalize_row) as reader:
        reader.read(15)
        reader.read(45)
        assert reader.cache_hits == 1 and reader.ocr_calls == 1

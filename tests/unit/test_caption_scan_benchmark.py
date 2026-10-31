"""微样本工具的边界、无损导出和严格等价统计；不运行真实 Vision。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-29 | Codex | 长片全帧相同但性能退化时不得授予整体门禁或生产许可。 |
| 1.0.0 | 2026-10-29 | Codex | 路径/覆盖拒绝、微样本帧像素、清洁环境与完整 runs 判等。 |
"""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


spec = importlib.util.spec_from_file_location('caption_scan_benchmark', Path(__file__).parents[2]/'scripts/benchmark_caption_scan.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


@pytest.mark.parametrize('extra', [[], ['--seconds','1'], ['--seconds','nan'], ['--first-frame','-1'], ['--timeout','0']])
def test_arguments_require_explicit_bounded_work(extra):
    base = [] if not extra else ['--source','/a.mp4','--output','/b']
    with pytest.raises(SystemExit):
        benchmark.arguments(base+extra)
    args = benchmark.arguments(['--source','/a.mp4','--output','/b'])
    assert not args.run_ocr and args.seconds == .5 and benchmark.ROUNDS == 3


def test_explicit_source_and_output_refuse_links_overwrites_and_source_parent(tmp_path):
    inputs = tmp_path/'inputs'
    inputs.mkdir()
    source = inputs/'a.mp4'
    source.write_bytes(b'not-media')
    link = inputs/'link.mp4'
    link.symlink_to(source)
    assert benchmark.explicit_file(str(source)) == source
    for value in ('relative.mp4', str(link)):
        with pytest.raises(ValueError):
            benchmark.explicit_file(value)
    for output in (str(inputs), str(inputs/'acceptance'), str(tmp_path/'output'/'candidate'), 'relative'):
        with pytest.raises(ValueError):
            benchmark.validate_output(output, [source])


def test_clean_environment_does_not_inherit_secrets_or_dispatch_context(tmp_path, monkeypatch):
    monkeypatch.setenv('BENCHMARK_CANARY_SECRET', 'not-a-real-key')
    monkeypatch.setenv('NATIVE_CAPTION_SCAN_OPTIMIZATION_ENABLED', 'true')
    environment = benchmark.child_environment(tmp_path/'runtime', tmp_path)
    assert set(environment) == {'PATH','HOME','PYTHONPATH','PYTHONDONTWRITEBYTECODE','TMPDIR','XDG_CACHE_HOME','LANG','LC_ALL'}
    assert 'BENCHMARK_CANARY_SECRET' not in environment
    assert 'NATIVE_CAPTION_SCAN_OPTIMIZATION_ENABLED' not in environment


def test_lossless_micro_export_preserves_every_pixel_and_never_overwrites(tmp_path):
    frames = [np.random.default_rng(i).integers(0, 256, (64,96,3), dtype=np.uint8) for i in range(4)]
    source = tmp_path/'micro.avi'
    result = benchmark.lossless_clip(iter(frames), source, 10., (96,64))
    assert result['frames'] == 4 and result['fps'] == 10. and result['duration_seconds'] == .4
    assert result['decoded_pixel_sha256'] == [benchmark.frame_hash(frame) for frame in frames]
    before = source.read_bytes()
    # export.log 自身也拒绝复用，尚未进入 FFmpeg 即失败。
    with pytest.raises(FileExistsError):
        benchmark.lossless_clip(iter(frames), source, 10., (96,64))
    assert source.read_bytes() == before


def test_full_runs_equivalence_is_strict_and_never_grants_long_form_gate(tmp_path):
    sample = dict(sample='a', kind='real', frames=4, fps=10., width=96, height=64)
    scan = dict(frame_count=4, fps=10., width=96, height=64,
                runs=[dict(text='债券', first=0, last=4, confidence=.9, box=[.1,.8,.9,.9])])
    runs = []
    for index in range(6):
        directory = tmp_path/str(index)
        directory.mkdir()
        benchmark.write_new(directory/'complete-scan.json', dict(scan, frame_evidence={'extra':index}))
        runs.append(dict(sample='a', mode='baseline' if index%2 == 0 else 'candidate',
                         exit_code=0, scan_wall_seconds=10 if index%2 == 0 else 8, directory=str(directory)))
    report = benchmark.summarize([sample], runs)
    assert report['samples'][0]['full_runs_equal']
    assert report['samples'][0]['candidate_reduction_fraction'] == pytest.approx(.2)
    assert not report['long_form_gate_passed'] and not report['production_enable_allowed']
    path = Path(runs[-1]['directory'])/'complete-scan.json'
    changed = json.loads(path.read_text())
    changed['runs'][0]['confidence'] = .899999
    path.write_text(json.dumps(changed))
    assert not benchmark.summarize([sample], runs)['samples'][0]['full_runs_equal']


def test_gold_only_reports_text_frames_and_does_not_invent_semantic_review():
    sample = dict(gold_text_by_frame=['','中文','',''])
    scan = dict(frame_count=4, runs=[dict(text='中文',first=1,last=2)])
    facts = benchmark.gold_facts(sample, scan)
    assert facts['expected_text_present'] == [True]*4
    assert facts['chinese_frame_presence_equal']
    assert facts['observed_chinese_frames'] == [1]
    assert not facts['semantic_gold']


def test_slow_long_form_equivalence_never_claims_performance_acceptance(tmp_path):
    sample = dict(sample='long', kind='full-source', frames=18000, fps=30.,
                  width=96, height=64, duration_seconds=600.)
    scan = dict(frame_count=18000, fps=30., width=96, height=64, runs=[])
    runs = []
    for index in range(6):
        directory = tmp_path/str(index)
        directory.mkdir()
        benchmark.write_new(directory/'complete-scan.json', scan)
        runs.append(dict(sample='long', mode='baseline' if index%2 == 0 else 'candidate',
                         exit_code=0, scan_wall_seconds=10 if index%2 == 0 else 12,
                         directory=str(directory)))
    report = benchmark.summarize([sample], runs)
    assert report['long_form_full_frame_equivalence_passed']
    assert report['samples'][0]['candidate_reduction_fraction'] < 0
    assert not report['long_form_gate_passed']
    assert not report['production_enable_allowed']


def test_synthetic_gold_refuses_missing_glyphs_before_ocr():
    from PIL import ImageFont
    font = ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc', 42)
    benchmark.validate_gold_glyphs(font, ['價格正在上漲','债券仍然重要','宏观经济王先生'])
    with pytest.raises(ValueError, match='字体缺字'):
        benchmark.validate_gold_glyphs(font, ['\u0378'])


def test_legacy_cache_verifier_copies_only_scans_and_detects_changed_copy(tmp_path):
    cache_spec = importlib.util.spec_from_file_location('native_cache_verifier', Path(__file__).parents[2]/'scripts/verify_native_scan_cache.py')
    verifier = importlib.util.module_from_spec(cache_spec)
    cache_spec.loader.exec_module(verifier)
    source, destination = tmp_path/'old', tmp_path/'new'
    source.mkdir(); destination.mkdir()
    (source/'scan.json').write_text('{"state":"complete"}')
    (source/'partial-scan.json').write_text('{"state":"prefix"}')
    (source/'review.json').write_text('not part of OCR cache acceptance')
    original = {path.name:path.read_bytes() for path in source.iterdir()}
    files = verifier.copy_cache(source, destination)
    assert set(files) == {'scan.json','partial-scan.json'}
    assert verifier.cache_files_unchanged(destination, files)
    (destination/'partial-scan.json').write_text('changed copy')
    assert not verifier.cache_files_unchanged(destination, files)
    assert {path.name:path.read_bytes() for path in source.iterdir()} == original


def test_cache_proof_sandbox_allows_only_selected_source_and_blocks_jxa(tmp_path):
    source = Path('/selected/input.mp4')
    profile = benchmark.sandbox_profile(tmp_path, readable_files=[source], blocked_executables=['/usr/bin/osascript'])
    assert '(deny network*)' in profile and '(deny file-read-data)' in profile
    assert '(allow file-read-data (literal "/selected/input.mp4"))' in profile
    assert '(allow file-read-data (subpath "/selected"))' not in profile
    assert '(deny process-exec (literal "/usr/bin/osascript"))' in profile


def test_native_experiment_requires_explicit_idle_fence_and_never_truncates_it(tmp_path):
    import fcntl
    base = ['--source','/a.mp4','--output','/b','--native-worker','/worker','--run-ocr']
    with pytest.raises(SystemExit):
        benchmark.arguments(base)
    path = tmp_path/'pipeline.lock'
    path.write_text('production lease record')
    args = benchmark.arguments(base+['--pipeline-lock',str(path)])
    with path.open('rb') as production:
        fcntl.flock(production, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='OCR_BENCHMARK_BUSY'):
            with benchmark.native_experiment_lease(args):
                pytest.fail('busy production must prevent any experiment')
    with benchmark.native_experiment_lease(args) as descriptor:
        assert descriptor >= 3
        with path.open('rb') as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert path.read_text() == 'production lease record'


def test_native_experiment_absent_or_plan_only_never_opens_production_lock():
    for enabled, run in [(False,True),(True,False),(False,False)]:
        args = SimpleNamespace(native_worker=enabled, run_ocr=run, pipeline_lock='/not-read/pipeline.lock')
        with benchmark.native_experiment_lease(args) as descriptor:
            assert descriptor is None


def native_profile_fixture(tmp_path, response):
    binary = tmp_path/'native-caption-worker'
    binary.write_bytes(b'explicit experiment binary')
    fence = tmp_path/'pipeline.lock'
    fence.write_text('lease')
    native = SimpleNamespace(FILE_VISION=Path('/original.js'), observe_file=lambda *a, **kw: response)
    config = dict(native_binary=str(binary), native_binary_sha256=benchmark.file_hash(binary), mode='candidate')
    return binary, fence, native, config


def test_native_experiment_rejects_changed_binary_before_changing_backend(tmp_path):
    binary, fence, native, config = native_profile_fixture(tmp_path, {})
    binary.write_bytes(b'changed')
    with pytest.raises(ValueError, match='摘要变化'):
        benchmark.configure_native_experiment(native, config, tmp_path)
    assert native.FILE_VISION == Path('/original.js')


def test_native_experiment_records_only_finite_complete_phase_metrics(tmp_path):
    response = dict(rows=[], worker_contract='vision-native-bmp-experiment-v1', vision_revision=3,
                    worker_metrics=dict(read_seconds=.1,setup_seconds=.2,recognize_seconds=.3,result_seconds=.4))
    binary, fence, native, config = native_profile_fixture(tmp_path, response)
    with fence.open('rb') as lease:
        config['pipeline_lock_fd'] = lease.fileno()
        stat = os.fstat(lease.fileno())
        config['pipeline_lock_identity'] = [stat.st_dev,stat.st_ino]
        profile = benchmark.configure_native_experiment(native, config, tmp_path)
        assert native.FILE_VISION == binary
        assert native.observe_file() is response
        assert native.observe_file() is response
    assert profile == dict(frames=2, revisions=[3], seconds=dict(read_seconds=.2,setup_seconds=.4,
                                                               recognize_seconds=.6,result_seconds=.8))


@pytest.mark.parametrize('change', [dict(worker_metrics={}),dict(worker_contract='other'),
    dict(vision_revision=True), dict(vision_revision=0),
    dict(worker_metrics=dict(read_seconds=float('nan'),setup_seconds=0,recognize_seconds=0,result_seconds=0))])
def test_invalid_native_profile_cannot_be_reported_as_a_valid_scan(tmp_path, change):
    response = dict(rows=[], worker_contract='vision-native-bmp-experiment-v1', vision_revision=3,
                    worker_metrics=dict(read_seconds=.1,setup_seconds=.2,recognize_seconds=.3,result_seconds=.4))
    response.update(change)
    _, fence, native, config = native_profile_fixture(tmp_path, response)
    with fence.open('rb') as lease:
        config['pipeline_lock_fd'] = lease.fileno()
        stat = os.fstat(lease.fileno())
        config['pipeline_lock_identity'] = [stat.st_dev,stat.st_ino]
        profile = benchmark.configure_native_experiment(native, config, tmp_path)
        with pytest.raises(ValueError, match='OCR_NATIVE_PROFILE_INVALID'):
            native.observe_file()
    assert profile['frames'] == 0


def test_native_experiment_rejects_wrong_inherited_fence_before_changing_backend(tmp_path):
    _, fence, native, config = native_profile_fixture(tmp_path, {})
    with fence.open('rb') as lease:
        config['pipeline_lock_fd'] = lease.fileno()
        config['pipeline_lock_identity'] = [0,0]
        with pytest.raises(ValueError, match='fence 身份不符'):
            benchmark.configure_native_experiment(native, config, tmp_path)
    assert native.FILE_VISION == Path('/original.js')


def test_native_profile_wraps_real_router_response_boundary(tmp_path, monkeypatch):
    """经过真实 router.observe/传输/进程；不能把 rows 列表误当原始响应字典。"""
    import sys
    from video_processing.processors import native_caption_router as native
    rows = [dict(text='原字幕',confidence=.9,box=[.1,.8,.9,.9])]
    response = dict(rows=rows, worker_contract='vision-native-bmp-experiment-v1', vision_revision=3,
                    worker_metrics=dict(read_seconds=.1,setup_seconds=.2,recognize_seconds=.3,result_seconds=.4))
    binary, fence, _, config = native_profile_fixture(tmp_path, response)
    binary.write_text(f'#!{sys.executable}\nimport sys,json\n'
        f'response={response!r}\n'
        'for line in sys.stdin:\n'
        ' request=json.loads(line)\n'
        ' if request.get("command")=="STOP": break\n'
        ' print(json.dumps(dict(response,id=request["id"])),flush=True)\n')
    binary.chmod(0o700)
    config['native_binary_sha256'] = benchmark.file_hash(binary)
    for name in ('FILE_VISION','file_worker','observe_file'):
        monkeypatch.setattr(native, name, getattr(native, name))
    with fence.open('rb') as lease:
        config['pipeline_lock_fd'] = lease.fileno()
        stat = os.fstat(lease.fileno())
        config['pipeline_lock_identity'] = [stat.st_dev,stat.st_ino]
        profile = benchmark.configure_native_experiment(native, config, tmp_path)
        with native.file_worker(native.FILE_VISION) as process:
            assert native.observe(process, np.zeros((8,8,3),dtype=np.uint8), timeout=5) == rows
    assert profile['frames'] == 1
    assert profile['seconds']['recognize_seconds'] == .3

"""只读历史 v2 完整扫描，复制后验证优化开启仍零 OCR 命中；不验证字幕语义。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 实际历史缓存副本、实际源摘要、JXA/网络拒绝及未改写收据。 |
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys


spec = importlib.util.spec_from_file_location('caption_benchmark_helpers', Path(__file__).with_name('benchmark_caption_scan.py'))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy_cache(source, destination):
    """连续读取发生改动则拒绝；只复制两个扫描文件，不读语义缓存或图像。"""
    metadata = {}
    for name in ('scan.json','partial-scan.json'):
        path = source/name
        if not path.exists() and name != 'scan.json':
            continue
        benchmark.explicit_file(str(path))
        before = path.stat()
        with path.open('rb') as reader, (destination/name).open('xb') as writer:
            shutil.copyfileobj(reader, writer, length=1024*1024)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('历史扫描缓存复制时发生变化；停止，不自动重试')
        metadata[name] = dict(sha256=digest_file(destination/name), bytes=after.st_size)
    return metadata


def cache_files_unchanged(directory, expected):
    return all((directory/name).is_file() and digest_file(directory/name) == value['sha256']
               for name,value in expected.items())


def worker(config_path):
    config_path = benchmark.explicit_file(config_path)
    config = json.loads(config_path.read_text())
    root, runtime = Path(config['root']), Path(__file__).resolve().parent
    directory, source = config_path.parent, Path(config['source'])
    if (not (root/benchmark.MARKER).is_file() or runtime != root/'runtime' or (runtime/'.env').exists()
            or not directory.is_relative_to(root/'runs') or config['source_sha256'] != digest_file(source)):
        raise ValueError('历史缓存验收身份或隔离根无效')
    sys.path.insert(0, str(runtime/'src'))
    from config.settings import settings
    from video_processing.processors import native_caption_router as native
    from video_processing.utils.stage_events import StageJournal, bind_journal
    settings.native_caption_scan_optimization_enabled = True
    calls = []
    def forbidden(*args, **kwargs):
        calls.append('forbidden')
        raise AssertionError('历史完整缓存不得发起 OCR 或语义请求')
    # 代码 guard 加系统 process-exec 拒绝双层证明：若缓存未命中立即失败。
    native.vision_worker = native.observe = native.run_codex_structured = forbidden
    journal = StageJournal(directory/'metrics.jsonl', task_id=config['sample'], attempt_id='legacy-cache-proof')
    with bind_journal(journal):
        scanned = native.scan(source, directory, lambda _: None)
        journal.close('complete')
    events = [json.loads(line) for line in (directory/'metrics.jsonl').read_text().splitlines()]
    metrics = [event for event in events if event['kind']=='metric' and event['stage']=='OCR_NATIVE']
    unchanged = cache_files_unchanged(directory, config['cache_files'])
    success = (not calls and unchanged and not (directory/'native-scan-v3-exact').exists()
               and len(metrics)==1 and metrics[0]['cache_hit'] is True and metrics[0]['ocr_calls']==0
               and metrics[0]['frames']==scanned['frame_count'] and 'frame_evidence' not in scanned)
    benchmark.write_new(directory/'scan-receipt.json', dict(cache_reuse_verified=success,
        frame_count=scanned['frame_count'], metrics=metrics, actual_ocr_calls=0, jxa_execution_allowed=False,
        network_allowed=False, copied_cache_unchanged=unchanged, candidate_optimization_enabled=True,
        partial_copied_but_not_consumed='partial-scan.json' in config['cache_files'],
        semantic_review_performed=False, quality_or_publication_permission_proven=False))
    if not success:
        raise ValueError('历史完整 v2 cache 未通过零 OCR 命中及未改写检查')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', action='append', default=[])
    parser.add_argument('--cache-root')
    parser.add_argument('--output')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--worker-config', help=argparse.SUPPRESS)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.worker_config:
        worker(args.worker_config)
        return 0
    if not args.source or not args.cache_root or not args.output or args.timeout <= 0:
        parser.error('必须显式 source（可重复）、cache-root、全新 output 及正 timeout')
    if sys.prefix == sys.base_prefix or sys.platform != 'darwin':
        raise ValueError('必须使用 macOS 项目 venv Python')
    sources = [benchmark.explicit_file(value) for value in args.source]
    if len(sources) != len(set(sources)) or len({s.stem for s in sources}) != len(sources):
        raise ValueError('源路径/stem 必须唯一')
    cache_root = Path(args.cache_root)
    if not cache_root.is_absolute() or not cache_root.is_dir() or cache_root.resolve() != cache_root:
        raise ValueError('cache-root 必须是无链接的显式绝对目录')
    root = benchmark.validate_output(args.output, sources)
    if root.is_relative_to(cache_root):
        raise ValueError('验收根不得位于历史缓存中')
    root.mkdir()
    for name in ('runs','tmp','cache','home'):
        (root/name).mkdir()
    benchmark.write_new(root/benchmark.MARKER, dict(schema=1, mode='legacy-cache-proof', actual_ocr_allowed=False))
    runtime, _ = benchmark.runtime_snapshot(root)
    script = runtime/'verify_native_scan_cache.py'
    shutil.copy2(Path(__file__).resolve(), script)
    benchmark.write_new(root/'verification-tool-sha256.json', dict(sha256=digest_file(script)))
    (root/'ocr.sb').write_text(benchmark.sandbox_profile(root, readable_files=sources,
                                                        blocked_executables=['/usr/bin/osascript']))
    results = []
    for source in sources:
        digest = digest_file(source)
        directory = root/'runs'/source.stem
        directory.mkdir()
        files = copy_cache(cache_root/digest, directory)
        config = directory/'config.json'
        benchmark.write_new(config, dict(root=str(root), source=str(source), source_sha256=digest,
            sample=source.stem, source_cache=str(cache_root/digest), cache_files=files))
        result = dict(benchmark.run_worker(script, runtime, root, config, args.timeout), sample=source.stem,
                      source_sha256=digest, directory=str(directory), cache_files=files)
        benchmark.write_new(directory/'resource-receipt.json', result)
        results.append(result)
        print(json.dumps({k:result.get(k) for k in ('sample','exit_code','cache_reuse_verified','frame_count')}, ensure_ascii=False), flush=True)
        if result['exit_code'] != 0:
            benchmark.write_new(root/'failed-run.json', result)
            return 2
    benchmark.write_new(root/'summary.json', dict(samples=results, all_legacy_complete_cache_reused=all(
        result['cache_reuse_verified'] for result in results), actual_ocr_calls=0,
        production_cache_written=False, partial_resume_proven=False, semantic_review_performed=False,
        quality_or_publication_permission_proven=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""显式本地小样的单 worker OCR A/B；不调用语义模型或发布入口。

源片只解码指定的最多 0.5 秒，FFV1 小样逐帧与输入解码像素对照。每轮冷应用缓存，
系统缓存不清理。真实样本不是完整长片验收；合成 gold 仅指文字及出现帧的事实。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.1 | 2026-10-29 | Codex | 将长片全帧等价与整体门禁分开，避免相同但更慢的结果被标成性能验收通过。 |
| 1.1.0 | 2026-10-29 | Codex | 显式完整原片模式，以逐字节副本及逐帧摘要补齐长片对照，不扩大默认微样本范围。 |
| 1.0.0 | 2026-10-29 | Codex | 无密钥源码副本、无损小样、三轮交错扫描及资源/等价收据。 |
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from fractions import Fraction
from functools import partial
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import time


MARKER = '.caption-benchmark.json'
MAX_SECONDS = .5
ROUNDS = 3


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def explicit_file(value):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('源文件必须是无符号链接的绝对普通文件路径')
    return path


def validate_output(value, sources):
    path = Path(value)
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError('输出必须是显式、尚不存在的绝对目录；不会覆盖或复用')
    if not path.parent.is_dir() or path.parent.resolve() != path.parent:
        raise ValueError('输出父目录必须已存在且无符号链接')
    volume = Path('/Volumes/EXT2T')
    if not volume.is_mount() or not path.is_relative_to(volume):
        raise ValueError('验收输出仅允许已挂载 EXT2T，不回退主盘')
    repository = Path(__file__).resolve().parents[1]
    if path.is_relative_to(repository) or any(path.is_relative_to(s.parent) for s in sources):
        raise ValueError('输出不能位于源码或任一源片所在目录内')
    # 明确拒绝任何项目的生产 output 目录，允许单独验收根。
    if 'output' in path.parts:
        raise ValueError('验收目录不得在生产 output 树内')
    return path


def frame_hash(frame):
    return hashlib.sha256(memoryview(frame)).hexdigest()


def lossless_clip(frames, target, fps, size):
    """写 BGR 原始帧到 FFV1，再按帧摘要回读；没有缩放、ROI 或抽帧。"""
    import cv2
    import imageio_ffmpeg
    width, height = size
    rate = str(Fraction(fps).limit_denominator(100000))
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-n', '-f', 'rawvideo',
               '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', rate, '-i', 'pipe:0',
               '-an', '-c:v', 'ffv1', '-level', '3', '-pix_fmt', 'bgr0', str(target)]
    hashes = []
    with (target.parent/(target.stem+'-export.log')).open('x') as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            for frame in frames:
                if frame.shape != (height, width, 3) or str(frame.dtype) != 'uint8':
                    raise ValueError('源片完整帧形状不一致')
                hashes.append(frame_hash(frame))
                process.stdin.write(memoryview(frame))
            process.stdin.close()
            if process.wait(timeout=60) != 0 or not hashes:
                raise ValueError('无损导出失败或没有帧')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    capture = cv2.VideoCapture(str(target))
    actual = []
    try:
        if (abs(capture.get(cv2.CAP_PROP_FPS)-fps) > .001
                or (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))) != size):
            raise ValueError('无损小样分辨率或帧率改变')
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            actual.append(frame_hash(frame))
    finally:
        capture.release()
    if hashes != actual:
        raise ValueError('无损小样逐帧像素不等价')
    return dict(frames=len(hashes), fps=fps, width=width, height=height,
                duration_seconds=len(hashes)/fps, decoded_pixel_sha256=hashes,
                clip_sha256=hashlib.sha256(target.read_bytes()).hexdigest())


def file_hash(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def full_source_sample(source, target):
    """原片逐字节副本，不转码、不缩放；完整解码建立逐帧摘要。"""
    import cv2
    before = file_hash(source)
    stat = source.stat()
    shutil.copyfile(source, target)
    if file_hash(target) != before or file_hash(source) != before:
        raise ValueError('原片复制期间变化')
    capture = cv2.VideoCapture(str(target))
    fps = capture.get(cv2.CAP_PROP_FPS)
    width, height = (int(capture.get(key)) for key in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
    expected = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    hashes = []
    try:
        if not capture.isOpened() or not math.isfinite(fps) or fps <= 0 or min(width,height) <= 0:
            raise ValueError('完整原片不可读')
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame.shape != (height,width,3) or str(frame.dtype) != 'uint8':
                raise ValueError('完整原片像素格式变化')
            hashes.append(frame_hash(frame))
    finally:
        capture.release()
    if len(hashes) != expected or file_hash(source) != before:
        raise ValueError('完整原片帧数或源摘要变化')
    return dict(frames=expected, fps=fps, width=width, height=height, duration_seconds=expected/fps,
                decoded_pixel_sha256=hashes, clip_sha256=before, source_sha256=before,
                source=str(source), source_size=stat.st_size, source_mtime_ns=stat.st_mtime_ns,
                first_frame=0, source_full_hash_performed=True, kind='full-source')


def extract_sample(source, target, seconds, first_frame):
    import cv2
    ffprobe = next((str(p) for p in (Path('/opt/homebrew/bin/ffprobe'), Path('/usr/local/bin/ffprobe')) if p.is_file()), None)
    if ffprobe is None:
        raise ValueError('缺少显式本机 ffprobe，不能确认源片恒定帧率')
    probe = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams',
                            '-of', 'json', str(source)], capture_output=True, text=True, check=True, timeout=30)
    stream = json.loads(probe.stdout)['streams'][0]
    original_fps = float(Fraction(stream['avg_frame_rate']))
    if (original_fps <= 0 or abs(original_fps-float(Fraction(stream['r_frame_rate']))) > .001
            or abs(float(stream.get('start_time', 0))) > .001
            or any(item.get('rotation', 0) for item in stream.get('side_data_list', []))):
        raise ValueError('微样本只接受零起点、无旋转、可确认恒定帧率源，不重设源时间轴')
    capture = cv2.VideoCapture(str(source))
    fps = capture.get(cv2.CAP_PROP_FPS)
    size = (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    if (not capture.isOpened() or not math.isfinite(fps) or fps <= 0 or min(size) <= 0
            or abs(fps-original_fps) > .001 or size != (stream['width'], stream['height'])):
        capture.release()
        raise ValueError('源片元数据无效')
    count = max(1, math.floor(seconds*fps + 1e-9))
    try:
        if first_frame and (not capture.set(cv2.CAP_PROP_POS_FRAMES, first_frame)
                            or abs(capture.get(cv2.CAP_PROP_POS_FRAMES)-first_frame) > .01):
            raise ValueError('不能确认小样起始帧位置')
        def frames():
            for _ in range(count):
                ok, frame = capture.read()
                if not ok:
                    raise ValueError('源片指定短段提前结束')
                yield frame
        result = lossless_clip(frames(), target, fps, size)
    finally:
        capture.release()
    stat = source.stat()
    return dict(result, source=str(source), source_size=stat.st_size, source_mtime_ns=stat.st_mtime_ns,
                first_frame=first_frame, source_full_hash_performed=False, kind='real')


def synthetic_samples(directory, font):
    """人为定义文字 gold，不能据此断言 ASR 对齐或 COMPLETE/ABSENT 语义结论。"""
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    if not font:
        font = '/System/Library/Fonts/STHeiti Medium.ttc'
    font = explicit_file(font)
    face = ImageFont.truetype(str(font), 42)
    cases = [
        ('simplified', ['债券仍然重要']*4, .78),
        ('traditional', ['價格正在上漲']*4, .78),
        ('bilingual', ['债券仍然重要\nBonds still matter']*4, .72),
        ('partial', ['债券仍然重要']*2+['']*2, .78),
        ('no_chinese', ['Bonds still matter']*4, .78),
        ('single_frame', ['', '债券仍然重要', '', ''], .78),
        ('title_nameplate', ['宏观经济\n王先生']*4, .08),
    ]
    validate_gold_glyphs(face, [text for _,texts,_ in cases for text in texts])
    samples = []
    for name, texts, top in cases:
        def frames():
            for text in texts:
                image = Image.new('RGB', (720, 1280), (28, 34, 42))
                ImageDraw.Draw(image).multiline_text((60, int(1280*top)), text, font=face,
                                                      fill=(255,255,255), spacing=14)
                yield cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        target = directory/f'gold-{name}.avi'
        result = lossless_clip(frames(), target, 10., (720,1280))
        samples.append(dict(result, clip=str(target), sample=name, kind='synthetic',
                            gold_text_by_frame=texts, gold_region_top=top, font=str(font), glyphs_verified=True,
                            semantic_gold=False))
    return samples


def validate_gold_glyphs(font, texts):
    """TTC 默认子字体可能仅含简体；空字形不能作为已绘制文字的 gold。"""
    missing = font.getmask('\u0378')
    missing_key = (missing.size, bytes(missing))
    for char in set(''.join(texts)):
        if char.isspace():
            continue
        mask = font.getmask(char)
        if not mask.size[0] or not mask.size[1] or (mask.size, bytes(mask)) == missing_key:
            raise ValueError(f'合成 gold 字体缺字 U+{ord(char):04X}；拒绝生成无效标注')


def runtime_snapshot(root):
    """仅复制受维护 src；无 .env、输出、用户配置或业务凭据。"""
    repository = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('caption_benchmark_isolation', repository/'scripts/run_isolated_tests.py')
    isolation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolation)
    runtime = root/'runtime'
    runtime.mkdir()
    manifest = {}
    for relative in isolation.source_files(repository):
        if relative.parts[0] != 'src':
            continue
        target = runtime/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (repository/relative).read_bytes()
        target.write_bytes(data)
        manifest[str(relative)] = hashlib.sha256(data).hexdigest()
    script = runtime/'benchmark_caption_scan.py'
    shutil.copy2(Path(__file__).resolve(), script)
    manifest['benchmark_caption_scan.py'] = hashlib.sha256(script.read_bytes()).hexdigest()
    write_new(root/'source-manifest.json', manifest)
    return runtime, script


def child_environment(runtime, root):
    # 构造显式环境；不读取/继承运行环境中的秘密、代理或业务 feature flags。
    return dict(PATH=f'{sys.prefix}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                HOME=str(root/'home'), PYTHONPATH=str(runtime/'src'), PYTHONDONTWRITEBYTECODE='1',
                TMPDIR=str(root/'tmp'), XDG_CACHE_HOME=str(root/'cache'), LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8')


def global_swap():
    result = subprocess.run(['/usr/bin/vm_stat'], capture_output=True, text=True, check=True)
    lines = result.stdout.splitlines()
    values = {line.split(':')[0]: int(line.split(':')[1].strip().rstrip('.'))
              for line in lines[1:] if ':' in line and line.split(':')[1].strip().rstrip('.').isdigit()}
    return dict(swapins_pages=values.get('Swapins'), swapouts_pages=values.get('Swapouts'))


def tree_rss(pid):
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,rss='], capture_output=True, text=True, check=True)
    rows = [tuple(map(int, line.split())) for line in result.stdout.splitlines() if len(line.split()) == 3]
    descendants = {pid}
    while True:
        enlarged = descendants | {child for child, parent, _ in rows if parent in descendants}
        if enlarged == descendants:
            break
        descendants = enlarged
    return sum(rss for child, _, rss in rows if child in descendants) * 1024


def sandbox_profile(root, *, readable_files=(), blocked_executables=()):
    # Vision 的系统 IPC 保持可用；子进程不能联网或写到本次验收根之外。
    readable = [root, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    readable += [Path(value) for value in (
        '/System/Library', '/System/Volumes/Preboot/Cryptexes/OS', '/usr', '/bin', '/sbin',
        '/opt/homebrew', '/Library/Apple', '/Library/Fonts', '/Library/Frameworks',
        '/Library/Developer', '/private/etc', '/private/var/db', '/dev')]
    rules = ['(version 1)', '(allow default)', '(deny network*)', '(deny file-read-data)', '(deny file-write*)']
    rules += [f'(allow file-read-data (subpath {json.dumps(str(path))}))' for path in readable]
    rules += [f'(allow file-read-data (literal {json.dumps(str(path))}))' for path in readable_files]
    rules += [f'(deny process-exec (literal {json.dumps(str(path))}))' for path in blocked_executables]
    rules += ['(allow file-read-data (literal "/"))',
              f'(allow file-write* (subpath {json.dumps(str(root))}) (literal "/dev/null"))']
    return '\n'.join(rules)+'\n'


def run_worker(script, runtime, root, config, timeout, *, pass_fds=()):
    profile = root/'ocr.sb'
    if not profile.exists():
        profile.write_text(sandbox_profile(root))
    command = ['/usr/bin/sandbox-exec', '-f', str(profile), sys.executable, str(script),
               '--worker-config', str(config)]
    directory = config.parent
    before, started, peak, samples = global_swap(), time.monotonic(), 0, 0
    with (directory/'worker.log').open('x') as log:
        process = subprocess.Popen(command, cwd=runtime, env=child_environment(runtime, root),
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                   pass_fds=pass_fds)
        try:
            while process.poll() is None:
                peak, samples = max(peak, tree_rss(process.pid)), samples+1
                if time.monotonic()-started > timeout:
                    raise TimeoutError('本轮 OCR 达到显式墙钟上限')
                time.sleep(.1)
        finally:
            if process.poll() is None:
                # 只处理本工具创建的新进程组。
                import os
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    after = global_swap()
    result = dict(exit_code=process.returncode, process_wall_seconds=time.monotonic()-started,
                  sampled_peak_tree_rss_bytes=peak, resource_samples=samples, sample_interval_seconds=.1,
                  rss_note='同时采样本轮 Python 与后代 RSS 之和；共享页可能重复，短峰值可能漏采',
                  global_swap_before=before, global_swap_after=after,
                  swap_note='整机计数，生产并发会混杂；短段不能证明长片无持续 swap')
    receipt = directory/'scan-receipt.json'
    if receipt.exists():
        result.update(json.loads(receipt.read_text()))
    return result


@contextmanager
def native_experiment_lease(args):
    """原生实验必须占用既有全局 fence；只读打开、非阻塞，不改锁文件内容。

    文件描述符传给基准 Python 和两种 OCR 后端；父进程退出也不能提前放行生产。
    没有空闲就立即拒绝，不在维护窗口外排队或抢占正在运行的扫描。
    """
    if not args.native_worker or not args.run_ocr:
        yield None
        return
    path = explicit_file(args.pipeline_lock)
    if path.name != 'pipeline.lock':
        raise ValueError('原生实验必须使用目标生产 output/pipeline.lock')
    with path.open('rb') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('OCR_BENCHMARK_BUSY: 生产流水线未空闲，未启动实验 OCR') from exc
        yield lease.fileno()


def configure_native_experiment(native, config, runtime):
    """仅隔离子进程替换后端；二进制摘要进入扫描身份，拒绝跨后端检查点复用。"""
    binary = explicit_file(config['native_binary'])
    if binary != runtime/'native-caption-worker' or file_hash(binary) != config['native_binary_sha256']:
        raise ValueError('原生实验二进制不在快照内或摘要变化')
    descriptor = config['pipeline_lock_fd']
    if type(descriptor) is not int or descriptor < 3:
        raise ValueError('原生实验缺少继承的生产 fence')
    stat = os.fstat(descriptor)  # 未继承、串 FD 或已经关闭时拒绝执行。
    if config.get('pipeline_lock_identity') != [stat.st_dev, stat.st_ino]:
        raise ValueError('原生实验继承的生产 fence 身份不符')
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    from video_processing.utils.caption_vision_transport import binary_file_worker, file_worker
    native.file_worker = partial(file_worker, pass_fds=(descriptor,))
    profile = dict(frames=0, seconds={}, revisions=[])
    if config['mode'] == 'candidate':
        native.FILE_VISION = binary
        native.file_worker = partial(binary_file_worker, pass_fds=(descriptor,))
        original_observe = native.observe_file

        def observe(*args, **kwargs):
            result = original_observe(*args, **kwargs)
            measured = result.get('worker_metrics')
            keys = {'read_seconds','setup_seconds','recognize_seconds','result_seconds'}
            revision = result.get('vision_revision')
            if (result.get('worker_contract') != 'vision-native-bmp-experiment-v1'
                    or type(revision) is not int or revision < 1
                    or not isinstance(measured, dict) or set(measured) != keys
                    or any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 for v in measured.values())):
                raise ValueError('OCR_NATIVE_PROFILE_INVALID')
            profile['frames'] += 1
            for key, value in measured.items():
                profile['seconds'][key] = profile['seconds'].get(key, 0) + value
            if revision not in profile['revisions']:
                profile['revisions'].append(revision)
            if len(profile['revisions']) != 1:
                raise ValueError('OCR_NATIVE_REVISION_CHANGED')
            return result

        native.observe_file = observe
    return profile


def worker(config_path):
    config_path = explicit_file(config_path)
    config = json.loads(config_path.read_text())
    root, runtime = Path(config['root']), Path(__file__).resolve().parent
    source, directory = Path(config['clip']), config_path.parent
    if (not (root/MARKER).is_file() or runtime != root/'runtime' or (runtime/'.env').exists()
            or not directory.is_relative_to(root/'runs') or not source.is_relative_to(root/'clips')):
        raise ValueError('子进程必须使用本工具创建的独立小样、源码与输出')
    sys.path.insert(0, str(runtime/'src'))
    from config.settings import settings
    from video_processing.processors import native_caption_router as native
    from video_processing.utils.stage_events import StageJournal, bind_journal
    settings.native_caption_scan_optimization_enabled = bool(config.get('native_binary')) or config['mode'] == 'candidate'
    settings.caption_scan_png_compression = config['png_compression']
    native_profile = configure_native_experiment(native, config, runtime) if config.get('native_binary') else None
    journal = StageJournal(directory/'metrics.jsonl', task_id=config['sample'], attempt_id=directory.name)
    started = time.monotonic()
    with bind_journal(journal):
        scanned = native.scan(source, directory, lambda _: None)
        journal.close('complete')
    write_new(directory/'complete-scan.json', scanned)
    events = [json.loads(line) for line in (directory/'metrics.jsonl').read_text().splitlines()]
    metrics = [event for event in events if event['kind'] == 'metric' and event['stage'] == 'OCR_NATIVE']
    write_new(directory/'scan-receipt.json', dict(scan_wall_seconds=time.monotonic()-started,
        metrics=metrics, worker_count=1, semantic_review_performed=False, native_profile=native_profile,
        self_maxrss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        child_maxrss=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        maxrss_unit='bytes on macOS; child value is maximum process, not aggregate tree'))


def core_scan(scanned):
    return {key: scanned[key] for key in ('frame_count', 'fps', 'width', 'height', 'runs')}


def gold_facts(sample, scanned):
    texts = ['\n'.join(run['text'] for run in scanned['runs'] if run['first'] <= i < run['last'])
             for i in range(scanned['frame_count'])]
    compact = lambda text: ''.join(c for c in text if c.isalnum()).lower()
    expected = sample['gold_text_by_frame']
    return dict(expected_text_by_frame=expected, observed_text_by_frame=texts,
                expected_text_present=[compact(a) in compact(b) for a,b in zip(expected,texts)],
                expected_chinese_frames=[i for i,t in enumerate(expected) if any('\u3400' <= c <= '\u9fff' for c in t)],
                observed_chinese_frames=[i for i,t in enumerate(texts) if any('\u3400' <= c <= '\u9fff' for c in t)],
                chinese_frame_presence_equal=([i for i,t in enumerate(expected) if any('\u3400' <= c <= '\u9fff' for c in t)] ==
                                              [i for i,t in enumerate(texts) if any('\u3400' <= c <= '\u9fff' for c in t)]),
                semantic_gold=False)


def summarize(samples, runs, *, rounds=ROUNDS):
    summaries = []
    for sample in samples:
        selected = [r for r in runs if r['sample'] == sample['sample']]
        successful = len(selected) == rounds*2 and all(r['exit_code'] == 0 for r in selected)
        scans = [json.loads(Path(r['directory'], 'complete-scan.json').read_text()) for r in selected if r['exit_code'] == 0]
        timeline_complete = successful and all(s['frame_count'] == sample['frames'] and
            abs(s['fps']-sample['fps']) <= .001 and s['width'] == sample['width'] and s['height'] == sample['height'] for s in scans)
        equivalent = timeline_complete and all(core_scan(s) == core_scan(scans[0]) for s in scans)
        medians = {mode: statistics.median(r['scan_wall_seconds'] for r in selected
                                         if r['mode'] == mode and r['exit_code'] == 0)
                   for mode in ('baseline','candidate') if any(r['mode'] == mode and r['exit_code'] == 0 for r in selected)}
        item = dict(sample=sample['sample'], successful=successful, timeline_complete=timeline_complete,
                    full_runs_equal=equivalent, median_seconds=medians)
        if len(medians) == 2:
            item['candidate_reduction_fraction'] = 1-medians['candidate']/medians['baseline']
        if sample['kind'] == 'synthetic' and scans:
            item['gold_facts'] = gold_facts(sample, scans[0])
        summaries.append(item)
    long_form = any(s['kind'] == 'full-source' and s['duration_seconds'] >= 600 for s in samples)
    return dict(samples=summaries, long_form_gate_passed=False,
                long_form_full_frame_equivalence_passed=(long_form and rounds == ROUNDS
                    and all(x['full_runs_equal'] for x in summaries)), production_enable_allowed=False,
                limitation='完整长片仅证明OCR全帧等价；语义 gold、真实翻译及成片吞吐仍独立验收；开关须继续关闭')


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--full-source', action='store_true', help='显式执行完整原片副本，保留全部帧；可能耗时数小时')
    parser.add_argument('--source', action='append', default=[], help='显式源文件绝对路径，可重复')
    parser.add_argument('--output', help='EXT2T 上尚不存在的独立验收目录')
    parser.add_argument('--seconds', type=float, default=.5)
    parser.add_argument('--first-frame', type=int, default=0)
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--font', help='合成 gold 字体绝对路径；默认系统 STHeiti Medium，生成前逐字验证')
    parser.add_argument('--run-ocr', action='store_true', help='显式执行三轮单 worker A/B；默认只准备小样与成本')
    parser.add_argument('--probe-only', action='store_true', help='仅单源一对A/B检查Vision/沙盒兼容；不构成三轮验收')
    parser.add_argument('--timeout', type=int, default=180, help='每轮 OCR 进程墙钟上限秒')
    parser.add_argument('--png-compression', type=int, choices=range(10), default=3)
    parser.add_argument('--native-worker', help='显式已编译原生实验二进制；对照改为 BMP/JXA vs BMP/原生，不进入生产')
    parser.add_argument('--pipeline-lock', help='原生 OCR 实验必需：目标生产现有 output/pipeline.lock；忙则退出')
    parser.add_argument('--worker-config', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker_config:
        return args
    if (not args.output or not (args.source or args.synthetic) or not math.isfinite(args.seconds)
            or not 0 < args.seconds <= MAX_SECONDS or args.first_frame < 0 or args.timeout <= 0):
        parser.error('需要显式 source 或 synthetic、output；seconds 必须在 (0,0.5]、first-frame 非负、timeout 为正')
    if args.full_source and (args.first_frame or args.synthetic or args.probe_only):
        parser.error('full-source 不接受起始偏移、synthetic 或 probe-only')
    if args.probe_only and (len(args.source) != 1 or args.synthetic or not args.run_ocr):
        parser.error('probe-only 必须恰好一个显式source、run-ocr，不能混合synthetic')
    if args.native_worker and args.run_ocr and not args.pipeline_lock:
        parser.error('原生 OCR 实验必须显式指定生产 pipeline-lock；不允许并行争抢资源')
    if args.pipeline_lock and not args.native_worker:
        parser.error('pipeline-lock 只用于显式原生实验')
    return args


def main(argv=None):
    args = arguments(sys.argv[1:] if argv is None else argv)
    if args.worker_config:
        worker(args.worker_config)
        return 0
    with native_experiment_lease(args) as lock_fd:
        return benchmark_main(args, lock_fd)


def benchmark_main(args, lock_fd=None):
    if sys.prefix == sys.base_prefix or sys.platform != 'darwin':
        raise ValueError('必须使用 macOS 项目 venv Python')
    sources = [explicit_file(value) for value in args.source]
    binary = explicit_file(args.native_worker) if args.native_worker else None
    if binary and not os.access(binary, os.X_OK):
        raise ValueError('原生 worker 必须已经编译并可执行；基准不运行编译器')
    if len(sources) != len(set(sources)) or len({s.stem for s in sources}) != len(sources):
        raise ValueError('源片路径及文件名 stem 必须唯一')
    root = validate_output(args.output, sources)
    root.mkdir()
    for name in ('clips','runs','tmp','cache','home'):
        (root/name).mkdir()
    write_new(root/MARKER, dict(schema=1, created_at=datetime.now(timezone.utc).isoformat(),
                              worker_count=1, semantic_review_performed=False))
    samples = []
    for source in sources:
        target = root/'clips'/(source.name if args.full_source else f'{source.stem}.avi')
        sample = full_source_sample(source, target) if args.full_source else extract_sample(source, target, args.seconds, args.first_frame)
        samples.append(dict(sample, clip=str(target), sample=source.stem))
    if args.synthetic:
        samples.extend(synthetic_samples(root/'clips', args.font))
    rounds = 1 if args.probe_only else ROUNDS
    total = sum(sample['frames'] for sample in samples)*rounds*2
    plan = dict(samples=samples, rounds=rounds, probe_only=args.probe_only,
                comparison='bmp-jxa-vs-native' if binary else 'png-jxa-vs-bmp-jxa',
                order=['baseline,candidate','candidate,baseline','baseline,candidate'][:rounds],
                planned_frame_visits=total, ocr_calls_no_retry_upper_bound=total, ocr_calls_upper_bound=total*2,
                estimated_ocr_seconds_at_3_to_8_fps=[total/8,total/3],
                cost_note='仅按历史吞吐估算，另加进程启动/编码/IO；没有任何收益倍数承诺', run_ocr=args.run_ocr)
    write_new(root/'plan.json', plan)
    print(json.dumps(dict(output=str(root), **{k:v for k,v in plan.items() if k != 'samples'}), ensure_ascii=False))
    if not args.run_ocr:
        return 0
    runtime, script = runtime_snapshot(root)
    native_config = {}
    if binary:
        expected = file_hash(binary)
        target = runtime/'native-caption-worker'
        shutil.copyfile(binary, target)
        target.chmod(0o500)
        if file_hash(target) != expected or file_hash(binary) != expected:
            raise ValueError('原生 worker 复制期间变化')
        native_config = dict(native_binary=str(target), native_binary_sha256=expected,
                             pipeline_lock_fd=lock_fd,
                             pipeline_lock_identity=[os.fstat(lock_fd).st_dev, os.fstat(lock_fd).st_ino])
        write_new(root/'native-artifact.json', dict(source=str(binary), sha256=expected,
                  production_enable_allowed=False, comparison='bmp-jxa-vs-native'))
    runs = []
    for sample in samples:
        for index in range(rounds):
            modes = ('baseline','candidate') if index % 2 == 0 else ('candidate','baseline')
            for mode in modes:
                directory = root/'runs'/f'{sample["sample"]}-{index+1}-{mode}'
                directory.mkdir()
                config = directory/'config.json'
                write_new(config, dict(root=str(root), clip=sample['clip'], mode=mode,
                                       sample=sample['sample'], png_compression=args.png_compression, **native_config))
                result = dict(run_worker(script, runtime, root, config, args.timeout,
                              pass_fds=(lock_fd,) if lock_fd is not None else ()), sample=sample['sample'],
                              mode=mode, round=index+1, directory=str(directory))
                write_new(directory/'resource-receipt.json', result)
                runs.append(result)
                print(json.dumps({k:v for k,v in result.items() if k in ('sample','mode','round','exit_code','scan_wall_seconds')}, ensure_ascii=False), flush=True)
                if result['exit_code'] != 0:
                    write_new(root/'failed-run.json', result)
                    return 2  # 不自动重试未知失败。
    write_new(root/'runs.json', runs)
    report = summarize(samples, runs, rounds=rounds)
    report.update(probe_only=args.probe_only, rounds=rounds)
    write_new(root/'summary.json', report)
    return 0 if all(item['full_runs_equal'] for item in report['samples']) else 3


if __name__ == '__main__':
    raise SystemExit(main())

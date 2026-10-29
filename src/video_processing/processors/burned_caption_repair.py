"""竖屏硬字幕的逐帧定位、字形修补与原位排版凭证。

A 优先局部修补；可靠定位但外观或质量不合格时，整片从原片评估 B，无法安全排版则停止。
Vision 是本机逐帧识别；修补只改字形掩膜，不能保证恢复被遮挡的真实背景。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.4.0 | 2026-10-29 | Codex | 默认关闭的完整帧同像素复用、独立分块断点与扫描计时。 |
| 2.3.1 | 2026-10-28 | Codex | 允许位于画面内的全宽对白字幕，仍按实际掩膜面积与纹理决定修补或避让。 |
| 2.3.0 | 2026-10-23 | Codex | 单片已确认独立字幕区绑定原片、完整时间轴、版式和实现凭证。 |
| 2.2.0 | 2026-10-23 | Codex | 对齐百分比与数字写法；用双向 ASR 轨迹区分字幕、孤帧 OCR 错误与画面文字。 |
| 2.1.0 | 2026-10-23 | Codex | 相邻帧合框证据确认同基线拆出的单字形，保留未知文字阻断。 |
| 2.0.0 | 2026-10-21 | Codex | A/B 全片决策、原片回退、逐帧人脸避让及有来源摘要的 OCR 缓存。 |
| 1.0.0 | 2026-10-21 | Codex | A 方案接入：逐帧识别与保守修补、完整画面、来源及成片摘要门禁。 |
"""
from __future__ import annotations

import base64
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import select
import subprocess
import tempfile
import time

import cv2
import imageio_ffmpeg
import numpy as np

from config.settings import settings
from ..core.preparation_resources import active_context, checkpoint_boundary, PreparationYielded
from ..utils.caption_scan_runtime import (
    CheckpointCadence, ExactFrameReuse, ObservationChunks, ScanMetrics, EXACT_CONTRACT,
    validate_observation, validate_reuse_spans, checkpoint_elapsed,
)
from ..utils.render_source_binding import digest

VERSION = "source-captions-ab-v2"
FALLBACK = Path(__file__).with_name("source_caption_fallback.py")
from .source_caption_fallback import RepairUnsuitable, appearance, repair_quality, fallback_geometry
VISION = Path(__file__).parents[1] / "utils/caption_vision.js"
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedCaptions:
    video: Path
    center_y: float | None
    source_hash: str
    plan: Path
    anchors: tuple = ()
    mode: str = "A"
    fallback: dict | None = None


def _write(path, value):
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _probe(path):
    from ..utils.video_metadata import _resolve_ffprobe_cmd
    result = subprocess.run([_resolve_ffprobe_cmd(), "-v", "error", "-select_streams", "v:0", "-show_streams",
                             "-of", "json", str(path)], capture_output=True, text=True, check=True, timeout=30)
    stream = json.loads(result.stdout)["streams"][0]
    def rate(value):
        a, b = value.split("/")
        return float(a) / float(b)
    fps = rate(stream["avg_frame_rate"])
    if (fps <= 0 or abs(fps - rate(stream["r_frame_rate"])) > .001
            or abs(float(stream.get("start_time", 0))) > .001
            or any(s.get("rotation", 0) for s in stream.get("side_data_list", []))):
        raise ValueError("原位字幕修补需要零起点、无旋转的恒定帧率源；请先规范化素材")
    return int(stream["width"]), int(stream["height"]), fps, float(stream["duration"])


@contextmanager
def _vision():
    # 错误流落本地临时文件，防止管道写满；所有请求都只有当前帧 PNG。
    with tempfile.TemporaryFile() as errors:
        worker = subprocess.Popen(["/usr/bin/osascript", "-l", "JavaScript", str(VISION)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=errors)
        try:
            yield worker
        finally:
            worker.stdin.close()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.wait(timeout=5)
            worker.stdout.close()


def _observe(worker, frame, *, metrics=None, png_compression=None):
    encoded_at = time.monotonic()
    if png_compression is not None:
        if type(png_compression) is not int or not 0 <= png_compression <= 9:
            raise ValueError('原字幕定位帧编码配置无效')
        ok, png = cv2.imencode('.png', frame, [cv2.IMWRITE_PNG_COMPRESSION, png_compression])
    else:
        ok, png = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("原字幕定位帧编码失败")
    pending, received = memoryview(base64.b64encode(png) + b'\n'), bytearray()
    if metrics is not None:
        metrics.values['encode_seconds'] += time.monotonic() - encoded_at
    vision_at, deadline = time.monotonic(), time.monotonic() + 60
    os.set_blocking(worker.stdin.fileno(), False)
    os.set_blocking(worker.stdout.fileno(), False)
    try:
        while b'\n' not in received:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("原字幕逐帧定位超时，停止出片")
            readable, writable, _ = select.select([worker.stdout], [worker.stdin] if pending else [], [], remaining)
            if writable:
                pending = pending[os.write(worker.stdin.fileno(), pending):]
            if readable:
                chunk = os.read(worker.stdout.fileno(), 65536)
                if not chunk or len(received) + len(chunk) > 4 * 1024 * 1024:
                    raise ValueError('原字幕逐帧定位响应无效，停止出片')
                received.extend(chunk)
        result = json.loads(received)
    finally:
        if metrics is not None:
            metrics.values['vision_seconds'] += time.monotonic() - vision_at
    if not isinstance(result, dict) or 'error' in result or not isinstance(result.get('rows'), list):
        raise ValueError("本地 Vision 无法定位原字幕，停止出片")
    if not isinstance(result.get('faces'), list):
        raise ValueError("人脸避让检测失败，停止出片")
    return result


def _recognize(worker, frame):
    return _observe(worker, frame)["rows"]


def _words(text):
    return set(re.findall(r"[a-z]+", _spoken_text(text)))


def _spoken_text(text):
    text = text.lower().replace('%', ' percent ').replace("'", '').replace('’', '')
    text = re.sub(r'\b(?:[a-z]-)+[a-z]\b', lambda m: m[0].replace('-', ''), text)
    def number(match):
        whole, dot, fraction = match[0].partition('.')
        spoken = _integer_words(int(whole))
        if dot:
            spoken += ' point '+' '.join(_integer_words(int(digit)) for digit in fraction)
        return match[0]+' '+spoken
    return re.sub(r'\b\d+(?:\.\d+)?\b', number, text)


def _integer_words(value):
    small = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
    tens = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()
    if not 0 <= value < 1000:
        return ''
    if value < 20:
        return small[value]
    if value < 100:
        return tens[value//10]+(' '+small[value%10] if value%10 else '')
    return small[value//100]+' hundred'+(' and '+_integer_words(value%100) if value%100 else '')


def _numeric_caption(text, local_text):
    """仅纯数字 OCR 可与 ASR 数值对齐；小数点偶发丢失不改变字形定位。"""
    if not re.fullmatch(r'\s*\d+(?:\.\d+)?\s*%?\s*', text):
        return False
    compact = lambda value: format(Decimal(value).normalize(), 'f').replace('.', '')
    return any(compact(text.strip().rstrip('%').strip()) == compact(number)
               for number in re.findall(r'\d+(?:\.\d+)?', local_text))


def _caption_text_matches(text, spoken):
    if re.fullmatch(r'\s*\d+(?:\.\d+)?\s*%?\s*', text):
        return _numeric_caption(text, spoken)
    tokens, local = _words(text), _words(spoken)
    compact = ''.join(re.findall('[a-z]+', _spoken_text(text)))
    context = ''.join(re.findall('[a-z]+', _spoken_text(spoken)))
    return (bool(tokens) and len(tokens & local)/len(tokens) >= .5
            or len(compact) >= 4 and compact in context
            or len(compact) >= 5 and SequenceMatcher(None, compact, context, autojunk=False).find_longest_match().size/len(compact) >= .8)


def _same_caption_line(a, b):
    return (abs((a[0]+a[2]-b[0]-b[2])/2) < .03
            and abs((a[1]+a[3]-b[1]-b[3])/2) < .012
            and abs(a[3]-a[1]-b[3]+b[1]) < .016)


def _track_pair(box, evidence, index, fps, seconds=.6):
    """只使用直接匹配 ASR 的原始证据，禁止插值结果继续充当证据。"""
    pair = []
    limit = max(1, round(fps*seconds))
    for direction in (-1, 1):
        found = None
        for distance in range(1, limit+1):
            other = index+direction*distance
            if not 0 <= other < len(evidence):
                break
            found = next((r for r in evidence[other] if _same_caption_line(box, r['box'])), None)
            if found:
                break
        if found is None:
            return None
        pair.append(found)
    return pair


def _isolated_ocr(row, pair):
    """低置信孤帧只有前后文字、完整边界都一致时才可恢复。"""
    glyph_count = lambda text: sum(c.isalnum() for c in text)
    return (pair and _spoken_text(pair[0]['text']) == _spoken_text(pair[1]['text'])
            and (row['confidence'] < .75 or abs(glyph_count(row['text'])-glyph_count(pair[0]['text'])) <= 1)
            and all(abs(a-b) < .015 for a,b in zip(pair[0]['box'], pair[1]['box']))
            and all(abs(a-b) < .015 for a,b in zip(row['box'], pair[0]['box'])))


def _joined_line_matches(row, rows, evidence, index, fps):
    """拆行 OCR 的一字误识别须由两侧同文合框及完整并集边界确认。"""
    if row['confidence'] < .9:
        return False
    compact = lambda text: ''.join(c for c in text.lower() if c.isalnum())
    for buddy in rows:
        a, b = row['box'], buddy['box']
        if buddy is row or buddy['confidence'] < .9:
            continue
        left, right = sorted((row, buddy), key=lambda r:r['box'][0])
        if (abs((a[1]+a[3]-b[1]-b[3])/2) > .012
                or not -.025 <= right['box'][0]-left['box'][2] <= .018):
            continue
        union = [min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
        pair = _track_pair(union, evidence, index, fps, .2)
        if not pair or not _isolated_ocr(dict(text=left['text']+right['text'], box=union, confidence=1), pair):
            continue
        expected, actual = compact(pair[0]['text']), compact(left['text']+right['text'])
        edits = SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes()
        if len(expected) >= 5 and sum(max(i2-i1,j2-j1) for tag,i1,i2,j1,j2 in edits if tag != 'equal') <= 1:
            return True
    return False


def _outside_caption_track(row, current, evidence, index, fps):
    # 同帧另有独立 ASR 字幕，且其前后 0.2 秒轨迹一致；分离的画面文字保留原像素。
    # 它仍进入 B 方案障碍物，不能被当作待擦除字幕或从避让计算中删除。
    box = row['box']
    if len(row['text'].strip()) == 1 and row['text'].strip().isalpha() and box[3]-box[1] >= .025:
        return False  # 单字母拆框必须走专门的合框证据，不能作为背景静默忽略。
    if _track_pair(box, evidence, index, fps, .2):
        return False  # 另一条有直接 ASR 支持的字幕轨迹不能当作背景忽略。
    anchors = [*current, *(r for previous in evidence[max(0,index-max(1,round(fps*.2))):index]
                          for r in previous)]
    for anchor in anchors:
        other = anchor['box']
        separation = .025 if row['confidence'] < .5 else .05
        if (other[1]-box[3] > separation and box[3]-box[1] <= .08
                and _track_pair(other, evidence, index, fps, .2)):
            return True
    return False


def _locate(source, segments, directory, fps, progress):
    metrics = ScanMetrics('OCR_BURNED')
    try:
        return _select_locate(source, segments, directory, fps, progress, metrics)
    except Exception:
        metrics.finish(metrics.values.get('frames', 0), failed=True)
        raise


def _select_locate(source, segments, directory, fps, progress, metrics):
    optimized = bool(getattr(settings, 'native_caption_scan_optimization_enabled', False))
    if not optimized and active_context() is None:
        return _locate_legacy(source, segments, directory, fps, progress, metrics=metrics)
    # 老的完整识别缓存仍按原人脸/文字合同验证，绝不拿 native 的 runs 代替。
    cache, identity = _scan_file(source, fps)
    if cache.is_file():
        valid_legacy = False
        try:
            data = json.loads(cache.read_text())
            valid_legacy = (data['identity'] == identity and data['observations_sha256'] ==
                            hashlib.sha256(json.dumps(data['observations'], sort_keys=True).encode()).hexdigest())
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if valid_legacy:
            return _locate_legacy(source, segments, directory, fps, progress, metrics=metrics)
    return _locate_chunked(source, segments, directory, fps, progress, metrics=metrics, optimized=optimized)


def _locate_legacy(source, segments, directory, fps, progress, *, metrics=None):
    metrics = metrics or ScanMetrics('OCR_BURNED')
    cache, scan_identity = _scan_file(source, fps)
    if cache.is_file():
        data = json.loads(cache.read_text())
        if (data['identity'] == scan_identity and data['observations_sha256'] ==
                hashlib.sha256(json.dumps(data['observations'], sort_keys=True).encode()).hexdigest()):
            observations = data['observations']
            metrics.values['frames'] = len(observations)
            _write(directory / 'ocr.json', data)
            selected, center = _classify([x['rows'] for x in observations], segments, fps)
            metrics.finish(len(observations), cache_hit=True)
            return selected, center, observations
    capture = cv2.VideoCapture(str(source))
    frames, observations = [], []
    try:
        with _vision() as worker:
            while True:
                with metrics.measure('decode_seconds'):
                    ok, frame = capture.read()
                if not ok:
                    break
                metrics.values['ocr_calls'] += 1
                observation = _observe(worker, frame, metrics=metrics)
                rows = observation["rows"]
                observations.append(observation)
                metrics.values['frames'] = len(observations)
                # 所有识别结果保留审计；下半画面是此次原位字幕处理范围。
                frames.append(rows)
                if len(frames) % max(1, round(fps * 5)) == 0:
                    LOG.info("[SourceCaptionScan] 已定位 %s 帧", len(frames))
                    if progress:
                        progress("SOURCE_CAPTION_LOCATING")
    finally:
        capture.release()
    if not frames:
        raise ValueError("无法完整解码原片")
    data = {'identity': scan_identity, 'observations': observations,
            'observations_sha256': hashlib.sha256(json.dumps(observations, sort_keys=True).encode()).hexdigest()}
    if digest(source) != scan_identity['source_sha256']:
        raise ValueError('扫描期间源片变化，不能缓存识别结果')
    _write(cache, data)
    _write(directory / 'ocr.json', data)
    selected, center = _classify(frames, segments, fps)
    metrics.finish(len(frames))
    return selected, center, observations


def _locate_chunked(source, segments, directory, fps, progress, *, metrics=None, optimized=True):
    """新扫描独立存储完整 observations；连续完整前缀才可恢复。"""
    metrics = metrics or ScanMetrics('OCR_BURNED')
    width, height, probed_fps, duration = _probe(source)
    if abs(fps - probed_fps) > .001:
        raise ValueError('原字幕时间轴不确定，停止出片')
    timeline = dict(width=width, height=height, fps=fps, expected=round(duration * fps))
    namespace = 'scan-v2-exact' if optimized else 'scan-v2-checkpoint'
    contract = 'burned-scan-v2-exact' if optimized else 'burned-scan-v2-checkpoint'
    identity = dict(version=contract, source_sha256=digest(source), pixel_reuse_enabled=optimized,
                    vision_sha256=digest(VISION), reuse_contract=EXACT_CONTRACT, timeline=timeline)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    store = ObservationChunks(source.parent / '.caption-repair' / namespace / key, identity, timeline)
    observations = store.load(validate_observation)
    spans = []
    if observations:
        try:
            evidence = store.metadata['frame_evidence']
            if (evidence['contract'] != EXACT_CONTRACT or evidence['decoded_frames'] != len(observations)
                    or evidence['pixel_format'] != 'opencv-bgr'):
                raise ValueError('OCR_REUSE_EVIDENCE_INVALID')
            spans = validate_reuse_spans(evidence['reuse_spans'], len(observations))
        except (TypeError, KeyError, ValueError):
            # 无有效映射的块不能作为已核验帧；仅重写本优化命名空间。
            observations, store.entries, store.index = [], [], 0
    reuse = ExactFrameReuse(spans, len(observations))
    prior_elapsed, scan_started = checkpoint_elapsed(store.metadata), time.monotonic()
    resumed, index = len(observations), len(observations)
    cadence = CheckpointCadence(index)
    if index == timeline['expected']:
        _write(directory / 'ocr.json', dict(identity=identity, observations=observations,
            frame_evidence=reuse.evidence(index), observations_sha256=hashlib.sha256(
                json.dumps(observations, sort_keys=True).encode()).hexdigest()))
        selected, center = _classify([x['rows'] for x in observations], segments, fps)
        metrics.finish(index, cache_hit=True, resumed_frames=resumed)
        return selected, center, observations
    capture = cv2.VideoCapture(str(source))
    expected = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if (not capture.isOpened() or abs(capture.get(cv2.CAP_PROP_FPS) - fps) > .001
            or expected != timeline['expected']
            or (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))) != (width, height)):
        capture.release()
        raise ValueError('原字幕完整时间轴不确定，停止出片')
    last_progress = time.monotonic()
    try:
        for skipped in range(index):
            with metrics.measure('decode_seconds'):
                if not capture.grab():
                    raise ValueError('原字幕断点源片提前结束')
            if progress and time.monotonic() - last_progress >= 5:
                progress('SOURCE_CAPTION_LOCATING')
                last_progress = time.monotonic()
        with ExitStack() as workers:
            worker, worker_frames = workers.enter_context(_vision()), 0
            while True:
                with metrics.measure('decode_seconds'):
                    ok, frame = capture.read()
                if not ok:
                    break
                if index >= expected or frame.shape != (height, width, 3) or str(frame.dtype) != 'uint8':
                    raise ValueError('原字幕完整帧不确定，停止出片')
                with metrics.measure('compare_seconds'):
                    observation = reuse.lookup(frame) if optimized else None
                reused = observation is not None
                if not reused:
                    if worker_frames >= 300:
                        workers.close()
                        worker, worker_frames = workers.enter_context(_vision()), 0
                    metrics.values['ocr_calls'] += 1
                    observation = _observe(worker, frame, metrics=metrics,
                        png_compression=getattr(settings, 'caption_scan_png_compression', 3) if optimized else None)
                    worker_frames += 1
                    with metrics.measure('normalize_seconds'):
                        validate_observation(observation)
                reuse.commit(frame, observation, index, reused=reused)
                observations.append(observation)
                index += 1
                metrics.values['frames'] = index
                metrics.values['reused_frames'] += int(reused)
                if progress and time.monotonic() - last_progress >= 5:
                    progress('SOURCE_CAPTION_LOCATING')
                    last_progress = time.monotonic()
                if cadence.due(index):
                    with metrics.measure('checkpoint_seconds'):
                        store.save(observations, metadata=dict(frame_evidence=reuse.evidence(index),
                            scan_wall_seconds=prior_elapsed+time.monotonic()-scan_started))
                    cadence.saved(index)
                    checkpoint_boundary(contract)
        if index != expected or digest(source) != identity['source_sha256']:
            raise ValueError('原字幕扫描未覆盖完整时长或源片变化')
    except PreparationYielded:
        metrics.finish(index, resumed_frames=resumed, outcome='yielded')
        raise
    except Exception:
        with metrics.measure('checkpoint_seconds'):
            store.save(observations, metadata=dict(frame_evidence=reuse.evidence(index),
                scan_wall_seconds=prior_elapsed+time.monotonic()-scan_started))
        metrics.finish(index, resumed_frames=resumed, failed=True)
        raise
    finally:
        capture.release()
    with metrics.measure('checkpoint_seconds'):
        store.save(observations, metadata=dict(frame_evidence=reuse.evidence(index),
            scan_wall_seconds=prior_elapsed+time.monotonic()-scan_started))
    _write(directory / 'ocr.json', dict(identity=identity, observations=observations,
        frame_evidence=reuse.evidence(index), observations_sha256=hashlib.sha256(
            json.dumps(observations, sort_keys=True).encode()).hexdigest()))
    selected, center = _classify([x['rows'] for x in observations], segments, fps)
    metrics.finish(index, resumed_frames=resumed)
    return selected, center, observations


def _scan_file(source, fps):
    identity = dict(version='vision-text-faces-v1', source_sha256=digest(source),
                    vision_sha256=digest(VISION), fps=fps)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return source.parent / '.caption-repair' / ('scan-'+key+'.json'), identity


def _classify(frames, segments, fps):
    # 画面中央的疑似字幕必须有临近转录证据；不能仅凭整段文字没变就当台标放过。
    selected, boxes = [], []
    # ASR 会漏掉短促应答；补位只能来自两侧直接匹配的连续轨迹。
    direct = []
    for index, rows in enumerate(frames):
        spoken = ' '.join(s.get('text', '') for s in segments if s['start']-5 <= index/fps <= s['end']+5)
        direct.append([r for r in rows if r['confidence'] >= .9 and _caption_text_matches(r['text'], spoken)
                       and .38 <= r['box'][1] < r['box'][3] <= .94
                       and .025 <= r['box'][3]-r['box'][1] <= .08])
    for index, rows in enumerate(frames):
        now = index / fps
        local_words = set().union(*(_words(s.get("text", "")) for s in segments
            if s["start"] - 5 <= now <= s["end"] + 5))
        spoken = ' '.join(s.get('text', '') for s in segments if s['start'] - 5 <= now <= s['end'] + 5)
        chosen = []
        for row in rows:
            text, box = row["text"], row["box"]
            # 只处理画面中央的原字幕，保留边缘台标、姓名条和顶部标题。
            if not (.38 <= box[1] < box[3] <= .94 and .22 <= (box[0]+box[2])/2 <= .78):
                continue
            if row['confidence'] < .5 and box[3]-box[1] < .018 and box[2]-box[0] < .08:
                continue  # 拉链等纹理偶发的微小低置信 OCR 不认作原字幕；不改动这些像素。
            if _outside_caption_track(row, direct[index], direct, index, fps):
                continue
            tokens = _words(text)
            if not any(c.isalnum() for c in text):
                continue
            matches = _caption_text_matches(text, spoken)
            if not matches:
                matches = _split_glyph_matches(row, rows, frames, index, fps, local_words)
            if not matches:
                matches = _joined_line_matches(row, rows, direct, index, fps)
            if not matches:
                # 分行硬字幕可能把短词单列；必须由同帧、相邻且同列的完整词组提供证据。
                for buddy in rows:
                    other = buddy['box']
                    if (buddy is row or buddy['confidence'] < .75 or
                            max(box[3], other[3])-min(box[1], other[1]) > .18 or
                            min(box[3], other[3])-max(box[1], other[1]) > .005 or
                            min(box[2], other[2]) <= max(box[0], other[0])):
                        continue
                    combined = tokens | _words(buddy['text'])
                    buddy_tokens = _words(buddy['text'])
                    grouped = (abs(box[0]-other[0]) <= .03 and
                               max(box[1],other[1])-min(box[3],other[3]) <= .035 and
                               buddy_tokens and len(buddy_tokens & local_words)/len(buddy_tokens) >= .5)
                    if tokens and combined and (len(combined & local_words)/len(combined) >= .6 or grouped):
                        matches = True
                        break
            pair = _track_pair(box, direct, index, fps) if not matches or row['confidence'] < .75 else None
            stable_ocr = _isolated_ocr(row, _track_pair(box, direct, index, fps, 1/fps)) if not matches or row['confidence'] < .75 else False
            short_reply = len(tokens) == 1 or tokens <= {'correct','right','yes','yeah','okay','ok'}
            if not matches and short_reply and row['confidence'] >= .9 and pair:
                matches = True  # 短应答/连写词由两侧直接 ASR 证据确认位置；保留字形掩膜。
            if stable_ocr:
                matches = True
                box = [min(r['box'][0] for r in pair), min(r['box'][1] for r in pair),
                       max(r['box'][2] for r in pair), max(r['box'][3] for r in pair)]
            if (row["confidence"] < .75 and not stable_ocr) or not matches:
                raise ValueError(f"第 {index} 帧原字幕位置或文字不确定，停止出片：{text[:60]}")
            if box[3] - box[1] > .08 or not (0 <= box[0] < box[2] <= 1):
                raise ValueError("原字幕字形范围超出可安全修补边界")
            chosen.append(box)
            boxes.append(box)
        if chosen and max(b[3] for b in chosen) - min(b[1] for b in chosen) > .18:
            raise ValueError('同帧存在多处疑似原字幕，需单独审查')
        selected.append(chosen)
    if not boxes:
        return selected, None
    top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
    return selected, (top + bottom) / 2


def _split_glyph_matches(row, rows, frames, index, fps, local_words):
    """单字形必须紧贴可信主句，且前后 0.2 秒内确有同位置合框 OCR；不忽略该字形。"""
    normalized = lambda value: ''.join(c for c in value.lower() if c.isalnum()).replace('0', 'o')
    glyph, box = normalized(row['text']), row['box']
    if len(glyph) != 1 or row['confidence'] < .9:
        return False
    for buddy in rows:
        other, words = buddy['box'], _words(buddy['text'])
        if (buddy is row or buddy['confidence'] < .9 or not words or not words <= local_words
                or abs((box[1]+box[3]-other[1]-other[3])/2) > .012
                or not .4 <= (box[3]-box[1])/(other[3]-other[1]) <= 1.2
                or box[2]-box[0] > .12 or not -.025 <= box[0]-other[2] <= .018):
            continue
        combined = normalized(buddy['text']) + glyph
        union = [min(box[0],other[0]),min(box[1],other[1]),max(box[2],other[2]),max(box[3],other[3])]
        for nearby in range(max(0,index-max(1,round(fps*.2))), min(len(frames),index+max(1,round(fps*.2))+1)):
            if nearby == index:
                continue
            if any(r['confidence'] >= .9 and normalized(r['text']) == combined
                   and all(abs(a-b) < .015 for a,b in zip(r['box'],union)) for r in frames[nearby]):
                return True
    return False


def _anchors(rows, fps):
    """把相邻字幕位置聚成时间区间；无字帧沿用最近位置，不新增显示区域。"""
    located = [(i/fps, (min(b[1] for b in boxes)+max(b[3] for b in boxes))/2)
               for i, boxes in enumerate(rows) if boxes]
    if not located:
        return ()
    groups = [[located[0]]]
    for point in located[1:]:
        if abs(point[1] - np.median([p[1] for p in groups[-1]])) > .10:
            groups.append([])
        groups[-1].append(point)
    return tuple((0 if i == 0 else group[0][0], float(np.median([p[1] for p in group])))
                 for i, group in enumerate(groups))


def caption_spans(prepared, start, end):
    anchors = prepared.anchors or ((0, prepared.center_y),)
    cuts = [start, *(t for t, _ in anchors if start < t < end), end]
    return [(a, b, next(y for t, y in reversed(anchors) if t <= a)) for a, b in zip(cuts, cuts[1:])]


def _mask(frame, boxes):
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for box in boxes:
        pad = max(3, round(w / 120))
        x0, y0 = max(0, int(box[0]*w)-pad), max(0, int(box[1]*h)-pad)
        x1, y1 = min(w, int(box[2]*w)+pad+1), min(h, int(box[3]*h)+pad+1)
        roi = frame[y0:y1, x0:x1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # 局部亮度突起保留细白字，避免把浅色衬衣等平滑背景整体当字擦除。
        contrast = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pad*2+1, pad*2+1)))
        glyph = ((gray > 190) & (hsv[:, :, 1] < 80) & (contrast > 25)).astype(np.uint8)*255
        count, labels, stats, _ = cv2.connectedComponentsWithStats(glyph)
        selected = np.zeros_like(glyph)
        for i in range(1, count):
            _, _, cw, ch, area = stats[i]
            if 2 <= ch <= roi.shape[0] and 1 <= cw <= w*.12 and 2 <= area <= w*h*.003:
                selected[labels == i] = 255
        ratio = np.count_nonzero(selected) / selected.size
        if not .015 <= ratio <= .45:
            raise RepairUnsuitable("原字幕白色字形无法与背景可靠分离")
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pad*2+1, pad*2+1))
        mask[y0:y1, x0:x1] |= cv2.dilate(selected, kernel)
    return mask


def _residual_text(rows, boxes):
    """邻近书封的大识别框边缘轻触字幕框，不算修补区域内的残字。"""
    for row in rows:
        b = row['box']
        area = max(1e-12, (b[2]-b[0]) * (b[3]-b[1]))
        cx, cy = (b[0]+b[2])/2, (b[1]+b[3])/2
        for old in boxes:
            overlap = max(0, min(b[2], old[2])-max(b[0], old[0])) * max(0, min(b[3], old[3])-max(b[1], old[1]))
            if old[0] <= cx <= old[2] and old[1] <= cy <= old[3] or overlap / area >= .25:
                return True
    return False


def _repair_video(source, rows, directory, fps, w, h, progress):
    silent, pending = directory / "silent.mp4", directory / "clean.pending.mp4"
    encoder = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-crf", "12", "-preset", "fast", "-pix_fmt", "yuv420p", str(silent)], stdin=subprocess.PIPE)
    capture = cv2.VideoCapture(str(source))
    try:
        with _vision() as verifier:
            for index, boxes in enumerate(rows):
                ok, frame = capture.read()
                if not ok:
                    raise ValueError("修补时源片提前结束")
                appearance(frame, boxes)
                mask = _mask(frame, boxes)
                fixed = cv2.inpaint(frame, mask, max(2, round(w/90)), cv2.INPAINT_TELEA) if boxes else frame
                repair_quality(frame, fixed, mask)
                if boxes:
                    remaining = _recognize(verifier, fixed)
                    if _residual_text(remaining, boxes):
                        raise RepairUnsuitable(f"第 {index} 帧修补后仍可识别出原字幕")
                encoder.stdin.write(fixed.tobytes())
                if (index+1) % max(1, round(fps*5)) == 0:
                    LOG.info('[SourceCaptionRepair] 已修补并复核 %s 帧', index+1)
                    if progress:
                        progress('VIDEO_RENDERING')
        encoder.stdin.close()
        if encoder.wait(timeout=120) != 0:
            raise ValueError("原字幕修补编码失败")
    finally:
        capture.release()
        if not encoder.stdin.closed:
            encoder.stdin.close()
        if encoder.poll() is None:
            encoder.terminate()
            try:
                encoder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                encoder.kill()
                encoder.wait(timeout=5)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(silent),
        "-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-c", "copy", "-movflags", "+faststart", str(pending)], check=True, timeout=120)
    cleaned = directory / "clean.mp4"
    pending.replace(cleaned)
    silent.unlink()
    return cleaned


def prepare_source(source: Path, segments: list[dict], progress=None) -> PreparedCaptions:
    """逐帧扫描全片；中途失败不返回原片，避免调用者静默叠加两套字幕。"""
    source = Path(source)
    w, h, fps, duration = _probe(source)
    if w < h and h/w > 1920/1080 + .001:
        raise ValueError("源片比 9:16 更窄，现有布局会裁切，需先人工规范化")
    source_hash = digest(source)
    from .approved_caption_layout import approved_layout, validate_segments
    approved = approved_layout(source, source_hash)
    if approved is not None:
        approved.geometry(w, h)
        validate_segments(segments, duration, source_hash=source_hash)
        identity = dict(source_sha256=source_hash, layout=approved.payload(),
                        layout_sha256=digest(Path(__file__).with_name('approved_caption_layout.py')),
                        segments_sha256=hashlib.sha256(json.dumps(segments, sort_keys=True,
                            ensure_ascii=False).encode()).hexdigest())
        directory = source.parent / '.caption-repair' / hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()).hexdigest()
        directory.mkdir(parents=True, exist_ok=True)
        plan = directory / 'plan.json'
        _write(plan, dict(identity=identity, mode='FRAMED', crop=False,
                         extra_subtitle_panel=True, clean_sha256=source_hash,
                         canvas=[1080, 1920], source_canvas=[w, h], fps=fps,
                         frames=round(duration*fps)))
        LOG.info('[ApprovedCaptionLayout] %s：完整画面 %sx%s，双语区 %s–%s',
                 approved.profile, approved.width, approved.height,
                 approved.subtitle_top, approved.subtitle_bottom)
        return PreparedCaptions(source, None, source_hash, plan, mode='FRAMED')
    identity = {"version": VERSION, "source_sha256": source_hash, "vision_sha256": digest(VISION),
                "implementation_sha256": digest(Path(__file__)), "fallback_sha256": digest(FALLBACK),
                "segments_sha256": hashlib.sha256(json.dumps(segments, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    directory = source.parent / ".caption-repair" / hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    plan = directory / "plan.json"
    if plan.is_file():
        data = json.loads(plan.read_text())
        cleaned = directory / "clean.mp4" if data["mode"] == "A" else source
        if data["identity"] == identity and digest(cleaned) == data["clean_sha256"]:
            return PreparedCaptions(cleaned, data["center_y"], source_hash, plan, tuple(map(tuple, data.get('anchors', []))), data['mode'], data.get('fallback'))
    # 横屏既有布局不在本次 A 方案范围；不改变英语精读卡片模板。
    if w >= h:
        return PreparedCaptions(source, None, source_hash, plan)
    rows, center, observations = _locate(source, segments, directory, fps, progress)
    if digest(source) != source_hash:
        raise ValueError("扫描期间源片发生变更")
    expected = round(duration * fps)
    if abs(len(rows) - expected) > 1:
        raise ValueError("原字幕扫描未覆盖完整时长")
    cleaned = source
    if center is not None:
        mode, fallback, reason = "A", None, ""
        try:
            cleaned = _repair_video(source, rows, directory, fps, w, h, progress)
        except RepairUnsuitable as exc:
            # 仅可靠定位后的外观/质量失败可评估 B；I/O、OCR、编码异常继续阻断。
            LOG.info("[SourceCaptionFallback] A 不适用，整片从原片评估 B：%s", exc)
            cleaned, mode, reason = source, "B", str(exc)
            fallback = fallback_geometry(rows, observations, h, fps)
    else:
        mode, fallback, reason = "NONE", None, "未检测到中央硬字幕"
    if identity['implementation_sha256'] != digest(Path(__file__)) or identity['vision_sha256'] != digest(VISION) or identity['fallback_sha256'] != digest(FALLBACK):
        raise ValueError('处理期间字幕实现发生变化，不能签发处理计划')
    anchors = _anchors(rows, fps)
    _write(plan, {"identity": identity, "center_y": center, "anchors": anchors, "frames": len(rows), "fps": fps,
                  "canvas": [w, h], "crop": False, "extra_subtitle_panel": False, "clean_sha256": digest(cleaned),
                  "mode": mode, "reason": reason, "fallback": fallback, "selected": rows})
    return PreparedCaptions(cleaned, center, source_hash, plan, anchors, mode, fallback)


def fallback_source(source, prepared, reason):
    """A 排版不合格时整片回到原片；保留 A 的证据，不覆盖旧计划。"""
    if prepared.mode != 'A' or digest(source) != prepared.source_hash:
        raise ValueError('不能从未知状态退化到 B')
    data = json.loads(prepared.plan.read_text())
    observations = json.loads((prepared.plan.parent/'ocr.json').read_text())['observations']
    geometry = fallback_geometry(data['selected'], observations, data['canvas'][1], data['fps'])
    data.update(mode='B', reason=str(reason), fallback=geometry, clean_sha256=digest(source))
    plan = prepared.plan.with_name('fallback-plan.json')
    _write(plan, data)
    return PreparedCaptions(Path(source), prepared.center_y, prepared.source_hash, plan,
                            prepared.anchors, 'B', geometry)


def seal_render(output: Path, source: Path, ass: Path, prepared: PreparedCaptions):
    if digest(source) != prepared.source_hash:
        raise ValueError("渲染期间源片变更，不能签发原位字幕凭证")
    _write(output.with_suffix(".captions.json"), {"version": VERSION, "source_sha256": digest(source),
        "output_sha256": digest(output), "ass_sha256": digest(ass), "plan": str(prepared.plan.resolve()),
        "plan_sha256": digest(prepared.plan), "implementation_sha256": digest(Path(__file__)),
        "renderer_sha256": digest(Path(__file__).with_name('vertical_processor.py')), "vision_sha256": digest(VISION),
        "approved_layout_sha256": digest(Path(__file__).with_name('approved_caption_layout.py')),
        "fallback_sha256": digest(FALLBACK), "mode": prepared.mode})


def render_receipt_matches(output: Path, source: Path) -> bool:
    try:
        w, h, _, _ = _probe(source)
        if w >= h:
            return True
        data = json.loads(output.with_suffix(".captions.json").read_text())
        from .approved_caption_layout import approved_layout
        approved = approved_layout(source, digest(source))
        if approved is not None:
            plan = json.loads(Path(data['plan']).read_text())
            if (data['mode'] != 'FRAMED' or plan['identity']['layout'] != approved.payload()
                    or plan['identity']['layout_sha256'] != digest(Path(__file__).with_name('approved_caption_layout.py'))):
                return False
        return (data["version"] == VERSION and data["source_sha256"] == digest(source)
            and data["output_sha256"] == digest(output) and data["ass_sha256"] == digest(source.with_suffix(".ass"))
            and data["plan_sha256"] == digest(Path(data["plan"]))
            and data['renderer_sha256'] == digest(Path(__file__).with_name('vertical_processor.py'))
            and data['approved_layout_sha256'] == digest(Path(__file__).with_name('approved_caption_layout.py'))
            and data["fallback_sha256"] == digest(FALLBACK)
            and data["implementation_sha256"] == digest(Path(__file__)) and data["vision_sha256"] == digest(VISION))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False

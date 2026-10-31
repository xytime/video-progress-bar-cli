"""逐帧扫描的计时、严格像素复用及独立分块断点；不决定字幕或发布权限。

依赖：processors -> 本模块 -> numpy / file_utils / stage_events；不依赖识别器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 保留全帧证据的相等复用、计时和校验分块断点。 |
"""
from contextlib import contextmanager
import copy
import hashlib
import json
import logging
import math
import time

import numpy as np

from .file_utils import write_json_atomically
from .stage_events import emit_event

LOG = logging.getLogger(__name__)
CHECKPOINT_FRAMES = 300
CHECKPOINT_SECONDS = 30
EXACT_CONTRACT = 'full-frame-exact-v1'


def checkpoint_elapsed(metadata):
    """旧断点缺省为零；已保存的累计扫描墙钟不能因 owner 更换归零。"""
    value = (metadata or {}).get('scan_wall_seconds', 0.)
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError('OCR_CHECKPOINT_BUDGET_INVALID')
    return float(value)


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


class ScanMetrics:
    def __init__(self, stage):
        self.stage = stage
        self.started = time.monotonic()
        self.finished = None
        self.values = dict(ocr_calls=0, reused_frames=0, decode_seconds=0., compare_seconds=0.,
                           encode_seconds=0., vision_seconds=0., normalize_seconds=0.,
                           checkpoint_seconds=0.)

    @contextmanager
    def measure(self, name):
        start = time.monotonic()
        try:
            yield
        finally:
            self.values[name] += time.monotonic() - start

    def finish(self, frames, *, cache_hit=False, resumed_frames=0, failed=False, outcome=None):
        if self.finished is not None:
            return self.finished
        values = dict(self.values, frames=frames, cache_hit=cache_hit, resumed_frames=resumed_frames,
                      failed=failed, outcome=outcome or ('failed' if failed else 'complete'),
                      duration_seconds=time.monotonic() - self.started)
        LOG.info('[CaptionScanMetrics] stage=%s %s', self.stage, json.dumps(values, sort_keys=True))
        emit_event('metric', stage=self.stage, **values)
        self.finished = values
        return values


class CheckpointCadence:
    def __init__(self, index=0):
        self.index, self.at = index, time.monotonic()

    def due(self, index):
        return index - self.index >= CHECKPOINT_FRAMES or time.monotonic() - self.at >= CHECKPOINT_SECONDS

    def saved(self, index):
        self.index, self.at = index, time.monotonic()


def validate_reuse_spans(spans, count):
    previous_end = 0
    if not isinstance(spans, list):
        raise ValueError('OCR_REUSE_EVIDENCE_INVALID')
    for span in spans:
        if not isinstance(span, dict):
            raise ValueError('OCR_REUSE_EVIDENCE_INVALID')
        first, last, observed = (span.get(key) for key in ('first', 'last', 'observed_frame'))
        digest = span.get('pixel_sha256')
        if (any(type(x) is not int for x in (first, last, observed))
                or not previous_end <= observed == first - 1 < last - 1 < count
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('OCR_REUSE_EVIDENCE_INVALID')
        previous_end = last
    return spans


class ExactFrameReuse:
    """只比较相邻完整 BGR 帧；恢复后没有前帧像素，第一帧必须实际识别。"""
    def __init__(self, spans=None, count=0):
        self.spans = copy.deepcopy(validate_reuse_spans(spans or [], count))
        self.frame = self.result = None
        self.observed_frame = None

    def lookup(self, frame):
        if (self.frame is not None and frame.shape == self.frame.shape
                and frame.dtype == self.frame.dtype and np.array_equal(frame, self.frame)):
            return copy.deepcopy(self.result)
        return None

    def commit(self, frame, result, index, *, reused):
        if reused:
            # 相等由 lookup 的完整逐字节比较证明；摘要仅用于事后对应源帧。
            if self.spans and self.spans[-1]['observed_frame'] == self.observed_frame:
                self.spans[-1]['last'] = index + 1
            else:
                self.spans.append(dict(first=index, last=index + 1, observed_frame=self.observed_frame,
                                       pixel_sha256=hashlib.sha256(memoryview(self.frame)).hexdigest()))
        else:
            self.frame, self.result, self.observed_frame = frame.copy(), copy.deepcopy(result), index

    def evidence(self, count):
        validate_reuse_spans(self.spans, count)
        return dict(contract=EXACT_CONTRACT, decoded_frames=count, pixel_format='opencv-bgr',
                    reuse_spans=copy.deepcopy(self.spans))


class ObservationChunks:
    """只供完整帧 observations 使用；manifest 提交前的孤立块不会成为进度。"""
    def __init__(self, directory, identity, timeline):
        self.directory, self.identity, self.timeline = directory, identity, timeline
        self.entries = []
        self.index = 0
        self.metadata = None

    def load(self, validate):
        self.entries, self.index, self.metadata = [], 0, None
        try:
            envelope = json.loads((self.directory / 'manifest.json').read_text())
            state = envelope['state']
            if (envelope['identity'] != self.identity or envelope['sha256'] != checksum(state)
                    or state['timeline'] != self.timeline):
                return []
            records, entries = [], state['chunks']
            for entry in entries:
                first, last = entry['first'], entry['last']
                if (type(first) is not int or type(last) is not int or first != len(records)
                        or not first < last <= self.timeline['expected'] or last - first > CHECKPOINT_FRAMES):
                    raise ValueError('OCR_CHUNK_INVALID')
                name = f'frames-{first:09d}-{last:09d}.json'
                if entry['file'] != name:
                    raise ValueError('OCR_CHUNK_INVALID')
                chunk = json.loads((self.directory / name).read_text())
                if (chunk['first'] != first or chunk['last'] != last or checksum(chunk) != entry['sha256']
                        or len(chunk['observations']) != last - first):
                    raise ValueError('OCR_CHUNK_INVALID')
                for observation in chunk['observations']:
                    validate(observation)
                records.extend(chunk['observations'])
            if type(state['frame_count']) is not int or state['frame_count'] != len(records):
                raise ValueError('OCR_CHUNK_INVALID')
            self.entries, self.index = entries, len(records)
            self.metadata = state.get('metadata')
            return records
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.entries, self.index = [], 0
            return []

    def save(self, observations, *, metadata=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        while self.index < len(observations):
            first, last = self.index, min(len(observations), self.index + CHECKPOINT_FRAMES)
            chunk = dict(first=first, last=last, observations=observations[first:last])
            name = f'frames-{first:09d}-{last:09d}.json'
            write_json_atomically(self.directory / name, chunk)
            entries = [*self.entries, dict(first=first, last=last, file=name, sha256=checksum(chunk))]
            state = dict(timeline=self.timeline, chunks=entries, frame_count=last)
            if last == len(observations) and metadata is not None:
                state['metadata'] = metadata
            write_json_atomically(self.directory / 'manifest.json',
                                  dict(identity=self.identity, state=state, sha256=checksum(state)))
            self.entries, self.index = entries, last
            self.metadata = state.get('metadata')


def validate_observation(observation):
    """修补器保留原始坐标与人脸；不把另一个 OCR 合同的结果当作本次证据。"""
    if not isinstance(observation, dict) or not all(isinstance(observation.get(k), list) for k in ('rows', 'faces')):
        raise ValueError('OCR_OBSERVATION_INVALID')
    for row in observation['rows']:
        if (not isinstance(row, dict) or not isinstance(row.get('text'), str) or not isinstance(row.get('confidence'), (float, int))
                or not math.isfinite(row['confidence']) or not 0 <= row['confidence'] <= 1):
            raise ValueError('OCR_OBSERVATION_INVALID')
    for box in [*(r.get('box') for r in observation['rows']), *observation['faces']]:
        if (not isinstance(box, list) or len(box) != 4
                or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise ValueError('OCR_OBSERVATION_INVALID')
    return observation

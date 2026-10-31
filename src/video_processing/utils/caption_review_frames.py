"""语义核验原分辨率图片缓存；只复用源、编码契约及字节摘要全部一致的图片。

依赖：router -> 本模块 -> cv2 / file_utils / render_source_binding；不调用模型。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 延迟打开解码器、校验图片及逐帧原子检查点，重复核验免解码。 |
"""
import fcntl
import json
import time

import cv2

from .file_utils import write_json_atomically
from .render_source_binding import digest


class ReviewFrames:
    def __init__(self, source, directory, count, metrics):
        self.source, self.count, self.metrics = source, count, metrics
        self.identity = dict(source_sha256=digest(source), contract='review-jpeg-default-v1',
                             opencv=cv2.__version__, frame_count=count)
        self.directory = directory / 'review-frames-v1' / self.identity['source_sha256']
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = self.directory / 'manifest.json'
        self.entries, self.capture = {}, None
        try:
            data = json.loads(self.manifest.read_text())
            if data['identity'] == self.identity and isinstance(data['frames'], dict):
                self.entries = data['frames']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        metrics.values.update(image_cache_hits=0, image_decodes=0, image_cache_seconds=0.)

    def __enter__(self):
        self.lock = (self.directory / 'frames.lock').open('a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.lock.close()
            raise
        return self

    def __exit__(self, *args):
        try:
            if self.capture is not None:
                self.capture.release()
            if digest(self.source) != self.identity['source_sha256']:
                # 源中途变化时撤销 manifest，禁止留下混合图片证据。
                self.manifest.unlink(missing_ok=True)
                raise ValueError('REVIEW_SOURCE_CHANGED')
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()

    def image(self, frame_number):
        if type(frame_number) is not int or not 0 <= frame_number < self.count:
            raise ValueError('REVIEW_FRAME_UNAVAILABLE')
        started = time.monotonic()
        path = self.directory / f'frame-{frame_number}.jpg'
        try:
            if path.is_file() and self.entries.get(str(frame_number)) == digest(path):
                self.metrics.values['image_cache_hits'] += 1
                return path
            if self.capture is None:
                self.capture = cv2.VideoCapture(str(self.source))
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = self.capture.read()
            temporary = path.with_suffix('.tmp.jpg')
            try:
                if not ok or not cv2.imwrite(str(temporary), frame):
                    raise ValueError('REVIEW_FRAME_UNAVAILABLE')
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            self.entries[str(frame_number)] = digest(path)
            write_json_atomically(self.manifest, dict(identity=self.identity, frames=self.entries))
            self.metrics.values['image_decodes'] += 1
            return path
        finally:
            self.metrics.values['image_cache_seconds'] += time.monotonic() - started

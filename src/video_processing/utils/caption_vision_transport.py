"""完整像素的本机 Vision 文件传输；每个 worker 独占文件及单调请求编号。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-29 | Codex | 当前帧响应后显式 STOP，消除 EOF 无响应的固定退出等待；仅回收本上下文创建的 worker。 |
| 1.0.0 | 2026-10-29 | Codex | 无损 BMP 避免 PNG 压缩和大体积 base64 管道；响应编号防串帧。 |
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time

import cv2

CONTRACT = 'vision-local-bmp-v1'


@contextmanager
def file_worker(script):
    with tempfile.TemporaryDirectory(prefix='caption-vision-') as folder, tempfile.TemporaryFile() as errors:
        worker = subprocess.Popen(['/usr/bin/osascript', '-l', 'JavaScript', str(script)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors)
        worker.caption_frame_path = Path(folder) / 'frame.bmp'
        worker.caption_request_id = 0
        try:
            yield worker
        finally:
            # JXA 的 availableData 在本机 EOF 后不退出；完成帧已由编号应答确认。
            # STOP 不执行识别，不等待管道有空间；异常路径仍只回收本 worker。
            try:
                os.set_blocking(worker.stdin.fileno(), False)
                os.write(worker.stdin.fileno(), b'{"command":"STOP"}\n')
            except (OSError, ValueError):
                pass
            worker.stdin.close()
            try:
                worker.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=3)
            worker.stdout.close()


def observe_file(worker, frame, *, timeout=45, metrics=None):
    deadline = time.monotonic() + timeout
    encoded_at = time.monotonic()
    if frame.ndim != 3 or frame.shape[2] != 3 or str(frame.dtype) != 'uint8':
        raise ValueError('OCR_FRAME_ENCODING')
    ok, encoded = cv2.imencode('.bmp', frame)
    if not ok:
        raise ValueError('OCR_FRAME_ENCODING')
    # 文件关闭后才发请求；收到当前编号前不覆盖，重试必须另建 worker/目录。
    worker.caption_frame_path.write_bytes(encoded)
    worker.caption_request_id += 1
    request_id = worker.caption_request_id
    pending = memoryview((json.dumps(dict(path=str(worker.caption_frame_path), id=request_id))+'\n').encode())
    if metrics is not None:
        metrics.values['encode_seconds'] += time.monotonic() - encoded_at
    started, received = time.monotonic(), bytearray()
    os.set_blocking(worker.stdin.fileno(), False)
    os.set_blocking(worker.stdout.fileno(), False)
    try:
        while b'\n' not in received:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('OCR_TIMEOUT')
            readable, writable, _ = select.select([worker.stdout], [worker.stdin] if pending else [], [], remaining)
            if writable:
                pending = pending[os.write(worker.stdin.fileno(), pending):]
            if readable:
                chunk = os.read(worker.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError('OCR_UNAVAILABLE')
                received.extend(chunk)
                if len(received) > 4*1024*1024:
                    raise ValueError('OCR_RESPONSE_INVALID')
        data = json.loads(received)
    finally:
        if metrics is not None:
            metrics.values['vision_seconds'] += time.monotonic() - started
    if (not isinstance(data, dict) or type(data.get('id')) is not int
            or data.get('id') != request_id or 'error' in data
            or not isinstance(data.get('rows'), list)):
        raise ValueError('OCR_UNAVAILABLE')
    return data

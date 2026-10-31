"""文件传输使用完整无损像素，错误或串帧回应不得变成空字幕。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 真实管道验证 BMP 像素、编号绑定、坏响应及有界失联。 |
"""
from contextlib import contextmanager
import subprocess
import sys
import time

import cv2
import numpy as np
import pytest

from video_processing.utils.caption_vision_transport import observe_file, file_worker


@contextmanager
def responder(tmp_path, expression, delay=0):
    code = ('import sys,json,time; request=json.loads(sys.stdin.readline()); '
            f'time.sleep({delay!r}); print({expression},flush=True)')
    worker = subprocess.Popen([sys.executable, '-u', '-c', code],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    worker.caption_frame_path = tmp_path / 'frame.bmp'
    worker.caption_request_id = 0
    try:
        yield worker
    finally:
        worker.stdin.close()
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=5)
        worker.stdout.close()


def test_file_input_preserves_every_bgr_channel_and_binds_current_reply(tmp_path):
    frame = np.random.default_rng(10).integers(0, 256, (48,64,3), dtype=np.uint8)
    with responder(tmp_path, 'json.dumps(dict(id=request["id"],rows=[]))') as worker:
        assert observe_file(worker, frame, timeout=5) == dict(id=1, rows=[])
        restored = cv2.imdecode(np.frombuffer(worker.caption_frame_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        assert np.array_equal(restored, frame)
        assert worker.caption_request_id == 1


@pytest.mark.parametrize('reply', ['not-json', '[]', '{}', '{"id":0,"rows":[]}',
    '{"id":true,"rows":[]}', '{"id":1.0,"rows":[]}', '{"id":1,"error":"VISION_FAILED","rows":[]}',
    '{"id":1,"rows":null}'])
def test_bad_or_stale_reply_is_never_accepted_as_successful_empty_frame(tmp_path, reply):
    with responder(tmp_path, repr(reply)) as worker:
        with pytest.raises(ValueError):
            observe_file(worker, np.zeros((8,8,3),dtype=np.uint8), timeout=5)


def test_lost_worker_has_bounded_wait_and_cannot_return_absence(tmp_path):
    with responder(tmp_path, '""', delay=1) as worker:
        with pytest.raises(ValueError, match='OCR_TIMEOUT'):
            observe_file(worker, np.zeros((8,8,3),dtype=np.uint8), timeout=.05)


@pytest.mark.parametrize('shape,dtype', [((8,8),np.uint8),((8,8,4),np.uint8),((8,8,3),np.float32)])
def test_non_bgr_or_non_byte_pixels_are_rejected_before_request(tmp_path, shape, dtype):
    with responder(tmp_path, '""') as worker:
        with pytest.raises(ValueError, match='OCR_FRAME_ENCODING'):
            observe_file(worker, np.zeros(shape,dtype=dtype), timeout=5)
        assert worker.caption_request_id == 0


def test_context_sends_stop_and_reaps_only_its_dedicated_worker(tmp_path, monkeypatch):
    marker = tmp_path / 'stopped'
    script = tmp_path / 'worker.py'
    script.write_text('import sys,json\nfrom pathlib import Path\n'
        'for line in sys.stdin:\n'
        ' if json.loads(line).get("command")=="STOP":\n'
        f'  Path({str(marker)!r}).write_text("STOP"); break\n')
    popen = subprocess.Popen
    monkeypatch.setattr('video_processing.utils.caption_vision_transport.subprocess.Popen',
        lambda command, **kwargs: popen([sys.executable, str(script)], **kwargs))
    started = time.monotonic()
    with file_worker(script) as worker:
        worker_pid = worker.pid
    assert marker.read_text() == 'STOP'
    assert worker.pid == worker_pid and worker.returncode == 0
    assert time.monotonic() - started < 2

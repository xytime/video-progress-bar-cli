"""真实跨进程全局锁争用超过准入期限，清理仍保留票据直到可安全删除。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 重现2秒锁争用与失主登记，保证准入仍有界、清理不中途丢锁。 |
"""
import json
import subprocess
import sys
import threading
import time

import pytest

from video_processing.core.maintenance import MaintenanceDenied, MaintenanceGate


def test_cleanup_keeps_real_admission_lock_past_normal_admission_timeout(tmp_path):
    import fcntl
    gate = MaintenanceGate(tmp_path / 'control.json')
    state = gate.enter('setup')
    gate.resume(state['version'], validated=True)
    ticket = gate.acquire('test', 'one')
    ticket.start()
    path = gate.directory / (ticket.row['id'] + '.json')
    script = ("import fcntl,sys; f=open(sys.argv[1],'a+'); fcntl.flock(f,fcntl.LOCK_EX); "
              "print('locked',flush=True); sys.stdin.readline()")
    child = subprocess.Popen([sys.executable, '-c', script, str(gate.path.with_suffix('.lock'))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    errors = []
    def close():
        try:
            ticket.close()
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=close)
    try:
        assert child.stdout.readline().strip() == 'locked'
        worker.start()
        # 竞争者仍按2秒准入期限闭锁；已结束票据清理不丢弃实际 flock。
        with pytest.raises(MaintenanceDenied, match='维护状态无法确认'):
            gate.require_running()
        assert worker.is_alive() and path.exists() and not ticket.stream.closed
        with path.open('rb') as stream:
            with pytest.raises(BlockingIOError):
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        child.communicate('release\n', timeout=5)
        worker.join(timeout=5)
    assert not errors and not worker.is_alive() and ticket.stream.closed
    assert gate.status()['unknown'] == [] and not path.exists()

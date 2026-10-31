"""独立 session 的沙盒执行者回收边界，使用真实子进程。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 仅终止精确副本执行者，保留其他根和外部脚本。 |
"""
from pathlib import Path
import subprocess
import sys

from scripts.run_isolated_tests import reap_snapshot_workers
from scripts import run_isolated_tests as runner


def test_reaps_only_exact_snapshot_python_script(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    python = repo / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    script = repo / 'scripts/worker.py'
    script.parent.mkdir()
    script.write_text("import time; print('ready', flush=True); time.sleep(60)")
    external = tmp_path / 'external.py'
    external.write_bytes(script.read_bytes())
    processes = [subprocess.Popen([str(python), str(path)], start_new_session=True,
                 stdout=subprocess.PIPE, text=True) for path in (script, external)]
    try:
        assert all(p.stdout.readline().strip() == 'ready' for p in processes)
        # macOS 沙盒禁止 ps 全机枚举；仅替代清单边界，发信号与退出仍为真实进程。
        def inventory(*args, **kwargs):
            return '\n'.join(f'{p.pid} {python} {path}' for p, path in zip(processes, (script, external))
                             if p.poll() is None)
        monkeypatch.setattr(runner.subprocess, 'check_output', inventory)
        # 别的物理副本不能匹配，即使进程名和脚本名相同。
        assert reap_snapshot_workers(tmp_path / 'other') == []
        receipt = reap_snapshot_workers(repo)
        assert receipt == [dict(pid=processes[0].pid, script=str(script), signal='SIGTERM')]
        assert processes[0].wait(timeout=5) != 0
        assert processes[1].poll() is None
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            process.stdout.close()

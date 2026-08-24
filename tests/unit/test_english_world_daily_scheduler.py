"""英语世界日更调度器的故障可观测性测试。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 2.0.0 | 2026-08-24 | Codex | 覆盖直接 Python 协调器的重试、失败回执与 LaunchAgent 入口。 |
"""

from __future__ import annotations

import subprocess
import sys
import plistlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / "scripts" / "run_english_world_daily.py"
PLIST = PROJECT_ROOT / "scripts" / "com.videopipeline.english-world-daily.plist"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _runner_arguments(tmp_path: Path, *, codex_exit: int) -> tuple[list[str], Path, Path]:
    calls = tmp_path / "calls.log"
    fake_codex = tmp_path / "codex"
    fake_python = tmp_path / "python"
    notifier = tmp_path / "notifier.py"
    _write_executable(fake_codex, f"#!/usr/bin/env bash\necho codex >> {calls}\nexit {codex_exit}\n")
    _write_executable(fake_python, f"#!/usr/bin/env bash\necho notifier:\"$*\" >> {calls}\n")
    notifier.write_text("# fake notifier\n", encoding="utf-8")
    log_dir = tmp_path / "logs"
    arguments = [
        sys.executable, str(RUNNER), "--project-root", str(PROJECT_ROOT),
        "--codex-bin", str(fake_codex), "--python-bin", str(fake_python),
        "--notifier-script", str(notifier), "--log-dir", str(log_dir),
        "--lock-dir", str(tmp_path / "lock"), "--max-attempts", "3",
        "--retry-delay-seconds", "0",
    ]
    return arguments, calls, log_dir


def test_ex_config_retries_then_notifies_with_durable_status(tmp_path: Path):
    arguments, calls, log_dir = _runner_arguments(tmp_path, codex_exit=78)

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 78
    call_lines = calls.read_text(encoding="utf-8").splitlines()
    assert call_lines.count("codex") == 3
    assert len([line for line in call_lines if line.startswith("notifier:")]) == 1
    status = (log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=FAILED_COORDINATOR" in status
    assert "exit_code=78" in status
    assert "attempts=3" in status
    run_logs = list(log_dir.glob("run_*.log"))
    assert len(run_logs) == 1
    assert "coordinator attempt 3/3" in run_logs[0].read_text(encoding="utf-8")


def test_success_does_not_send_failure_notification(tmp_path: Path):
    arguments, calls, log_dir = _runner_arguments(tmp_path, codex_exit=0)

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert calls.read_text(encoding="utf-8").splitlines() == ["codex"]
    status = (log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=COORDINATOR_FINISHED" in status
    assert "exit_code=0" in status


def test_plist_directly_starts_python_coordinator():
    plist_text = PLIST.read_text(encoding="utf-8")
    runner_text = RUNNER.read_text(encoding="utf-8")
    with PLIST.open("rb") as plist_file:
        configuration = plistlib.load(plist_file)

    assert "/Users/ryusei/.pyenv/versions/3.12.4/bin/python" in plist_text
    assert "/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/run_english_world_daily.py" in plist_text
    assert "run_english_world_daily_codex.sh" not in plist_text
    assert configuration["StartCalendarInterval"] == [
        {"Hour": 7, "Minute": 0},
        {"Hour": 16, "Minute": 30},
    ]
    assert "严格大于 30 秒且不超过 300 秒" in runner_text

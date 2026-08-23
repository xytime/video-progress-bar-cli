"""英语世界日更调度器的故障可观测性测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-23 | Codex | 覆盖 EX_CONFIG 有界重试、失败 Telegram 回执和独立运行日志。 |
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / "scripts" / "run_english_world_daily_codex.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _runner_environment(tmp_path: Path, *, codex_exit: int) -> tuple[dict[str, str], Path, Path]:
    calls = tmp_path / "calls.log"
    fake_codex = tmp_path / "codex"
    fake_python = tmp_path / "python"
    notifier = tmp_path / "notifier.py"
    _write_executable(
        fake_codex,
        "#!/usr/bin/env bash\n"
        "echo codex >> \"$CALLS_LOG\"\n"
        "exit \"$FAKE_CODEX_EXIT\"\n",
    )
    _write_executable(
        fake_python,
        "#!/usr/bin/env bash\n"
        "echo notifier:\"$*\" >> \"$CALLS_LOG\"\n",
    )
    notifier.write_text("# fake notifier\n", encoding="utf-8")
    log_dir = tmp_path / "logs"
    environment = {
        **os.environ,
        "CALLS_LOG": str(calls),
        "FAKE_CODEX_EXIT": str(codex_exit),
        "CODEX_BIN": str(fake_codex),
        "PYTHON_BIN": str(fake_python),
        "NOTIFIER_SCRIPT": str(notifier),
        "ENGLISH_WORLD_LOG_DIR": str(log_dir),
        "ENGLISH_WORLD_LOCK_DIR": str(tmp_path / "lock"),
        "MAX_EX_CONFIG_ATTEMPTS": "3",
        "RETRY_DELAY_SECONDS": "0",
    }
    return environment, calls, log_dir


def test_ex_config_retries_then_notifies_with_durable_status(tmp_path: Path):
    environment, calls, log_dir = _runner_environment(tmp_path, codex_exit=78)

    result = subprocess.run(
        [str(RUNNER)], cwd=PROJECT_ROOT, env=environment,
        capture_output=True, text=True, check=False,
    )

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
    environment, calls, log_dir = _runner_environment(tmp_path, codex_exit=0)

    result = subprocess.run(
        [str(RUNNER)], cwd=PROJECT_ROOT, env=environment,
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0
    assert calls.read_text(encoding="utf-8").splitlines() == ["codex"]
    status = (log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=COORDINATOR_FINISHED" in status
    assert "exit_code=0" in status

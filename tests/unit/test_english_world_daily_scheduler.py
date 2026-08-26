"""英语世界日更调度器的故障可观测性测试。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 2.0.0 | 2026-08-24 | Codex | 覆盖直接 Python 协调器的重试、失败回执与 LaunchAgent 入口。 |
# | 2.1.0 | 2026-08-25 | Codex | 覆盖 Codex 瞬时传输故障触发有界重试。 |
# | 2.2.0 | 2026-08-25 | Codex | 覆盖瞬时失败后已获 Telegram 审核回执时禁止重跑。 |
# | 2.3.0 | 2026-08-26 | Codex | 覆盖协调器卡死时终止进程组、写入超时状态并发送一次失败回执。 |
# | 2.4.0 | 2026-08-26 | Codex | 覆盖可审计锁的失效 PID 回收，避免中断后日更永久被跳过。 |
# | 2.5.0 | 2026-08-26 | Codex | 覆盖协调器收到 SIGTERM 后的子进程收口、失败状态与锁释放。 |
# | 2.6.0 | 2026-08-26 | Codex | 固化生产代理的受限工作区和禁止自我监控约束。 |
# | 2.7.0 | 2026-08-26 | Codex | 固化工作区沙箱中的来源网络访问，避免 DNS 隔离造成日更断供。 |
# | 2.8.0 | 2026-08-26 | Codex | 固化协调器复用项目 YouTube Cookie，避免裸 yt-dlp 被反爬拦截。 |
# | 2.9.0 | 2026-08-26 | Codex | 固化用户自动投稿策略覆盖旧 R3 人工审核文本的边界。 |
"""

from __future__ import annotations

import subprocess
import sys
import plistlib
import json
import os
import time
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


def test_transient_transport_failure_retries_before_failure_notification(tmp_path: Path):
    calls = tmp_path / "calls.log"
    fake_codex = tmp_path / "codex"
    fake_python = tmp_path / "python"
    notifier = tmp_path / "notifier.py"
    _write_executable(
        fake_codex,
        f"#!/usr/bin/env bash\necho codex >> {calls}\necho 'tls handshake eof' >&2\nexit 1\n",
    )
    _write_executable(fake_python, f"#!/usr/bin/env bash\necho notifier >> {calls}\nexit 0\n")
    notifier.write_text("# fake notifier\n", encoding="utf-8")
    log_dir = tmp_path / "logs"
    arguments = [
        sys.executable, str(RUNNER), "--project-root", str(PROJECT_ROOT),
        "--codex-bin", str(fake_codex), "--python-bin", str(fake_python),
        "--notifier-script", str(notifier), "--log-dir", str(log_dir),
        "--lock-dir", str(tmp_path / "lock"), "--max-attempts", "3",
        "--retry-delay-seconds", "0",
    ]

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 1
    call_lines = calls.read_text(encoding="utf-8").splitlines()
    assert call_lines.count("codex") == 3
    assert call_lines.count("notifier") == 1
    run_log = next(log_dir.glob("run_*.log")).read_text(encoding="utf-8")
    assert "Codex transient transport failure" in run_log


def test_transient_failure_with_accepted_review_receipt_does_not_rerun(tmp_path: Path):
    calls = tmp_path / "calls.log"
    project_root = tmp_path / "project"
    project_root.mkdir()
    receipt = project_root / "output" / "english_world_daily" / "2026-08-25" / "example" / "telegram_receipt.json"
    fake_codex = tmp_path / "codex"
    fake_python = tmp_path / "python"
    notifier = tmp_path / "notifier.py"
    _write_executable(
        fake_codex,
        "#!/usr/bin/env bash\n"
        f"echo codex >> {calls}\n"
        f"mkdir -p {receipt.parent}\n"
        f"printf '%s\\n' '{{\"status\": \"ACCEPTED\"}}' > {receipt}\n"
        "echo 'tls handshake eof' >&2\n"
        "exit 1\n",
    )
    _write_executable(fake_python, f"#!/usr/bin/env bash\necho notifier >> {calls}\nexit 0\n")
    notifier.write_text("# fake notifier\n", encoding="utf-8")
    log_dir = project_root / "output" / "english_world_daily"
    arguments = [
        sys.executable, str(RUNNER), "--project-root", str(project_root),
        "--codex-bin", str(fake_codex), "--python-bin", str(fake_python),
        "--notifier-script", str(notifier), "--log-dir", str(log_dir),
        "--lock-dir", str(project_root / "output" / "locks" / "lock"), "--max-attempts", "3",
        "--retry-delay-seconds", "0",
    ]

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 1
    assert calls.read_text(encoding="utf-8").splitlines() == ["codex"]
    status = (log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=COORDINATOR_DELIVERY_UNCERTAIN" in status
    assert str(receipt) in next(log_dir.glob("run_*.log")).read_text(encoding="utf-8")


def test_coordinator_timeout_records_durable_failure_and_does_not_retry(tmp_path: Path):
    calls = tmp_path / "calls.log"
    fake_codex = tmp_path / "codex"
    fake_python = tmp_path / "python"
    notifier = tmp_path / "notifier.py"
    _write_executable(fake_codex, f"#!/usr/bin/env bash\necho codex >> {calls}\nsleep 30\n")
    _write_executable(fake_python, f"#!/usr/bin/env bash\necho notifier >> {calls}\nexit 0\n")
    notifier.write_text("# fake notifier\n", encoding="utf-8")
    log_dir = tmp_path / "logs"
    arguments = [
        sys.executable, str(RUNNER), "--project-root", str(PROJECT_ROOT),
        "--codex-bin", str(fake_codex), "--python-bin", str(fake_python),
        "--notifier-script", str(notifier), "--log-dir", str(log_dir),
        "--lock-dir", str(tmp_path / "lock"), "--max-attempts", "3",
        "--retry-delay-seconds", "0", "--coordinator-timeout-seconds", "1",
    ]

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False, timeout=15)

    assert result.returncode == 124
    assert calls.read_text(encoding="utf-8").splitlines() == ["codex", "notifier"]
    status = (log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=COORDINATOR_TIMED_OUT" in status
    assert "exit_code=124" in status
    run_log = next(log_dir.glob("run_*.log")).read_text(encoding="utf-8")
    assert "terminating its process group" in run_log


def test_stale_pid_lock_is_recovered_before_running_coordinator(tmp_path: Path):
    arguments, calls, log_dir = _runner_arguments(tmp_path, codex_exit=0)
    lock_dir = tmp_path / "lock"
    lock_dir.mkdir()
    (lock_dir / "owner.json").write_text(json.dumps({"pid": 999999, "started_at": "old"}), encoding="utf-8")

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert calls.read_text(encoding="utf-8").splitlines() == ["codex"]
    assert not lock_dir.exists()
    assert "phase=COORDINATOR_FINISHED" in (log_dir / "last_run_status.txt").read_text(encoding="utf-8")


def test_signal_interrupt_writes_status_notifies_and_releases_lock(tmp_path: Path):
    calls = tmp_path / "calls.log"
    fake_codex = tmp_path / "codex"
    fake_python = tmp_path / "python"
    notifier = tmp_path / "notifier.py"
    _write_executable(fake_codex, f"#!/usr/bin/env bash\necho codex >> {calls}\nsleep 30\n")
    _write_executable(fake_python, f"#!/usr/bin/env bash\necho notifier >> {calls}\nexit 0\n")
    notifier.write_text("# fake notifier\n", encoding="utf-8")
    log_dir = tmp_path / "logs"
    lock_dir = tmp_path / "lock"
    arguments = [
        sys.executable, str(RUNNER), "--project-root", str(PROJECT_ROOT),
        "--codex-bin", str(fake_codex), "--python-bin", str(fake_python),
        "--notifier-script", str(notifier), "--log-dir", str(log_dir),
        "--lock-dir", str(lock_dir), "--max-attempts", "1",
        "--retry-delay-seconds", "0", "--coordinator-timeout-seconds", "60",
    ]
    process = subprocess.Popen(arguments, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 5
    while (not lock_dir.exists() or not calls.exists()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert lock_dir.exists()
    assert calls.read_text(encoding="utf-8").splitlines() == ["codex"]

    os.kill(process.pid, 15)
    process.communicate(timeout=15)

    assert process.returncode == 143
    assert calls.read_text(encoding="utf-8").splitlines() == ["codex", "notifier"]
    assert not lock_dir.exists()
    status = (log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=COORDINATOR_INTERRUPTED" in status
    assert "exit_code=143" in status


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
    assert '"--sandbox", "workspace-write"' in runner_text
    assert "sandbox_workspace_write.network_access=true" in runner_text
    assert "--cookies output/youtube_cookies.txt" in runner_text
    assert "覆盖任何旧文档中要求 Telegram 人工 R3 审核" in runner_text
    assert all(command in runner_text for command in ("`ps`", "`tail`", "`sleep`"))

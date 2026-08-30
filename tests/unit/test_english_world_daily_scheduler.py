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
# | 2.10.0 | 2026-08-26 | Codex | 固化协调器仅凭指定机器回执认定 Telegram 交付成功。 |
# | 2.11.0 | 2026-08-27 | Codex | 固化生产代理必须等待通知回执，不得以 PENDING 结束任务。 |
# | 2.12.0 | 2026-08-28 | Codex | 固化受限生产代理只写交付请求，宿主负责标准封面、通知与上传。 |
# | 2.13.0 | 2026-08-29 | Codex | 固化 Telegram 已选候选提示边界及宿主 manual-review-only 强制参数。 |
# | 2.14.0 | 2026-08-30 | Codex | 固化日更候选在完整来源预检前可有界换题、锁定后禁止换题及末屏微笔记梯度。 |
# | 2.15.0 | 2026-08-30 | Codex | 覆盖跨运行候选淘汰账本、旧失败兼容提取与补发显式排除。 |
# | 2.16.0 | 2026-08-30 | Codex | 固化密集自动字幕生成逐词时间轴时的词尾单调不越界要求。 |
# | 2.17.0 | 2026-08-30 | Codex | 覆盖宿主媒体通路预检、Cookie/Clash 恢复分支及预检假阳性候选回退语义。 |
"""

from __future__ import annotations

import subprocess
import sys
import plistlib
import json
import os
import time
from contextlib import contextmanager
from io import StringIO
from pathlib import Path

import pytest

from scripts import run_english_world_daily as runner
from video_processing.utils.youtube_access import YoutubeAccessResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / "scripts" / "run_english_world_daily.py"
PLIST = PROJECT_ROOT / "scripts" / "com.videopipeline.english-world-daily.plist"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _runner_arguments(
    tmp_path: Path,
    *,
    codex_exit: int,
    write_delivery_receipt: bool = False,
    write_delivery_request: bool = False,
) -> tuple[list[str], Path, Path]:
    calls = tmp_path / "calls.log"
    fake_codex = tmp_path / "codex"
    fake_python = tmp_path / "python"
    notifier = tmp_path / "notifier.py"
    log_dir = tmp_path / "logs"
    request_command = (
        "request=\"$ENGLISH_WORLD_DELIVERY_REQUEST_PATH\"\n"
        "mkdir -p \"$(dirname \"$request\")\"\n"
        "printf '%s\\n' '{\"kind\":\"production\",\"title\":\"fixture\",\"mp4\":\""
        + str(PROJECT_ROOT / "pyproject.toml")
        + "\",\"manifest\":\""
        + str(PROJECT_ROOT / "pyproject.toml")
        + "\"}' > \"$request\"\n"
        if write_delivery_request else ""
    )
    receipt_command = (
        "receipt=''\nwhile [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = '--delivery-receipt' ]; then receipt=$2; fi\n"
        "  shift\ndone\n"
        "printf '%s\\n' '{\"kind\":\"review\",\"status\":\"ACCEPTED\"}' > \"$receipt\"\n"
        if write_delivery_receipt else ""
    )
    _write_executable(fake_codex, f"#!/usr/bin/env bash\necho codex >> {calls}\n{request_command}exit {codex_exit}\n")
    _write_executable(fake_python, f"#!/usr/bin/env bash\necho notifier:\"$*\" >> {calls}\n{receipt_command}exit 0\n")
    notifier.write_text("# fake notifier\n", encoding="utf-8")
    arguments = [
        sys.executable, str(RUNNER), "--project-root", str(PROJECT_ROOT),
        "--codex-bin", str(fake_codex), "--python-bin", str(fake_python),
        "--notifier-script", str(notifier), "--log-dir", str(log_dir),
        "--lock-dir", str(tmp_path / "lock"), "--max-attempts", "3",
        "--retry-delay-seconds", "0", "--skip-source-access-preflight",
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
    arguments, calls, log_dir = _runner_arguments(
        tmp_path, codex_exit=0, write_delivery_request=True, write_delivery_receipt=True,
    )

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert [line.split(":", 1)[0] for line in calls.read_text(encoding="utf-8").splitlines()] == ["codex", "notifier"]
    status = (log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=COORDINATOR_FINISHED" in status
    assert "exit_code=0" in status


def test_success_without_machine_delivery_receipt_is_a_durable_failure(tmp_path: Path):
    arguments, calls, log_dir = _runner_arguments(tmp_path, codex_exit=0, write_delivery_request=True)

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 1
    assert len([line for line in calls.read_text(encoding="utf-8").splitlines() if line.startswith("notifier:")]) == 1
    status = (log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=FAILED_DELIVERY_EVIDENCE" in status


def test_host_executes_delivery_after_agent_writes_request(tmp_path: Path):
    """受限生产代理不再运行封面/通知；协调器宿主只消费一次原子请求。"""
    arguments, calls, log_dir = _runner_arguments(
        tmp_path, codex_exit=0, write_delivery_request=True, write_delivery_receipt=True,
    )

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0
    request = next(log_dir.glob("run_*.delivery-request.json"))
    assert json.loads(request.read_text(encoding="utf-8"))["kind"] == "production"
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "codex"
    assert lines[1].startswith("notifier:")


def test_source_access_failure_is_reported_without_launching_candidate_coordinator(monkeypatch, tmp_path: Path):
    codex = tmp_path / "codex"
    notifier = tmp_path / "notifier.py"
    _write_executable(codex, "#!/usr/bin/env bash\nexit 0\n")
    notifier.write_text("# fake notifier\n", encoding="utf-8")
    paths = runner.RuntimePaths(
        project_root=tmp_path,
        codex_home=tmp_path,
        codex_bin=codex,
        python_bin=Path(sys.executable),
        notifier_script=notifier,
        log_dir=tmp_path / "logs",
        lock_dir=tmp_path / "lock",
        coordinator_timeout_seconds=60,
    )
    blocked = YoutubeAccessResult(False, "MEDIA_ACCESS_REJECTED", "HTTP error 403")
    monkeypatch.setattr(
        runner,
        "_preflight_youtube_source_access",
        lambda *_args: (blocked, object(), {"PATH": "/bin"}, False),
    )
    delivered = []
    monkeypatch.setattr(
        runner,
        "_deliver_request_from_host",
        lambda _paths, request, *_args, **_kwargs: (delivered.append(json.loads(request.read_text())) or (1, True)),
    )
    monkeypatch.setattr(
        runner,
        "_run_coordinator",
        lambda *_args, **_kwargs: pytest.fail("source access failure must not launch candidate coordinator"),
    )

    exit_code = runner.run(
        paths,
        max_attempts=1,
        retry_delay_seconds=0,
        source_access_preflight=True,
    )

    assert exit_code == 1
    assert delivered and delivered[0]["kind"] == "failure"
    assert "不是候选质量或换题问题" in delivered[0]["failure"]
    status = (paths.log_dir / "last_run_status.txt").read_text(encoding="utf-8")
    assert "phase=REPORTED_SOURCE_ACCESS_FAILURE" in status


def test_source_access_auth_failure_refreshes_cookie_once_then_reprobes(monkeypatch, tmp_path: Path):
    paths = runner.RuntimePaths(
        project_root=tmp_path,
        codex_home=tmp_path,
        codex_bin=tmp_path / "codex",
        python_bin=Path(sys.executable),
        notifier_script=tmp_path / "notifier.py",
        log_dir=tmp_path / "logs",
        lock_dir=tmp_path / "lock",
        coordinator_timeout_seconds=60,
    )

    class Settings:
        ytdlp_path = "yt-dlp"
        youtube_auth_probe_url = "https://example.test/probe"
        enable_youtube_cookie_auto_refresh = True
        youtube_cookies_file = ""
        youtube_cookie_browser = "chrome"
        clash_download_node = None

        def get_active_proxies(self):
            return {"HTTPS_PROXY": "http://127.0.0.1:7890"}

        def get_yt_cookie_args(self):
            return ["--cookies", "cookies.txt"]

    attempts = iter([
        YoutubeAccessResult(False, "AUTH_REQUIRED", "bot challenge"),
        YoutubeAccessResult(True, "READY"),
    ])
    refresh_calls = []
    monkeypatch.setattr(
        runner,
        "_load_youtube_runtime_dependencies",
        lambda _paths: (
            Settings(),
            lambda **_kwargs: next(attempts),
            lambda *args, **kwargs: refresh_calls.append((args, kwargs)) or type("Result", (), {"ok": True, "code": "REFRESHED"})(),
        ),
    )

    result, _settings, environment, use_clash = runner._preflight_youtube_source_access(paths, StringIO())

    assert result.ok is True
    assert use_clash is False
    assert refresh_calls and refresh_calls[0][1]["environment"] == environment


def test_source_access_media_failure_uses_configured_clash_fallback_once(monkeypatch, tmp_path: Path):
    paths = runner.RuntimePaths(
        project_root=tmp_path,
        codex_home=tmp_path,
        codex_bin=tmp_path / "codex",
        python_bin=Path(sys.executable),
        notifier_script=tmp_path / "notifier.py",
        log_dir=tmp_path / "logs",
        lock_dir=tmp_path / "lock",
        coordinator_timeout_seconds=60,
    )
    switches = []

    class Settings:
        ytdlp_path = "yt-dlp"
        youtube_auth_probe_url = "https://example.test/probe"
        enable_youtube_cookie_auto_refresh = False
        youtube_cookies_file = ""
        youtube_cookie_browser = "chrome"
        clash_download_node = "Japan"

        def get_active_proxies(self):
            return {}

        def get_yt_cookie_args(self):
            return ["--cookies", "cookies.txt"]

        @contextmanager
        def clash_switch_node(self):
            switches.append("entered")
            yield
            switches.append("restored")

    attempts = iter([
        YoutubeAccessResult(False, "MEDIA_ACCESS_REJECTED", "HTTP 403"),
        YoutubeAccessResult(True, "READY"),
    ])
    monkeypatch.setattr(
        runner,
        "_load_youtube_runtime_dependencies",
        lambda _paths: (Settings(), lambda **_kwargs: next(attempts), lambda *_args, **_kwargs: None),
    )

    result, _settings, _environment, use_clash = runner._preflight_youtube_source_access(paths, StringIO())

    assert result.ok is True
    assert use_clash is True
    assert switches == ["entered", "restored"]


def test_manual_production_prompt_binds_selected_candidate_and_forbids_platform_authority(tmp_path: Path):
    prompt = runner._manual_production_prompt(
        {
            "id": "a" * 32,
            "candidate_source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "candidate_youtube_id": "dQw4w9WgXcQ",
            "candidate_source_title": "untrusted title",
            "candidate_source_channel": "CBC Kids News",
            "candidate_duration_sec": 42,
            "candidate_safety_note": "reviewed",
        },
        tmp_path / "delivery.json",
    )

    assert '"youtube_id": "dQw4w9WgXcQ"' in prompt
    assert "禁止重新搜索、换题或制作第二条" in prompt
    assert "不包含视频号投稿授权" in prompt
    assert "manual-review-only" in prompt


def test_daily_prompt_preflights_multiple_candidates_before_locking_one():
    prompt = runner.PROMPT

    assert "来源预检最多依次检查 5 个不同的 `youtube_id`" in prompt
    assert "某个候选预检失败不算已经选题，可以继续下一个" in prompt
    assert "至少一种视频格式可实际下载" in prompt
    assert "针对拟使用的连续片段生成接触表并确认画面适龄" in prompt
    assert "只有完整来源预检已经覆盖“拟用片段的画面与自然语音”后，才锁定第一个合格 `youtube_id`" in prompt
    assert "才构成不可切换的制作承诺" in prompt
    assert "最终仍只允许制作一条成片" in prompt
    assert "来源预检出现假阳性" in prompt
    assert "继续预检剩余候选" in prompt
    assert "HTTP 403 不是自动“换题”信号" in prompt
    assert "两个独立候选都出现 403、DNS、TLS 或超时" in prompt
    assert "不要追加 `--rejected-youtube-id`" in prompt


def test_daily_prompt_matches_terminal_screen_micro_note_tiers():
    prompt = runner.PROMPT

    assert "普通阅读屏至少 8 个微笔记" in prompt
    assert "不超过 12 词为 0 条" in prompt
    assert "13–24 词为 3 条" in prompt
    assert "25–40 词为 5 条" in prompt
    assert "41 词以上为 8 条" in prompt


def test_daily_prompt_requires_monotonic_word_boundaries_before_enrichment():
    prompt = runner.PROMPT

    assert "`word.end <= next_word.start`" in prompt
    assert "不得用固定最短词长覆盖下一词起点" in prompt
    assert "StudyCardContent.from_mapping" in prompt


def test_recent_rejected_candidates_include_structured_and_legacy_failures(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "structured.delivery-request.json").write_text(
        json.dumps({"kind": "production", "rejected_youtube_ids": ["EJ5Sqku_fYc"]}),
        encoding="utf-8",
    )
    (log_dir / "legacy.delivery-request.json").write_text(
        json.dumps({"kind": "failure", "failure": "唯一锁定候选 xewivZQgBMQ 内容级质检失败"}),
        encoding="utf-8",
    )
    (log_dir / "invalid.delivery-request.json").write_text(
        json.dumps({"rejected_youtube_ids": ["not-valid"]}),
        encoding="utf-8",
    )

    assert runner._recent_rejected_youtube_ids(log_dir) == ("EJ5Sqku_fYc", "xewivZQgBMQ")


def test_daily_prompt_injects_machine_exclusions_and_requires_rejection_persistence(tmp_path: Path):
    prompt = runner._daily_production_prompt(
        tmp_path / "delivery.json",
        ("EJ5Sqku_fYc", "xewivZQgBMQ"),
    )

    assert "--rejected-youtube-id '<实际youtube_id>'" in prompt
    assert '["EJ5Sqku_fYc", "xewivZQgBMQ"]' in prompt
    assert "禁止再次下载、锁定或制作" in prompt


def test_delivery_request_recorder_persists_deduplicated_rejected_ids(tmp_path: Path):
    request = tmp_path / "delivery.json"
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts/record_english_world_delivery_request.py"),
            "--request", str(request),
            "--title", "fixture",
            "--failure", "no source",
            "--rejected-youtube-id", "EJ5Sqku_fYc",
            "--rejected-youtube-id", "EJ5Sqku_fYc",
            "--rejected-youtube-id", "xewivZQgBMQ",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(request.read_text(encoding="utf-8"))
    assert payload["rejected_youtube_ids"] == ["EJ5Sqku_fYc", "xewivZQgBMQ"]


def test_manual_host_delivery_forces_notifier_review_only(monkeypatch, tmp_path: Path):
    request_path = tmp_path / "request.json"
    mp4 = tmp_path / "video.mp4"
    manifest = tmp_path / "manifest.json"
    notifier = tmp_path / "notifier.py"
    for path in (mp4, manifest, notifier):
        path.write_text("fixture", encoding="utf-8")
    request_path.write_text(
        json.dumps({
            "kind": "production", "title": "fixture",
            "mp4": str(mp4), "manifest": str(manifest),
        }),
        encoding="utf-8",
    )
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    paths = runner.RuntimePaths(
        project_root=tmp_path, codex_home=tmp_path, codex_bin=tmp_path / "codex",
        python_bin=Path(sys.executable), notifier_script=notifier, log_dir=tmp_path,
        lock_dir=tmp_path / "lock", coordinator_timeout_seconds=1,
    )

    assert runner._deliver_request_from_host(
        paths, request_path, tmp_path / "receipt.json", sys.stdout,
        manual_review_only=True,
    ) == (0, False)
    assert "--manual-review-only" in captured["command"]


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
        "--retry-delay-seconds", "0", "--skip-source-access-preflight",
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
        "--retry-delay-seconds", "0", "--skip-source-access-preflight",
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
        "--skip-source-access-preflight",
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
    arguments, calls, log_dir = _runner_arguments(
        tmp_path, codex_exit=0, write_delivery_request=True, write_delivery_receipt=True,
    )
    lock_dir = tmp_path / "lock"
    lock_dir.mkdir()
    (lock_dir / "owner.json").write_text(json.dumps({"pid": 999999, "started_at": "old"}), encoding="utf-8")

    result = subprocess.run(arguments, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert [line.split(":", 1)[0] for line in calls.read_text(encoding="utf-8").splitlines()] == ["codex", "notifier"]
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
        "--skip-source-access-preflight",
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
    assert "写入请求是本任务的最后一个硬性检查点" in runner_text
    assert "请求缺失、不可解析或 MP4/manifest 路径不完整都表示本次生产未交付" in runner_text
    assert all(command in runner_text for command in ("`ps`", "`tail`", "`sleep`"))

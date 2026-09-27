"""Anti-gravity 自动封面执行器的失败诊断测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 防止 SDK 配额错误被压缩为无产物 |
| 1.1.0 | 2026-09-27 | Codex | 验证 CLI 凭据隔离、工作目录边界、失败与临近截止时间 |
"""

from __future__ import annotations

from scripts.run_antigravity_cover_doer import _diagnostic_text
from scripts import run_antigravity_cover_doer as worker
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import subprocess
import pytest


class Text:
    def __init__(self, *, text: str = "", error: str = "") -> None:
        self.text = text
        self.error = error


def test_diagnostic_text_prefers_tool_error_and_limits_length():
    message = _diagnostic_text([Text(text="visible"), Text(error="RESOURCE_EXHAUSTED")])

    assert "visible" in message
    assert "RESOURCE_EXHAUSTED" in message
    assert len(_diagnostic_text([Text(text="x" * 700)])) == 500


def _generation_inputs(tmp_path, seconds=120):
    task = SimpleNamespace(
        payload={"visual_brief": {"visual_direction": "telescope", "visual_keywords": ["space"]}},
        fallback_after=datetime.now(timezone.utc) + timedelta(seconds=seconds),
    )
    args = SimpleNamespace(agy_bin="agy", model="gemini-3.7-flash-high", timeout_seconds=90)
    return args, task


def test_cli_generation_strips_api_credentials_and_bounds_workspace(tmp_path, monkeypatch):
    args, task = _generation_inputs(tmp_path)
    captured = {}
    monkeypatch.setattr(worker, "build_subprocess_env", lambda **kwargs: {
        "PATH": "/usr/bin", "GEMINI_API_KEY": "test", "GOOGLE_API_KEY": "test",
        "TELEGRAM_BOT_TOKEN": "test",
    })

    def cli(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, '{"status":"SUCCESS","response":"saved"}', '')

    monkeypatch.setattr(worker.subprocess, "run", cli)
    assert worker._generate(args, task, tmp_path) == "saved"
    assert captured["cwd"] == str(tmp_path)
    assert captured["command"][captured["command"].index("--add-dir") + 1] == str(tmp_path)
    assert "GEMINI_API_KEY" not in captured["env"]
    assert "GOOGLE_API_KEY" not in captured["env"]
    assert "TELEGRAM_BOT_TOKEN" not in captured["env"]
    assert "candidate.png" in captured["command"][-1]


def test_cli_failure_preserves_diagnostic(tmp_path, monkeypatch):
    args, task = _generation_inputs(tmp_path)
    monkeypatch.setattr(worker, "build_subprocess_env", lambda **kwargs: {})
    monkeypatch.setattr(worker.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, '', 'image quota exhausted'))
    with pytest.raises(RuntimeError, match="image quota exhausted"):
        worker._generate(args, task, tmp_path)


def test_cli_error_status_cannot_accept_zero_exit(tmp_path, monkeypatch):
    args, task = _generation_inputs(tmp_path)
    monkeypatch.setattr(worker, "build_subprocess_env", lambda **kwargs: {})
    monkeypatch.setattr(worker.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 0, '{"status":"ERROR","response":"quota blocked"}', ''))
    with pytest.raises(RuntimeError, match="quota blocked"):
        worker._generate(args, task, tmp_path)


def test_cli_does_not_start_when_validation_time_is_missing(tmp_path):
    args, task = _generation_inputs(tmp_path, seconds=5)
    with pytest.raises(RuntimeError, match="insufficient time"):
        worker._generate(args, task, tmp_path)

"""子进程环境工厂与跨进程传参单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-18 | Antigravity | 覆盖 build_subprocess_env 代理过滤、密钥注入、PATH/PYTHONPATH 保证及 cover_generator --payload-file 参数 |
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from config.settings import settings
from video_processing.utils.subprocess_env import PROXY_KEYS, build_subprocess_env
from video_processing.pipeline_manager import _build_subprocess_env


def test_build_subprocess_env_default_injections(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test_gemini_key_abc")
    monkeypatch.setattr(settings, "telegram_bot_token", "test_tg_token_123")
    monkeypatch.setattr(settings, "telegram_chat_id", "-100123456")
    monkeypatch.setattr(settings, "telegram_admin_ids", "111,222")

    env = build_subprocess_env(extra_env={"CUSTOM_KEY": "custom_value"})

    assert env["GEMINI_API_KEY"] == "test_gemini_key_abc"
    assert env["TELEGRAM_BOT_TOKEN"] == "test_tg_token_123"
    assert env["TELEGRAM_CHAT_ID"] == "-100123456"
    assert env["TELEGRAM_ADMIN_IDS"] == "111,222"
    assert env["CUSTOM_KEY"] == "custom_value"

    # PATH 保证
    path_segments = env["PATH"].split(":")
    assert str(settings.project_root / ".venv" / "bin") in path_segments
    assert "/opt/homebrew/bin" in path_segments
    assert "/usr/local/bin" in path_segments

    # PYTHONPATH 保证
    assert str(settings.project_root / "src") in env["PYTHONPATH"]


def test_build_subprocess_env_proxy_filtering(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://old-proxy:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://old-proxy:1080")

    monkeypatch.setattr(type(settings), "get_active_proxies", lambda self: {"HTTP_PROXY": "http://127.0.0.1:7890"})

    env = build_subprocess_env(include_proxies=True)
    assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert "ALL_PROXY" not in env


def test_pipeline_manager_delegates_to_subprocess_env(monkeypatch):
    called = False

    def fake_builder(**kwargs):
        nonlocal called
        called = True
        return {"TEST_ENV": "1"}

    monkeypatch.setattr("video_processing.pipeline_manager.build_subprocess_env", fake_builder)
    res = _build_subprocess_env()
    assert called is True
    assert res == {"TEST_ENV": "1"}


def test_cover_generator_payload_file(tmp_path: Path):
    payload_file = tmp_path / "test_payload.json"
    payload_data = {
        "title": "测试封面标题",
        "audio_edition": "original_audio_subtitled",
    }
    payload_file.write_text(json.dumps(payload_data, ensure_ascii=False), encoding="utf-8")
    output_cover = tmp_path / "test_cover.jpg"

    script_path = settings.project_root / "scripts" / "cover_generator.py"
    # 调用 cover_generator 并使用 --payload-file
    cmd = [
        sys.executable,
        str(script_path),
        "--payload-file",
        str(payload_file),
        "--output",
        str(output_cover),
    ]
    env = build_subprocess_env()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    assert output_cover.is_file()

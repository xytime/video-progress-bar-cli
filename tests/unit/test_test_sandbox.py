"""测试入口隔离的真实进程与路径契约。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 验证收集前拒绝、默认数据库位置、配置清除、网络与子进程拒绝 |
"""

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("test_sandbox_runner", ROOT / "scripts/run_isolated_tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_default_constructors_stay_in_snapshot():
    from video_processing.db.database import PipelineDB
    from video_processing.pipeline_manager import PipelineManager
    import web.app

    database = PipelineDB()
    manager = PipelineManager()
    expected = ROOT / "output/pipeline.db"
    assert Path(database.db_path).resolve() == expected
    assert Path(manager.db.db_path).resolve() == expected
    assert Path(web.app.db.db_path).resolve() == expected
    assert manager._OUT_DIR.resolve() == ROOT / "output"
    assert manager._ORIG_VIDEO_DIR.resolve().is_relative_to(ROOT)
    assert expected.is_file()


def test_default_configuration_has_no_host_credentials():
    from config.settings import settings

    assert not (ROOT / ".env").exists()
    assert not settings.telegram_bot_token
    assert not settings.pipeline_internal_api_token
    assert not settings.youtube_data_api_key


def test_os_denies_external_read_write_and_child_access(tmp_path):
    marker = json.loads((ROOT / runner.MARKER).read_text())
    canary = Path(marker["canary"])
    with pytest.raises(PermissionError):
        canary.read_bytes()
    with pytest.raises(PermissionError):
        canary.write_text("unsafe")
    link = tmp_path / "outside-link"
    link.symlink_to(canary)
    with pytest.raises(PermissionError):
        link.read_bytes()
    with pytest.raises(PermissionError):
        link.write_text("unsafe")
    result = subprocess.run(
        [sys.executable, "-I", "-c", f"from pathlib import Path; Path({str(canary)!r}).read_bytes()"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "PermissionError" in result.stderr


def test_os_denies_network_in_parent_and_child():
    with socket.socket() as sock:
        with pytest.raises(PermissionError):
            sock.bind(("127.0.0.1", 0))
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import socket; socket.socket().bind(('127.0.0.1',0))"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "PermissionError" in result.stderr


@pytest.mark.parametrize("fake_marker", [False, True])
def test_uncontained_collection_refuses_before_config_import(tmp_path, fake_marker):
    evidence = tmp_path / "video-pytest-uncontained"
    tmp_path = evidence / "sandbox/repo"
    tmp_path.mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/conftest.py").write_text((ROOT / "tests/conftest.py").read_text())
    (tmp_path / "tests/test_example.py").write_text("def test_example(): pass\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/__init__.py").write_text("")
    sentinel = tmp_path / "unsafe-config-loaded"
    (tmp_path / "config/settings.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\nsettings = None\n"
    )
    if fake_marker:
        canary = evidence / "outside-canary.txt"
        canary.write_text("probe")
        (tmp_path / runner.MARKER).write_text(json.dumps({
            "schema": 1, "repo": str(tmp_path), "canary": str(canary), "run_root": str(tmp_path.parent),
        }))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-c", "/dev/null", "tests"],
        cwd=tmp_path, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 4
    assert "run_isolated_tests.py" in result.stderr
    assert not sentinel.exists()


def test_snapshot_excludes_runtime_and_env_variants(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    names = ["src/example.py", "config/.env.production", ".env", "output/pipeline.db", ".env.example"]
    for name in names:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **kw: "\0".join(names).encode())
    manifest = runner.snapshot(source, destination)
    assert set(manifest) == {"src/example.py", ".env.example"}
    assert set(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()) == set(manifest)


def test_snapshot_rejects_symlink_before_read(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "external.py").write_text("fixture")
    (tmp_path / "src/linked.py").symlink_to(tmp_path / "external.py")
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **kw: b"src/linked.py")
    with pytest.raises(ValueError, match="符号链接"):
        runner.snapshot(tmp_path, tmp_path / "destination")


def test_child_environment_does_not_inherit_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-secret")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--unsafe-plugin")
    child = runner.child_environment(tmp_path / "repo", tmp_path)
    assert "TELEGRAM_BOT_TOKEN" not in child
    assert "PYTEST_ADDOPTS" not in child
    assert child["HOME"] == str(Path.home())
    assert child["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_timeout_reports_failure_and_reaps_child(tmp_path):
    pid_file = tmp_path / "child.pid"
    code = f"import os,time; open({str(pid_file)!r},'w').write(str(os.getpid())); time.sleep(60)"
    result = runner.run_child([sys.executable, "-c", code], tmp_path, dict(os.environ), tmp_path / "log", 0.3)
    assert result["exit_code"] == 124
    assert pid_file.is_file()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)

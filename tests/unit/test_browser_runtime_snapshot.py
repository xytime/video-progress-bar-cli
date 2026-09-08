"""浏览器包复制的文件边界契约，不启动浏览器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 验证包内链接拒绝与快照独立性，保持默认单测不需浏览器 |
"""

import hashlib
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "browser_snapshot", Path(__file__).resolve().parents[2] / "scripts/test_browser_runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_browser_snapshot_is_independent_and_hashes_copied_bytes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    data = b"synthetic browser dependency"
    executable = source / "shell"
    executable.write_bytes(data)
    executable.chmod(0o755)
    manifest = runtime.copy_browser(source, target)
    executable.write_bytes(b"source changed after snapshot")
    assert (target / "shell").read_bytes() == data
    assert (target / "shell").stat().st_mode & 0o777 == 0o755
    assert manifest == {"shell": {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}}


@pytest.mark.parametrize("directory", [False, True])
def test_browser_snapshot_refuses_symlinks(tmp_path, directory):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    if directory:
        outside.mkdir()
        (outside / "dependency").write_text("fixture")
    else:
        outside.write_text("fixture")
    (source / "dependency-link").symlink_to(outside, target_is_directory=directory)
    with pytest.raises(ValueError, match="链接"):
        runtime.copy_browser(source, tmp_path / "target")


def test_missing_playwright_refuses_without_install_or_skip(monkeypatch):
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(ValueError, match="未安装 Playwright"):
        runtime.installed_browser()

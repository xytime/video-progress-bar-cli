"""离线模型准备的真实文件边界和失败契约。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 验证独立副本、校验失败删除副本、缺模型/链接/包拒绝 |
"""

import hashlib
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "media_snapshot", Path(__file__).resolve().parents[2] / "scripts/test_media_runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_model_copy_is_independent_and_validates_actual_bytes(tmp_path):
    source, target = tmp_path / "source.pt", tmp_path / "copy/model.pt"
    content = b"synthetic model fixture"
    source.write_bytes(content)
    record = runtime.copy_model(source, target, hashlib.sha256(content).hexdigest())
    source.write_bytes(b"changed")
    assert target.read_bytes() == content
    assert record["sha256"] == hashlib.sha256(content).hexdigest()
    assert record["bytes"] == len(content)


def test_corrupt_model_refuses_and_removes_only_copy(tmp_path):
    source, target = tmp_path / "source.pt", tmp_path / "copy/model.pt"
    source.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="SHA256"):
        runtime.copy_model(source, target, "0" * 64)
    assert not target.exists()
    assert source.read_bytes() == b"corrupt"


@pytest.mark.parametrize("kind", ["absent", "directory", "symlink"])
def test_non_regular_model_is_refused(tmp_path, kind):
    source = tmp_path / "model.pt"
    if kind == "directory":
        source.mkdir()
    elif kind == "symlink":
        actual = tmp_path / "actual.pt"
        actual.write_bytes(b"synthetic")
        source.symlink_to(actual)
    with pytest.raises(ValueError, match="常规离线模型"):
        runtime.copy_model(source, tmp_path / "copy.pt", "0" * 64)


def test_missing_whisper_refuses_without_import_or_download(monkeypatch):
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(ValueError, match="未安装 Whisper"):
        runtime.installed_models()

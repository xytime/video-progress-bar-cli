"""D05/D08：真实 Git 仓库、dirty 三方产物及未跟踪源码保留。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 已测清单绑定与采用失败保护 |
"""
from pathlib import Path
import subprocess
import pytest
from video_processing.core.deployment import DeploymentDenied, write_json
from video_processing.core.deployment_sources import prepare, Sources, runtime_manifest, sha, git


def commit(root, message):
    git(root, "add", ".")
    git(root, "-c", "user.name=Isolation", "-c", "user.email=isolation@invalid", "-c", "commit.gpgsign=false", "commit", "-m", message)
    return git(root, "rev-parse", "HEAD").decode().strip()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "src").mkdir()
    (root / "scripts").mkdir()
    (root / "vpanel").write_text("wrapper\n")
    (root / "src/app.py").write_text("old\n")
    (root / "src/unrelated.py").write_text("other\n")
    old = commit(root, "baseline")
    (root / "src/app.py").write_text("target\n")
    (root / "scripts/deploy.py").write_text("entry\n")
    target = commit(root, "target")
    git(root, "reset", "--hard", old)  # 仅临时仓库构造 fixture。
    (root / "scripts").mkdir(exist_ok=True)
    (root / "src/app.py").write_text("old plus user work\n")
    (root / "src/unrelated.py").write_text("untouched dirty\n")
    (root / "scripts/user.py").write_text("untouched untracked\n")
    overlay = tmp_path / "overlay"
    (overlay / "src").mkdir(parents=True)
    (overlay / "src/app.py").write_text("target plus user work\n")
    expected = runtime_manifest(root)
    expected.update({"src/app.py": sha((overlay / "src/app.py").read_bytes()), "scripts/deploy.py": sha(b"entry\n")})
    manifest = tmp_path / "tested.json"
    write_json(manifest, expected)
    return root, target, overlay, manifest


def test_d08_real_fast_forward_preserves_dirty_overlay_and_untracked(checkout, tmp_path):
    root, target, overlay, manifest = checkout
    plan = prepare(root, target, tmp_path / "private", manifest, overlay)
    sources = Sources(root, tmp_path / "private", plan)
    sources.adopt()
    sources.final()
    assert (root / "src/app.py").read_text() == "target plus user work\n"
    assert (root / "src/unrelated.py").read_text() == "untouched dirty\n"
    assert (root / "scripts/user.py").read_text() == "untouched untracked\n"
    assert git(root, "rev-parse", "HEAD").decode().strip() == target


@pytest.mark.parametrize("damage", ["source", "payload", "untracked", "staged"])
def test_d05_plan_drift_refuses_before_adopt(checkout, tmp_path, damage):
    root, target, overlay, manifest = checkout
    directory = tmp_path / "private"
    plan = prepare(root, target, directory, manifest, overlay)
    before = git(root, "rev-parse", "HEAD")
    if damage == "source":
        (root / "src/unrelated.py").write_text("new concurrent edit")
    elif damage == "payload":
        (directory / "payload/src/app.py").write_text("not tested")
    elif damage == "untracked":
        (root / "scripts/new.py").write_text("new source")
    else:
        git(root, "add", "src/unrelated.py")
    with pytest.raises(DeploymentDenied):
        Sources(root, directory, plan).adopt()
    assert git(root, "rev-parse", "HEAD") == before
    assert (root / "src/app.py").read_text() == "old plus user work\n"


def test_d08_missing_overlay_and_unverified_manifest_refuse(checkout, tmp_path):
    root, target, overlay, manifest = checkout
    with pytest.raises(DeploymentDenied, match="TESTED_OVERLAY_REQUIRED"):
        prepare(root, target, tmp_path / "first", manifest)
    write_json(manifest, {})
    with pytest.raises(DeploymentDenied, match="TESTED_SOURCE_MISMATCH"):
        prepare(root, target, tmp_path / "second", manifest, overlay)


def test_d08_secret_path_not_read(checkout, tmp_path):
    root, target, overlay, manifest = checkout
    (root / ".env").write_text("fixture-only")
    commit(root, "fixture secret")
    (root / ".env").write_text("changed fixture")
    with pytest.raises(DeploymentDenied, match="SECRET_OR_RUNTIME_PATH_REFUSED"):
        prepare(root, target, tmp_path / "private", manifest, overlay)

"""测试副本回收与宿主证据保留，不导入生产运行配置。"""

import importlib.util
import json
from pathlib import Path
import sys

import pytest


spec = importlib.util.spec_from_file_location(
    "sandbox_lifecycle_runner", Path(__file__).resolve().parents[2] / "scripts/run_isolated_tests.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize("outcome", [0, 1, "prepare-error", "interrupt", "timeout"])
def test_all_exit_paths_remove_copy_and_retain_evidence(tmp_path, monkeypatch, outcome):
    evidence = tmp_path / "video-pytest-lifecycle"
    evidence.mkdir()
    monkeypatch.setattr(runner, "create_evidence", lambda: evidence)

    def execute(args, source, directory, receipt):
        root = directory / "sandbox"
        root.mkdir()
        (root / "repo").mkdir()
        (root / "repo/source.py").write_text("synthetic source")
        (root / "pytest.xml").write_text("<testsuites/>")
        (directory / "pytest.log").write_text("synthetic test log")
        (directory / "source-manifest.json").write_text("{}")
        if outcome == "prepare-error":
            raise ValueError("synthetic snapshot failure")
        if outcome == "interrupt":
            raise KeyboardInterrupt
        if outcome == "timeout":
            result = runner.run_child([sys.executable, "-c", "import time; time.sleep(30)"],
                                      root, runner.child_environment(root / "repo", root),
                                      directory / "pytest.log", 0.1)
            receipt["pytest"] = result
            return result["exit_code"]
        return outcome

    monkeypatch.setattr(runner, "execute_run", execute)
    expected = {"prepare-error": 2, "interrupt": 130, "timeout": 124}.get(outcome, outcome)
    assert runner.main([]) == expected
    assert not (evidence / "sandbox").exists()
    assert (evidence / "pytest.log").is_file()
    assert (evidence / "pytest.xml").read_text() == "<testsuites/>"
    assert (evidence / "source-manifest.json").is_file()
    receipt = json.loads((evidence / "receipt.json").read_text())
    assert receipt["cleanup"]["status"] == "removed"
    assert receipt["exit_code"] == expected
    assert receipt["finished_at"]


def test_cleanup_does_not_follow_copy_symlinks(tmp_path):
    evidence = tmp_path / "video-pytest-links"
    root = evidence / "sandbox"
    root.mkdir(parents=True)
    outside = tmp_path / "kept"
    outside.mkdir()
    (outside / "source.py").write_text("kept")
    (root / "venv-link").symlink_to(outside, target_is_directory=True)
    (root / "pytest.xml").symlink_to(outside / "source.py")
    assert runner.finish_run(evidence, {"exit_code": 0})
    assert (outside / "source.py").read_text() == "kept"
    assert not root.exists()
    assert not (evidence / "pytest.xml").exists()


def test_explicit_debug_retention_keeps_copy(tmp_path):
    evidence = tmp_path / "video-pytest-debug"
    (evidence / "sandbox").mkdir(parents=True)
    assert runner.finish_run(evidence, {"exit_code": 1}, keep_sandbox=True)
    assert (evidence / "sandbox").is_dir()
    assert json.loads((evidence / "receipt.json").read_text())["cleanup"]["status"] == "retained"


def test_missing_mount_refuses_before_creating_directory(tmp_path, monkeypatch):
    missing = tmp_path / "unmounted-volume"
    monkeypatch.setattr(runner, "TEST_VOLUME", missing)
    monkeypatch.setattr(runner, "TEST_RUNS", missing / "TestRuns")
    with pytest.raises(ValueError, match="未挂载"):
        runner.create_evidence()
    assert not missing.exists()


def test_cleanup_failure_is_recorded_without_following_root_link(tmp_path):
    evidence = tmp_path / "video-pytest-refused"
    evidence.mkdir()
    outside = tmp_path / "kept"
    outside.mkdir()
    (evidence / "sandbox").symlink_to(outside, target_is_directory=True)
    receipt = {"exit_code": 0}
    assert not runner.finish_run(evidence, receipt)
    assert outside.is_dir()
    assert receipt["cleanup"]["status"] == "failed"
    assert receipt["exit_code"] == 3

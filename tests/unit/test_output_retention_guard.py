"""清理宿主边界测试：真实临时树和维护锁，不接触生产进程或磁盘设置。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 挂载漂移、事实来源失败、进程归属与维护锁竞争反例 |
"""
from pathlib import Path
import fcntl
import os
import plistlib
import subprocess

import pytest

from video_processing.core.maintenance import MaintenanceGate
from video_processing.core.output_retention_guard import RetentionHostGuard, RetentionGuardDenied


VOLUME_UUID = "F09BC95D-B996-4971-8F99-9780C25FCC89"


class Commands:
    def __init__(self, volume, project, output, store):
        self.volume, self.project, self.output, self.store = volume, project, output, store
        self.calls = []
        self.volume_uuid = VOLUME_UUID
        self.mount_point = str(volume)
        self.fail = None
        self.warning = None
        self.tracked = b""
        self.lsof = (f"p123\0\nfcwd\0n{project}\0\nf3\0n{output / 'old.mp4'}\0\n"
                     f"p456\0\nf4\0n{store / 'item/payload/cache.jpg'}\0\n").encode()
        self.ps = (f"123 1 python /python scripts/auto.py --token=secret\n"
                   "456 1 node /usr/bin/node service.js\n").encode()

    def __call__(self, arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        kind = Path(arguments[0]).name
        if self.fail == kind:
            return subprocess.CompletedProcess(arguments, 1, b"", b"secret failure")
        if kind == "diskutil":
            data = plistlib.dumps({"VolumeUUID": self.volume_uuid, "MountPoint": self.mount_point})
        elif kind == "lsof":
            data = self.lsof
        elif kind == "ps":
            data = self.ps
        else:
            data = self.tracked
        return subprocess.CompletedProcess(arguments, 0, data,
                                           b"incomplete secret" if self.warning == kind else b"")


@pytest.fixture
def setup_guard(tmp_path, monkeypatch):
    volume = tmp_path / "external"
    project = volume / "project"
    output = project / "output"
    store = volume / "staging"
    output.mkdir(parents=True)
    store.mkdir()
    monkeypatch.setattr(Path, "is_mount", lambda path: path == volume)
    gate = MaintenanceGate(output / "maintenance.json")
    initial = gate.enter("测试初始化")
    gate.resume(initial["version"], validated=True)
    runner = Commands(volume, project, output, store)
    guard = RetentionHostGuard(project, output, volume, VOLUME_UUID, gate,
                               store_root=store, runner=runner)
    return guard, runner, gate


def test_capture_matches_exact_volume_paths_and_redacts_process_arguments(setup_guard):
    guard, runner, _ = setup_guard
    runner.tracked = b"output/versioned.jpg\0"
    result = guard.capture()
    assert result["status"] == "OK"
    assert result["mount"]["volume_uuid"] == VOLUME_UUID
    assert result["tracked_paths"] == [str(guard.output_root / "versioned.jpg")]
    assert result["open_references"] == [
        {"pid": 123, "path": str(guard.output_root / "old.mp4")},
        {"pid": 456, "path": str(guard.store_root / "item/payload/cache.jpg")},
    ]
    assert result["busy_processes"] == [{"pid": 123, "ppid": 1,
                                         "kinds": ["PROJECT_PYTHON_WORKER"]}]
    assert "secret" not in str(result)
    command, kwargs = runner.calls[-1]
    assert command[:4] == ["git", "--no-optional-locks", "-c", "core.fsmonitor=false"]
    assert "env" not in kwargs
    assert kwargs["cwd"] == guard.project_root


def test_missing_actual_mount_does_not_accept_same_named_directory(setup_guard, monkeypatch):
    guard, runner, _ = setup_guard
    monkeypatch.setattr(Path, "is_mount", lambda path: False)
    assert guard.capture()["unknown_reasons"] == ["VOLUME_BOUNDARY_INVALID"]
    assert not runner.calls


@pytest.mark.parametrize("change", ["uuid", "mount"])
def test_volume_identity_drift_refuses_capture(setup_guard, change):
    guard, runner, _ = setup_guard
    if change == "uuid":
        runner.volume_uuid = "different-volume"
    else:
        runner.mount_point = str(guard.volume_root / "wrong")
    assert guard.capture()["unknown_reasons"] == ["VOLUME_IDENTITY_MISMATCH"]
    assert len(runner.calls) == 1


def test_symlink_ancestor_refuses_even_when_target_is_same_volume(setup_guard):
    guard, runner, _ = setup_guard
    alias = guard.volume_root / "alias"
    alias.symlink_to(guard.project_root, target_is_directory=True)
    guard.output_root = alias / "output"
    assert guard.capture()["unknown_reasons"] == ["HOST_PATH_SYMLINK"]
    assert not runner.calls


@pytest.mark.parametrize("kind", ["diskutil", "lsof", "ps", "git"])
def test_tool_failure_is_unknown_and_never_means_no_references(setup_guard, kind):
    guard, runner, _ = setup_guard
    runner.fail = kind
    result = guard.capture()
    assert result["status"] == "UNKNOWN"
    assert result["unknown_reasons"] == ["HOST_COMMAND_FAILED"]
    assert "secret" not in str(result)


def test_lsof_warning_and_unparseable_processes_fail_closed(setup_guard):
    guard, runner, _ = setup_guard
    runner.warning = "lsof"
    assert guard.capture()["unknown_reasons"] == ["OPEN_FILES_INCOMPLETE"]
    runner.warning = None
    runner.ps = b"not-a-process-row\n"
    assert guard.capture()["unknown_reasons"] == ["PROCESS_CAPTURE_UNKNOWN"]


def test_lsof_null_fields_preserve_newline_in_file_name(setup_guard):
    guard, runner, _ = setup_guard
    name = str(guard.output_root / "line\nbreak.mp4")
    runner.lsof = f"p123\0\nf3\0n{name}\0\n".encode()
    runner.ps = b"123 1 python /usr/bin/python service.py\n"
    result = guard.capture()
    assert result["status"] == "OK"
    assert result["open_references"] == [{"pid": 123, "path": name}]


@pytest.mark.parametrize("payload", [b"p123\n", b"p123\0\nf3\0n/path\n", b"f3\0n/path\0\n"])
def test_lsof_truncated_or_unowned_records_are_unknown(setup_guard, payload):
    guard, runner, _ = setup_guard
    runner.lsof = payload
    assert guard.capture()["unknown_reasons"] == ["OPEN_FILES_UNKNOWN"]


def test_only_owned_business_processes_block_idle_capture(setup_guard):
    guard, runner, _ = setup_guard
    runner.ps = (f"123 1 python python -m cli.main auto-caption\n"
                 f"901 1 python python {guard.project_root}/scripts/render_clip.py\n"
                 f"902 1 python python {guard.project_root}/scripts/bot_daemon.py\n"
                 "903 1 python python /other/project/scripts/render_clip.py\n").encode()
    result = guard.capture()
    assert {row["pid"] for row in result["busy_processes"]} == {123, 901}


@pytest.mark.parametrize("tracked", [b"elsewhere/file\0", b"output/../secret\0", b"output/file"])
def test_git_paths_cannot_escape_output_or_hide_truncated_records(setup_guard, tracked):
    guard, runner, _ = setup_guard
    runner.tracked = tracked
    assert guard.capture()["status"] == "UNKNOWN"


def test_exclusive_idle_holds_same_admission_lock_without_state_change(setup_guard):
    guard, _, gate = setup_guard
    before = gate.path.read_bytes()
    with guard.exclusive_idle():
        with gate.path.with_suffix(".lock").open("a+") as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert gate.path.read_bytes() == before
    with gate.admit("new-work", "video"):
        pass
    assert gate.path.read_bytes() == before


def test_active_or_unknown_admission_never_enters_file_operation(setup_guard):
    guard, _, gate = setup_guard
    with gate.admit("render", "video"):
        with pytest.raises(RetentionGuardDenied, match="MAINTENANCE_BUSY"):
            with guard.exclusive_idle():
                pytest.fail("在途任务期间不得操作文件")
    gate.directory.mkdir(exist_ok=True)
    (gate.directory / "unrecognized").touch()
    with pytest.raises(RetentionGuardDenied, match="MAINTENANCE_LEASE_UNKNOWN"):
        with guard.exclusive_idle():
            pytest.fail("未知记录不能当作空闲")


def test_maintenance_or_missing_control_never_changes_state(setup_guard):
    guard, _, gate = setup_guard
    gate.enter("正在维护")
    before = gate.path.read_bytes()
    with pytest.raises(RetentionGuardDenied, match="MAINTENANCE_NOT_RUNNING"):
        with guard.exclusive_idle():
            pass
    assert gate.path.read_bytes() == before
    gate.path.unlink()
    with pytest.raises(RetentionGuardDenied):
        with guard.exclusive_idle():
            pass
    assert not gate.path.exists()


def test_own_retention_process_is_not_reported_as_busy(setup_guard):
    guard, runner, _ = setup_guard
    runner.ps = f"{os.getpid()} 1 python python {guard.project_root}/scripts/output_retention.py\n".encode()
    assert guard.capture()["busy_processes"] == []

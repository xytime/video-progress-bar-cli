"""M01–M07：真实跨进程准入与临时 SQLite；不接触生产来源。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 持久化、竞争、等待项与 CAS 恢复验收 |
"""
import json
import fcntl
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import pytest
from video_processing.core.maintenance import MaintenanceGate, MaintenanceDenied

WORKER = Path(__file__).parents[1] / "helpers/maintenance_worker.py"


def test_m01_restart_never_clears_maintenance(tmp_path):
    path = tmp_path / "control.json"
    control = MaintenanceGate(path)
    expected = control.enter("隔离维护")
    crashed = subprocess.run([sys.executable, str(WORKER), "crash", str(path), "unused"], timeout=10)
    assert crashed.returncode == 42
    for _ in range(4):
        result = subprocess.run([sys.executable, str(WORKER), "status", str(path), "unused"],
                                capture_output=True, text=True, timeout=10, check=True)
        observed = json.loads(result.stdout)
        assert observed["state"] == "MAINTENANCE"
        assert observed["version"] == expected["version"]
        with pytest.raises(MaintenanceDenied):
            with MaintenanceGate(path).admit("restart", "never"):
                pytest.fail("维护期间不应接纳")


def test_m02_m03_real_processes_drain_current_never_claim_next(tmp_path):
    path = tmp_path / "control.json"
    control = MaintenanceGate(path)
    initial = control.enter("初始化")
    control.resume(initial["version"], validated=True)
    markers = [str(tmp_path / f"worker-{i}") for i in range(4)]
    workers = [subprocess.Popen([sys.executable, str(WORKER), "work", str(path), marker],
               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for marker in markers]
    try:
        deadline = time.monotonic() + 10
        while not all(Path(marker + ".ready").exists() for marker in markers):
            assert time.monotonic() < deadline
            time.sleep(.01)
        paused = control.enter("竞争窗口关闭")
        observed = control.status()
        assert observed["phase"] == "DRAINING"
        assert len(observed["active"]) == 4
        with pytest.raises(MaintenanceDenied):
            control.resume(paused["version"], validated=True)
        for marker in markers:
            Path(marker + ".release").touch()
        for process in workers:
            out, err = process.communicate(timeout=10)
            assert process.returncode == 0, err
            assert json.loads(out) == {"item": 1, "code": "MAINTENANCE"}
        with sqlite3.connect(str(path) + ".test.db") as db:
            rows = db.execute("SELECT item,state FROM work").fetchall()
        assert rows == [(0, "FINISHED")] * 4
        assert control.status()["phase"] == "IDLE"
    finally:
        for marker in markers:
            Path(marker + ".release").touch()
        for process in workers:
            process.communicate(timeout=10)


def test_m02_waiting_admission_is_counted_and_cancelled_before_start(tmp_path):
    control = MaintenanceGate(tmp_path / "control.json")
    state = control.enter("初始化")
    control.resume(state["version"], validated=True)
    with control.admit("resource-waiter", "video-A") as ticket:
        assert control.status()["active"][0]["phase"] == "WAITING"
        control.enter("暂停等待项")
        with pytest.raises(MaintenanceDenied):
            ticket.start()
        assert control.status()["phase"] == "DRAINING"
    assert control.status()["phase"] == "IDLE"


@pytest.mark.parametrize("damage", ["missing", "corrupt", "directory"])
def test_m05_unknown_refuses_work_and_resume(tmp_path, damage):
    path = tmp_path / "control.json"
    control = MaintenanceGate(path)
    if damage == "corrupt":
        path.write_text("{")
    elif damage == "directory":
        path.mkdir()
    assert control.status()["state"] == "UNKNOWN"
    with pytest.raises(MaintenanceDenied):
        control.require_running()
    with pytest.raises(MaintenanceDenied):
        control.resume(1, validated=True)


def test_m07_idempotent_enter_stale_resume_and_unverified_sources(tmp_path):
    control = MaintenanceGate(tmp_path / "control.json")
    state = control.enter("初始化")
    assert control.enter("重复暂停") == state
    with pytest.raises(MaintenanceDenied, match="维护状态"):
        control.resume(state["version"])
    running = control.resume(state["version"], validated=True)
    assert running["version"] == state["version"] + 1
    with pytest.raises(MaintenanceDenied) as failure:
        control.resume(state["version"], validated=True)
    assert failure.value.code == "VERSION_CONFLICT"


def test_m07_two_process_cas_and_idempotent_enter(tmp_path):
    path = tmp_path / 'control.json'
    control = MaintenanceGate(path)
    initial = control.enter('并发恢复')
    def race(action, argument):
        processes = [subprocess.Popen([sys.executable, str(WORKER), action, str(path), str(argument)],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        values = []
        for process in processes:
            out, err = process.communicate(timeout=10)
            assert process.returncode == 0, err
            values.append(json.loads(out))
        return values
    resumed = race('resume', initial['version'])
    assert sum(row.get('state') == 'RUNNING' for row in resumed) == 1
    assert sum(row.get('code') == 'VERSION_CONFLICT' for row in resumed) == 1
    paused = race('enter', 'unused')
    assert paused[0] == paused[1]
    assert paused[0]['version'] == initial['version'] + 2


def test_m02_actual_resource_waiter_rechecks_after_lock(tmp_path):
    control = MaintenanceGate(tmp_path / "control.json")
    state = control.enter("初始化")
    control.resume(state["version"], validated=True)
    marker = str(tmp_path / "waiting")
    with Path(marker + ".lock").open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        process = subprocess.Popen([sys.executable, str(WORKER), "wait-resource", str(control.path), marker],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not Path(marker + ".ready").exists():
                assert time.monotonic() < deadline
                time.sleep(.01)
            assert control.status()["active"][0]["phase"] == "WAITING"
            control.enter("等待时维护")
            fcntl.flock(held, fcntl.LOCK_UN)
            out, err = process.communicate(timeout=10)
            assert process.returncode == 0, err
            assert json.loads(out) == {"code": "MAINTENANCE"}
            assert not Path(marker + ".begun").exists()
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
            process.communicate(timeout=10)
    assert control.status()["phase"] == "IDLE"


def test_m05_unreadable_control_and_lease_directory_are_unknown(tmp_path):
    control = MaintenanceGate(tmp_path / "control.json")
    control.enter("隔离")
    control.path.chmod(0)
    try:
        assert control.status()["state"] == "UNKNOWN"
        with pytest.raises(MaintenanceDenied): control.resume(1, validated=True)
    finally:
        control.path.chmod(0o600)
    control.directory.mkdir()
    control.directory.chmod(0)
    try:
        assert control.status()["state"] == "UNKNOWN"
    finally:
        control.directory.chmod(0o700)

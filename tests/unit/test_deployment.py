"""D01–D07：真实文件日志与跨进程互斥，失败后不产生后续副作用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 逐步拒绝、崩溃恢复、备份 WAL 和日志故障 |
"""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest
from video_processing.core.deployment import Deployment, DeploymentDenied, STEPS, project_lock, read_json, write_json
from video_processing.db.database import PipelineDB


class Adapter:
    def __init__(self, root, failure=None, phase="action", kind="exception"):
        self.root, self.failure, self.phase, self.kind = root, failure, phase, kind
        self.lock_path = root / "project.lock"
        self.calls = []

    def fault(self, step, phase):
        if step == self.failure and phase == self.phase:
            if self.kind == "crash":
                raise SystemExit(42)
            if self.kind == "timeout":
                raise subprocess.TimeoutExpired("isolated-host-operation", 1)
            raise DeploymentDenied("INJECTED_FAILURE")

    def preflight(self, step):
        self.fault(step, "preflight")

    def action(self, step):
        self.calls.append(step)
        self.fault(step, "action")
        write_json(self.root / (step + ".observed"), {"complete": True})
        self.fault(step, "after-effect")
        if step == self.failure and self.kind == "malformed":
            return {"ok": "true"}
        return {"ok": True}

    def verify(self, step, result):
        self.fault(step, "verify")
        assert read_json(self.root / (step + ".observed"))["complete"]

    def reconcile(self, row):
        if row["pending"]:
            return "DONE" if (self.root / (row["pending"] + ".observed")).exists() else "NOT_STARTED"
        return "READY"

    def final_status(self):
        assert all((self.root / (s + ".observed")).exists() for s in STEPS)


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize("phase,kind", [("preflight", "exception"), ("action", "exception"),
                                        ("action", "timeout"), ("result", "malformed"), ("verify", "exception")])
def test_d01_each_failure_stops_all_later_effects(tmp_path, step, phase, kind):
    adapter = Adapter(tmp_path, step, phase, kind)
    deploy = Deployment({"id": "test"}, tmp_path / "receipt", adapter)
    with pytest.raises((DeploymentDenied, subprocess.TimeoutExpired)):
        deploy.run()
    cutoff = STEPS.index(step) + (phase != "preflight")
    assert adapter.calls == list(STEPS[:cutoff])
    assert deploy.status()["state"] == "FAILED"
    before = list(adapter.calls)
    with pytest.raises(DeploymentDenied, match="RECOVERY_REQUIRED"):
        deploy.run()
    assert adapter.calls == before


def test_d02_external_lock_rejection_never_adopts_or_starts(tmp_path):
    adapter = Adapter(tmp_path, "backup", "preflight")
    with pytest.raises(DeploymentDenied):
        Deployment({"id": "test"}, tmp_path / "receipt", adapter).run()
    assert adapter.calls == ["baseline", "freeze", "stop"]
    assert not any((tmp_path / (s + ".observed")).exists() for s in ("backup", "adopt", "start", "resume"))


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize("phase", ["action", "after-effect"])
def test_d07_crash_reconciles_observation_before_continuation(tmp_path, step, phase):
    adapter = Adapter(tmp_path, step, phase, "crash")
    deploy = Deployment({"id": "test"}, tmp_path / "receipt", adapter)
    with pytest.raises(SystemExit):
        deploy.run()
    assert deploy.status()["pending"] == step
    recovered = Adapter(tmp_path)
    result = Deployment({"id": "test"}, tmp_path / "receipt", recovered).run(recover=True)
    assert result["state"] == "COMPLETE"
    start = STEPS.index(step) + (phase == "after-effect")
    assert recovered.calls == list(STEPS[start:])


def test_d07_unknown_result_does_not_repeat_effect(tmp_path):
    adapter = Adapter(tmp_path, "adopt", "after-effect", "crash")
    deploy = Deployment({"id": "test"}, tmp_path / "receipt", adapter)
    with pytest.raises(SystemExit):
        deploy.run()
    adapter.reconcile = lambda row: "UNKNOWN"
    calls = list(adapter.calls)
    with pytest.raises(DeploymentDenied, match="ACTION_RESULT_UNKNOWN"):
        deploy.run(recover=True)
    assert adapter.calls == calls


def test_d06_complete_repeat_has_no_effects(tmp_path):
    adapter = Adapter(tmp_path)
    deploy = Deployment({"id": "test"}, tmp_path / "receipt", adapter)
    assert deploy.run()["state"] == "COMPLETE"
    calls = list(adapter.calls)
    assert deploy.run()["state"] == "COMPLETE"
    assert adapter.calls == calls


def test_d06_corrupt_journal_refuses(tmp_path):
    directory = tmp_path / "receipt"
    directory.mkdir()
    (directory / "journal.json").write_text('{"schema":1}')
    adapter = Adapter(tmp_path)
    with pytest.raises(DeploymentDenied):
        Deployment({"id": "test"}, directory, adapter).run(recover=True)
    assert adapter.calls == []


def test_d06_real_cross_process_lock(tmp_path):
    lock = tmp_path / "project.lock"
    code = "from video_processing.core.deployment import project_lock; import sys;\nwith project_lock(sys.argv[1]): print('entered',flush=True)"
    with project_lock(lock):
        other = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True, text=True, timeout=10)
        assert other.returncode != 0 and "DEPLOYMENT_BUSY" in other.stderr
        assert "entered" not in other.stdout
    other = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True, text=True, timeout=10)
    assert other.returncode == 0 and "entered" in other.stdout


def test_d01_journal_write_failure_prevents_first_action(tmp_path):
    directory = tmp_path / "receipt"
    directory.mkdir()
    # ENOTDIR 确定性注入，比 root/不同文件系统下 chmod 更可靠。
    blocked = directory / "blocked"
    blocked.write_text("file")
    adapter = Adapter(tmp_path)
    with pytest.raises(OSError):
        Deployment({"id": "test"}, blocked, adapter).run()
    assert adapter.calls == []


def test_d03_backup_includes_committed_wal_without_initializing_source(tmp_path):
    source, target = tmp_path / "live.sqlite", tmp_path / "saved.sqlite"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE isolated_proof (value TEXT)")
        conn.execute("INSERT INTO isolated_proof VALUES ('committed-wal')")
        conn.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        receipt = PipelineDB.maintenance_backup(source, target)
        assert receipt["integrity"] == "ok"
        assert PipelineDB.maintenance_verify_backup(target, receipt)
        with sqlite3.connect(target) as saved:
            assert saved.execute("SELECT value FROM isolated_proof").fetchall() == [("committed-wal",)]
            assert saved.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("isolated_proof",)]
    original = target.read_bytes()
    with pytest.raises(ValueError):
        PipelineDB.maintenance_backup(source, target)
    assert target.read_bytes() == original
    with target.open("ab") as stream:
        stream.write(b"tamper")
    assert not PipelineDB.maintenance_verify_backup(target, receipt)


def test_d03_invalid_database_and_unwritable_destination_fail(tmp_path):
    source = tmp_path / "bad.sqlite"
    source.write_bytes(b"this is not SQLite")
    with pytest.raises(sqlite3.DatabaseError):
        PipelineDB.maintenance_backup(source, tmp_path / "backup.sqlite")
    blocked = tmp_path / "parent-file"
    blocked.write_text("blocked")
    with pytest.raises(OSError):
        PipelineDB.maintenance_backup(source, blocked / "backup.sqlite")

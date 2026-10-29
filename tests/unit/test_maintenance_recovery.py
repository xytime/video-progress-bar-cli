"""临时准入文件和真实 flock 的保守对账；不接触线上任务或数据库。"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from video_processing.core.deployment import DeploymentDenied, digest, read_json
from video_processing.core.maintenance import MaintenanceDenied, MaintenanceGate
from video_processing.core.maintenance_recovery import MaintenanceRecovery


def fixture(tmp_path, count=1, process=None):
    control = MaintenanceGate(tmp_path / "state" / "control.json")
    control.enter("失主准入对账")
    control.directory.mkdir()
    records = []
    for number in range(count):
        identity = f"{number + 1:032x}"
        row = {"id": identity, "pid": 999999 + number, "role": "pipeline",
               "object": f"video:{number}", "phase": "ACTIVE", "at": 1.0}
        (control.directory / (identity + ".json")).write_text(json.dumps(row) + "\n")
        records.append(identity)
    recovery = MaintenanceRecovery(control, tmp_path / "audit", boot_reader=lambda: "boot-A",
                                   process_reader=process or (lambda pid: {"state": "ABSENT"}))
    return control, recovery, records


def apply(recovery, **kwargs):
    return recovery.apply(expected_plan=digest(read_json(recovery.directory / "plan.json")), **kwargs)


def test_archive_exact_bytes_keeps_gate_tasks_and_unselected_records(tmp_path):
    control, recovery, records = fixture(tmp_path, 2)
    business = tmp_path / "business.db"
    business.write_bytes(b"untouched publication evidence")
    before_state, before_business = control.path.read_bytes(), business.read_bytes()
    source = control.directory / (records[0] + ".json")
    raw = source.read_bytes()
    plan = recovery.plan(records[:1])
    assert plan["records"][0]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert source.exists()
    result = apply(recovery)
    assert result["count"] == 1 and result["task_outcome"] == "NOT_ASSESSED"
    assert result["maintenance_resumed"] is False
    assert not source.exists()
    assert (recovery.directory / (records[0] + ".lease.json")).read_bytes() == raw
    assert (control.directory / (records[1] + ".json")).exists()
    assert control.path.read_bytes() == before_state and business.read_bytes() == before_business
    assert apply(recovery, recover=True) == result
    with pytest.raises(DeploymentDenied) as error:
        apply(recovery)
    assert error.value.code == "RECOVERY_REQUIRED"


@pytest.mark.parametrize("birth", [None, "same"])
def test_unlocked_alive_owner_never_treated_as_finished(tmp_path, birth):
    control, recovery, records = fixture(tmp_path, process=lambda pid: {"state": "PRESENT", "birth": "same"})
    source = control.directory / (records[0] + ".json")
    if birth:
        row = json.loads(source.read_text())
        row["birth"] = birth
        source.write_text(json.dumps(row))
    with pytest.raises(DeploymentDenied) as error:
        recovery.plan(records)
    assert error.value.code == "OWNER_STILL_ALIVE_OR_UNPROVEN"
    assert source.exists() and not recovery.directory.exists()


def test_only_recorded_birth_proves_pid_reuse(tmp_path):
    control, recovery, records = fixture(tmp_path, process=lambda pid: {"state": "PRESENT", "birth": "new-birth"})
    source = control.directory / (records[0] + ".json")
    row = json.loads(source.read_text())
    row["birth"] = "old-birth"
    source.write_text(json.dumps(row))
    assert recovery.plan(records)["records"][0]["owner"]["verdict"] == "PID_REUSED"
    assert apply(recovery)["count"] == 1


@pytest.mark.parametrize("stage", ["plan", "apply"])
def test_real_flock_owner_blocks_even_when_pid_probe_says_absent(tmp_path, stage):
    control, recovery, records = fixture(tmp_path)
    source = control.directory / (records[0] + ".json")
    if stage == "apply":
        recovery.plan(records)
    code = ("import fcntl,sys; f=open(sys.argv[1],'rb'); fcntl.flock(f,fcntl.LOCK_EX); "
            "print('held',flush=True); sys.stdin.readline()")
    child = subprocess.Popen([sys.executable, "-c", code, str(source)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        with pytest.raises(DeploymentDenied) as error:
            recovery.plan(records) if stage == "plan" else apply(recovery)
        assert error.value.code == "ADMISSION_HELD" and source.exists()
        assert not (recovery.directory / "intent.json").exists()
    finally:
        child.communicate("release\n", timeout=5)
        assert child.returncode == 0


@pytest.mark.parametrize("change", ["bytes", "inode", "gate", "boot", "pid"])
def test_plan_cas_rejects_racing_changes_before_intent(tmp_path, change):
    control, recovery, records = fixture(tmp_path)
    recovery.plan(records)
    source = control.directory / (records[0] + ".json")
    if change == "bytes":
        source.write_bytes(source.read_bytes() + b" ")
    elif change == "inode":
        alternate = source.with_suffix(".replacement")
        alternate.write_bytes(source.read_bytes())
        alternate.replace(source)
    elif change == "gate":
        state = control._read()
        state["version"] += 1
        control._write(state)
    elif change == "boot":
        recovery.boot_reader = lambda: "boot-B"
    else:
        recovery.process_reader = lambda pid: {"state": "PRESENT", "birth": "new"}
    with pytest.raises(DeploymentDenied):
        apply(recovery)
    assert source.exists() and not (recovery.directory / "intent.json").exists()


def test_batch_rechecks_all_before_removing_any(tmp_path):
    control, recovery, records = fixture(tmp_path, 2)
    recovery.plan(records)
    second = control.directory / (records[1] + ".json")
    second.write_bytes(second.read_bytes() + b" ")
    with pytest.raises(DeploymentDenied):
        apply(recovery)
    assert all((control.directory / (identity + ".json")).exists() for identity in records)
    assert not (recovery.directory / "intent.json").exists()


@pytest.mark.parametrize("point", ["before_unlink", "after_unlink"])
def test_crash_has_raw_evidence_and_requires_explicit_recover(tmp_path, monkeypatch, point):
    import video_processing.core.maintenance_recovery as module
    control, recovery, records = fixture(tmp_path)
    recovery.plan(records)
    source = control.directory / (records[0] + ".json")
    raw = source.read_bytes()
    if point == "before_unlink":
        original = Path.unlink
        def fail(path, *args, **kwargs):
            if path == source:
                raise OSError("interrupted before unlink")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", fail)
    else:
        original = module.write_json
        def fail(path, value):
            if path.name.endswith(".receipt.json"):
                raise OSError("interrupted after unlink")
            return original(path, value)
        monkeypatch.setattr(module, "write_json", fail)
    with pytest.raises(MaintenanceDenied) as failure:
        apply(recovery)
    assert failure.value.code == "UNKNOWN" and isinstance(failure.value.__cause__, OSError)
    assert (recovery.directory / "intent.json").exists()
    assert (recovery.directory / (records[0] + ".lease.json")).read_bytes() == raw
    assert source.exists() == (point == "before_unlink")
    monkeypatch.undo()
    with pytest.raises(DeploymentDenied) as error:
        apply(recovery)
    assert error.value.code == "RECOVERY_REQUIRED"
    assert apply(recovery, recover=True)["count"] == 1
    assert not source.exists()


def test_recover_checks_archived_bytes_before_accepting_missing_source(tmp_path, monkeypatch):
    import video_processing.core.maintenance_recovery as module
    control, recovery, records = fixture(tmp_path)
    recovery.plan(records)
    original = module.write_json
    def fail(path, value):
        if path.name.endswith(".receipt.json"):
            raise OSError("interrupted")
        return original(path, value)
    monkeypatch.setattr(module, "write_json", fail)
    with pytest.raises(MaintenanceDenied):
        apply(recovery)
    monkeypatch.undo()
    archive = recovery.directory / (records[0] + ".lease.json")
    archive.write_bytes(archive.read_bytes() + b" ")
    with pytest.raises(DeploymentDenied) as error:
        apply(recovery, recover=True)
    assert error.value.code == "ARCHIVE_CHANGED"
    assert not (recovery.directory / "complete.json").exists()


def test_permission_or_ambiguous_process_observation_is_not_dead(tmp_path):
    def unavailable(pid):
        raise PermissionError("unknown")
    control, recovery, records = fixture(tmp_path, process=unavailable)
    with pytest.raises(MaintenanceDenied) as failure:
        recovery.plan(records)
    assert failure.value.code == "UNKNOWN" and isinstance(failure.value.__cause__, PermissionError)
    assert (control.directory / (records[0] + ".json")).exists()


@pytest.mark.parametrize("damage", ["symlink", "invalid-row"])
def test_noncanonical_records_are_rejected(tmp_path, damage):
    control, recovery, records = fixture(tmp_path)
    source = control.directory / (records[0] + ".json")
    if damage == "symlink":
        target = tmp_path / "elsewhere.json"
        source.replace(target)
        source.symlink_to(target)
    else:
        source.write_text('{"pid": 1}')
    with pytest.raises((MaintenanceDenied, DeploymentDenied)):
        recovery.plan(records)
    assert not recovery.directory.exists()


def test_partial_archive_write_keeps_source_and_explicit_recover_can_continue(tmp_path, monkeypatch):
    import builtins
    import video_processing.core.maintenance_recovery as module
    control, recovery, records = fixture(tmp_path)
    recovery.plan(records)
    source = control.directory / (records[0] + ".json")
    raw = source.read_bytes()
    class InterruptedWriter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, value):
            self.stream.write(value[:9])
            self.stream.flush()
            os.fsync(self.stream.fileno())
            raise OSError("partial target write")
    def partial_open(path, *args, **kwargs):
        stream = builtins.open(path, *args, **kwargs)
        return InterruptedWriter(stream) if ".lease.json." in str(path) else stream
    monkeypatch.setattr(module, "open", partial_open, raising=False)
    with pytest.raises(MaintenanceDenied) as failure:
        apply(recovery)
    assert failure.value.code == "UNKNOWN" and isinstance(failure.value.__cause__, OSError)
    assert source.read_bytes() == raw
    assert not (recovery.directory / (records[0] + ".lease.json")).exists()
    fragments = list(recovery.directory.glob("*.lease.json.*.tmp"))
    assert len(fragments) == 1 and fragments[0].read_bytes() == raw[:9]
    monkeypatch.undo()
    assert apply(recovery, recover=True)["count"] == 1
    assert fragments[0].read_bytes() == raw[:9]
    assert (recovery.directory / (records[0] + ".lease.json")).read_bytes() == raw


def test_reviewed_plan_digest_must_match_even_before_intent(tmp_path):
    control, recovery, records = fixture(tmp_path)
    plan = recovery.plan(records)
    approved = digest(plan)
    plan["records"][0]["row"]["object"] = "changed:object"
    (recovery.directory / "plan.json").write_text(json.dumps(plan))
    with pytest.raises(DeploymentDenied) as error:
        recovery.apply(expected_plan=approved)
    assert error.value.code == "PLAN_CHANGED"
    assert (control.directory / (records[0] + ".json")).exists()
    assert not (recovery.directory / "intent.json").exists()


def test_source_cannot_change_after_archive_copy_before_unlink(tmp_path, monkeypatch):
    import video_processing.core.maintenance_recovery as module
    control, recovery, records = fixture(tmp_path)
    recovery.plan(records)
    source = control.directory / (records[0] + ".json")
    original = module._write_raw
    def replace_after_archive(path, raw):
        original(path, raw)
        source.write_bytes(raw + b" ")
    monkeypatch.setattr(module, "_write_raw", replace_after_archive)
    with pytest.raises(DeploymentDenied) as error:
        apply(recovery)
    assert error.value.code == "RECORD_CHANGED" and source.exists()
    assert not (recovery.directory / "complete.json").exists()


def test_reappeared_source_is_not_deleted_by_repeat_recover(tmp_path):
    control, recovery, records = fixture(tmp_path)
    recovery.plan(records)
    apply(recovery)
    source = control.directory / (records[0] + ".json")
    source.write_bytes((recovery.directory / (records[0] + ".lease.json")).read_bytes())
    with pytest.raises(DeploymentDenied) as error:
        apply(recovery, recover=True)
    assert error.value.code == "SOURCE_REAPPEARED" and source.exists()


def test_native_gate_still_refuses_resume_with_unselected_unknown(tmp_path):
    control, recovery, records = fixture(tmp_path, 2)
    version = control._read()["version"]
    recovery.plan(records[:1])
    apply(recovery)
    state = control.status()
    assert state["state"] == "MAINTENANCE" and state["version"] == version
    assert state["phase"] == "UNKNOWN" and state["unknown"][0]["id"] == records[1]
    with pytest.raises(MaintenanceDenied) as error:
        control.resume(version, validated=True)
    assert error.value.code == "NOT_VERIFIED_IDLE"
    with pytest.raises(MaintenanceDenied):
        control.require_running()


def test_cli_roundtrip_real_crashed_admission_and_reviewed_digest(tmp_path, monkeypatch):
    control = MaintenanceGate(tmp_path / "state" / "control.json")
    initial = control.enter("初始化")
    control.resume(initial["version"], validated=True)
    script = Path(__file__).resolve().parents[2] / "scripts/reconcile_maintenance.py"
    code = ("from video_processing.core.maintenance import MaintenanceGate; import os,sys; "
            "t=MaintenanceGate(sys.argv[1]).acquire('video','synthetic:0'); t.start(); "
            "print(t.row['id'],flush=True); os._exit(0)")
    child = subprocess.run([sys.executable, "-c", code, str(control.path)],
                           capture_output=True, text=True, timeout=10, check=True)
    identity = child.stdout.strip()
    source = control.directory / (identity + ".json")
    raw = source.read_bytes()
    paused = control.enter("真实崩溃登记对账")
    monkeypatch.setenv("MAINTENANCE_STATE_PATH", str(control.path))
    directory = tmp_path / "cli-audit"
    def command(action, *arguments):
        result = subprocess.run([sys.executable, str(script), action, "--directory", str(directory), *arguments],
                                capture_output=True, text=True, timeout=10)
        return result, json.loads(result.stdout)
    result, planned = command("plan", "--record", identity)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert planned["task_outcome"] == "NOT_ASSESSED" and source.read_bytes() == raw
    result, rejected = command("apply", "--expected-plan", "wrong-digest")
    assert result.returncode == 2 and rejected["code"] == "PLAN_CHANGED" and source.exists()
    result, applied = command("apply", "--expected-plan", planned["plan_sha256"])
    assert result.returncode == 0 and applied["count"] == 1 and not source.exists()
    assert (directory / (identity + ".lease.json")).read_bytes() == raw
    assert control._read() == paused and applied["maintenance_resumed"] is False
    result, recovered = command("recover", "--expected-plan", planned["plan_sha256"])
    assert result.returncode == 0 and recovered == applied


def test_cli_unlocked_real_alive_pid_without_birth_remains_blocked(tmp_path, monkeypatch):
    control, recovery, records = fixture(tmp_path)
    source = control.directory / (records[0] + ".json")
    row = json.loads(source.read_text())
    row["pid"] = os.getpid()
    source.write_text(json.dumps(row))
    monkeypatch.setenv("MAINTENANCE_STATE_PATH", str(control.path))
    script = Path(__file__).resolve().parents[2] / "scripts/reconcile_maintenance.py"
    result = subprocess.run([sys.executable, str(script), "plan", "--directory", str(recovery.directory),
                             "--record", records[0]], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stdout)["code"] == "OWNER_STILL_ALIVE_OR_UNPROVEN"
    assert source.exists() and not recovery.directory.exists()

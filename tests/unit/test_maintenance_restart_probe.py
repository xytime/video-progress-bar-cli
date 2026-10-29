"""退休身份只读证明：真实 flock，替代宿主进程/命令读取，不发信号。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-30 | Codex | 真实角色锁、PID 复用、证据漂移、未知退出与精确角色组回归。 |
"""
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from video_processing.core import maintenance_restart_probe as probe
from video_processing.core.deployment import DeploymentDenied


@pytest.fixture
def owners(tmp_path, monkeypatch):
    root = tmp_path / "project"
    for relative in (".venv/bin/python", "src/web/app.py", *(
            "scripts/" + name for name in probe.WORKER_SCRIPTS.values())):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# isolated identity fixture\n")
    control = SimpleNamespace(path=root / "output/maintenance-state.json")
    directory = control.path.with_suffix(".workers")
    directory.mkdir(parents=True)
    state = SimpleNamespace(root=root, control=control, handles={}, rows={}, processes={},
                            boot="boot-A", commands=[], fd_missing=False, hook=None, children={})

    def add(role, pid=7001, **fields):
        row = dict(role=role, pid=pid, protocol=probe.PROTOCOL, cwd=str(root),
                   source_hash="a" * 64, birth=str(pid) + ".000001", started_at="original")
        row.update(fields)
        path = directory / (role + ".lock")
        handle = path.open("w+")
        json.dump(row, handle)
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state.handles[role], state.rows[role] = handle, row
        entry = "src/web/app.py" if role in probe.UI_ROLES else "scripts/" + probe.WORKER_SCRIPTS.get(role, "unknown.py")
        state.processes.setdefault(pid, dict(birth=row["birth"], cwd=str(root),
                                            arguments=[str(root / ".venv/bin/python"), str(root / entry)]))
        return row

    def release(role):
        state.handles.pop(role).close()

    def birth(pid):
        row = state.processes.get(pid)
        if row is None:
            raise ProcessLookupError("isolated process exited")
        if isinstance(row, BaseException):
            raise row
        return row["birth"]

    def run(arguments, **kwargs):
        state.commands.append(arguments)
        assert kwargs == dict(text=True, capture_output=True, timeout=3, check=True)
        if state.hook:
            state.hook(arguments)
        if arguments == ["ps", "-axo", "pid=,ppid="]:
            rows = {pid: 1 for pid in state.processes}
            rows.update(state.children)
            return subprocess.CompletedProcess(arguments, 0, "".join(f"{pid} {parent}\n" for pid, parent in rows.items()), "")
        pid = int(arguments[arguments.index("-p") + 1])
        row = state.processes[pid]
        if arguments[0] == "ps":
            output = " ".join(row["arguments"]) + "\n"
        elif "cwd" in arguments:
            output = "p" + str(pid) + "\nfcwd\nn" + row["cwd"] + "\n"
        else:
            output = "p" + str(pid) + "\n"
            for index, name in enumerate(arguments[arguments.index("-FpfDin") + 1:]):
                path = Path(name)
                role = path.stem
                if state.fd_missing or role not in state.handles or state.rows[role]["pid"] != pid:
                    continue
                value = path.stat()
                output += f"f{index + 6}\nD{value.st_dev:#x}\ni{value.st_ino}\nn{name}\n"
        return subprocess.CompletedProcess(arguments, 0, output, "")

    state.add, state.release = add, release
    monkeypatch.setattr(probe, "process_birth", birth)
    monkeypatch.setattr(probe, "boot_identity", lambda: state.boot)
    monkeypatch.setattr(subprocess, "run", run)
    for role in sorted(probe.UI_ROLES):
        add(role)
    add("ready-worker", 7002, source_hash="b" * 64)
    yield state
    for handle in state.handles.values():
        handle.close()


def capture(owners):
    return probe.capture_owners(owners.control, owners.root)


def test_capture_real_flocks_old_hash_and_full_process_evidence(owners):
    before = {path: path.read_bytes() for path in owners.control.path.parent.rglob("*.lock")}
    snapshot = capture(owners)
    assert set(snapshot) == {"workers", "processes", "boot"}
    assert snapshot["workers"] == owners.rows
    assert snapshot["processes"]["7001"] == dict(
        pid=7001, birth="7001.000001", cwd=str(owners.root),
        arguments=owners.processes[7001]["arguments"], roles=sorted(probe.UI_ROLES),
        locks=snapshot["processes"]["7001"]["locks"])
    assert set(snapshot["processes"]["7001"]["locks"]) == probe.UI_ROLES
    assert snapshot["workers"]["ready-worker"]["source_hash"] == "b" * 64
    assert probe.verify_owners(owners.control, owners.root, snapshot) == snapshot
    assert {path: path.read_bytes() for path in before} == before
    assert all(command[0] == "ps" or command[0].endswith("lsof") for command in owners.commands)


def test_ui_resolved_pyenv_interpreter_and_unbuffered_flag_are_accepted(owners, tmp_path):
    actual = tmp_path / "pyenv/versions/3.12.4/bin/python"
    actual.parent.mkdir(parents=True)
    actual.write_text("# interpreter fixture")
    alias = owners.root / ".venv/bin/python"
    alias.unlink()
    alias.symlink_to(actual)
    owners.processes[7001]["arguments"] = [str(actual), "-u", str(owners.root / "src/web/app.py")]
    assert capture(owners)["processes"]["7001"]["arguments"][1] == "-u"


@pytest.mark.parametrize("entry", ["venv", "intermediate", "resolved"])
def test_ui_multilevel_interpreter_symlink_aliases_are_accepted(owners, tmp_path, entry):
    actual = tmp_path / "pyenv/versions/3.12.4/bin/python3.12"
    actual.parent.mkdir(parents=True)
    actual.write_text("# isolated interpreter")
    intermediate = actual.with_name("python")
    intermediate.symlink_to(actual.name)
    venv = owners.root / ".venv/bin/python"
    venv.unlink()
    venv.symlink_to(intermediate)
    interpreter = {"venv": venv, "intermediate": intermediate, "resolved": actual}[entry]
    arguments = [str(interpreter), "-u", str(owners.root / "src/web/app.py")]
    owners.processes[7001]["arguments"] = arguments
    assert capture(owners)["processes"]["7001"]["arguments"] == arguments


def test_ui_interpreter_with_different_real_target_is_rejected(owners, tmp_path):
    different = tmp_path / "different-python"
    different.write_text("# distinct interpreter")
    alias = tmp_path / "python-alias"
    alias.symlink_to(different)
    owners.processes[7001]["arguments"][0] = str(alias)
    with pytest.raises(DeploymentDenied, match="OWNER_INTERPRETER_UNKNOWN"):
        capture(owners)


def test_independent_worker_still_requires_exact_venv_interpreter_path(owners, tmp_path):
    alias = tmp_path / "same-python"
    alias.symlink_to(owners.root / ".venv/bin/python")
    owners.processes[7002]["arguments"][0] = str(alias)
    with pytest.raises(DeploymentDenied, match="OWNER_INTERPRETER_UNKNOWN"):
        capture(owners)


@pytest.mark.parametrize("field,value", [("pid", True), ("protocol", 99), ("protocol", True),
                                         ("role", "other"), ("birth", ""), ("source_hash", "old")])
def test_invalid_busy_row_is_never_retirement_evidence(owners, field, value):
    handle = owners.handles["ui"]
    row = dict(owners.rows["ui"], **{field: value})
    handle.seek(0)
    handle.truncate()
    json.dump(row, handle)
    handle.flush()
    with pytest.raises(DeploymentDenied, match="OWNER_ROW_INVALID"):
        capture(owners)


@pytest.mark.parametrize("raw", ["", "{}", "[]", "null", "not json"])
def test_empty_or_corrupt_metadata_on_busy_lock_never_means_idle(owners, raw):
    handle = owners.handles["ui"]
    handle.seek(0)
    handle.truncate()
    handle.write(raw)
    handle.flush()
    with pytest.raises(DeploymentDenied):
        capture(owners)


@pytest.mark.parametrize("case,code", [
    ("unknown-role", "OWNER_ROLE_UNKNOWN"), ("split-ui", "OWNER_UI_SPLIT"),
    ("missing-ui", "OWNER_UI_MISSING"), ("shared-worker", "OWNER_WORKER_SHARED_PID"),
    ("wrong-cwd", "OWNER_CWD_MISMATCH"), ("wrong-entry", "OWNER_ENTRY_UNKNOWN"),
    ("wrong-interpreter", "OWNER_INTERPRETER_UNKNOWN"), ("extra-arg", "OWNER_ARGUMENTS_UNKNOWN"),
    ("ambiguous-arg", "OWNER_ARGV_AMBIGUOUS"), ("missing-fd", "OWNER_FD_MISSING"),
])
def test_only_known_role_topology_commands_and_actual_fds_are_allowed(owners, case, code):
    if case == "unknown-role": owners.add("not-registered", 7003)
    elif case == "split-ui": owners.release("auto-pipeline"); owners.add("auto-pipeline", 7003)
    elif case == "missing-ui": owners.release("ui")
    elif case == "shared-worker": owners.release("ready-worker"); owners.add("ready-worker", 7001)
    elif case == "wrong-cwd": owners.processes[7001]["cwd"] += "/other"
    elif case == "wrong-entry": owners.processes[7001]["arguments"][-1] += ".other"
    elif case == "wrong-interpreter": owners.processes[7002]["arguments"][0] = "/usr/bin/python"
    elif case == "extra-arg": owners.processes[7001]["arguments"].append("--debug")
    elif case == "ambiguous-arg": owners.processes[7001]["arguments"].append("'x'")
    elif case == "missing-fd": owners.fd_missing = True
    with pytest.raises(DeploymentDenied, match=code):
        capture(owners)


def test_unlocked_stale_rows_are_not_workers_and_symlinks_are_rejected(owners):
    owners.release("ready-worker")
    assert "ready-worker" not in capture(owners)["workers"]
    path = owners.control.path.with_suffix(".workers") / "ready-worker.lock"
    path.rename(path.with_suffix(".original"))
    path.symlink_to(path.with_suffix(".original"))
    with pytest.raises(DeploymentDenied, match="OWNER_LOCK_NOT_REGULAR"):
        capture(owners)


@pytest.mark.parametrize("case", ["birth", "argv", "new-owner", "boot", "row"])
def test_verify_rejects_identity_or_set_drift(owners, case):
    expected = capture(owners)
    if case == "birth": owners.processes[7002]["birth"] = "reused"
    elif case == "argv": owners.processes[7002]["arguments"].append("--once")
    elif case == "new-owner": owners.add("publishing-recovery-worker", 7003)
    elif case == "boot": owners.boot = "boot-B"
    else:
        handle = owners.handles["ready-worker"]
        handle.seek(0); handle.truncate()
        json.dump(dict(owners.rows["ready-worker"], started_at="different"), handle); handle.flush()
    with pytest.raises(DeploymentDenied):
        probe.verify_owners(owners.control, owners.root, expected, allow_missing=True)


@pytest.mark.parametrize("case", ["same-json-new-inode", "same-row-different-bytes"])
def test_role_lock_inode_and_raw_bytes_are_bound_in_expected_snapshot(owners, case):
    expected = capture(owners)
    path = owners.control.path.with_suffix(".workers") / "ready-worker.lock"
    raw = path.read_bytes()
    if case == "same-json-new-inode":
        owners.release("ready-worker")
        path.rename(path.with_suffix(".retained-old-inode"))
        owners.handles["ready-worker"] = path.open("w+")
        handle = owners.handles["ready-worker"]
        handle.write(raw.decode())
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        handle = owners.handles["ready-worker"]
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(owners.rows["ready-worker"], indent=2))
    handle.flush()
    assert json.loads(path.read_bytes()) == json.loads(raw)
    for allow_missing in (False, True):
        with pytest.raises(DeploymentDenied, match="OWNER_SNAPSHOT_CHANGED"):
            probe.verify_owners(owners.control, owners.root, expected, allow_missing=allow_missing)


def test_only_confirmed_exit_and_released_whole_role_group_can_be_missing(owners):
    expected = capture(owners)
    owners.release("ready-worker")
    with pytest.raises(DeploymentDenied, match="OWNER_EXIT_UNPROVEN"):
        probe.verify_owners(owners.control, owners.root, expected, allow_missing=True)
    owners.processes.pop(7002)
    with pytest.raises(DeploymentDenied, match="OWNER_SNAPSHOT_CHANGED"):
        probe.verify_owners(owners.control, owners.root, expected)
    current = probe.verify_owners(owners.control, owners.root, expected, allow_missing=True)
    assert set(current["processes"]) == {"7001"}
    for role in probe.UI_ROLES:
        owners.release(role)
    owners.processes.pop(7001)
    assert probe.verify_owners(owners.control, owners.root, expected, allow_missing=True)["workers"] == {}


@pytest.mark.parametrize("process", [dict(birth="new-birth"), PermissionError("unknown"), OSError("unknown")])
def test_reused_or_unreadable_pid_is_not_confirmed_exit(owners, process):
    expected = capture(owners)
    owners.release("ready-worker")
    owners.processes[7002] = process
    with pytest.raises(DeploymentDenied, match="OWNER_EXIT_(UNKNOWN|UNPROVEN)"):
        probe.verify_owners(owners.control, owners.root, expected, allow_missing=True)


def test_partial_ui_role_loss_is_not_treated_as_process_exit(owners):
    expected = capture(owners)
    owners.release("auto-pipeline")
    with pytest.raises(DeploymentDenied, match="OWNER_SNAPSHOT_CHANGED"):
        probe.verify_owners(owners.control, owners.root, expected, allow_missing=True)


@pytest.mark.parametrize("case", ["read-timeout", "birth-during-capture", "row-during-capture"])
def test_concurrent_changes_or_tool_failure_cannot_return_partial_proof(owners, case):
    def hook(arguments):
        if case == "read-timeout":
            raise subprocess.TimeoutExpired(arguments, 3)
        if case == "birth-during-capture":
            owners.processes[7001]["birth"] = "different"
        else:
            handle = owners.handles["ui"]
            handle.seek(0); handle.truncate()
            json.dump(dict(owners.rows["ui"], started_at="changed"), handle); handle.flush()
    owners.hook = hook
    with pytest.raises(DeploymentDenied):
        capture(owners)


def test_missing_process_with_still_busy_role_is_not_retired(owners):
    expected = capture(owners)
    owners.processes.pop(7002)
    with pytest.raises(DeploymentDenied, match="OWNER_PROBE_UNAVAILABLE"):
        probe.verify_owners(owners.control, owners.root, expected, allow_missing=True)


@pytest.mark.parametrize("child_state,accepted", [
    (dict(birth="child.000001"), False), (ProcessLookupError("zombie"), True),
    (PermissionError("unknown child"), False), (OSError("child unavailable"), False),
])
def test_alive_children_refuse_retirement_but_confirmed_zombie_does_not(owners, child_state, accepted):
    owners.children[7003] = 7002
    owners.processes[7003] = child_state
    if accepted:
        assert set(capture(owners)["processes"]) == {"7001", "7002"}
    else:
        with pytest.raises(DeploymentDenied):
            capture(owners)


def test_child_starting_during_identity_read_is_detected(owners):
    def hook(arguments):
        if "-FpfDin" in arguments:
            owners.children[7003] = 7002
            owners.processes[7003] = dict(birth="new child")
    owners.hook = hook
    with pytest.raises(DeploymentDenied, match="OWNER_LIVE_CHILD"):
        capture(owners)


@pytest.mark.parametrize("case", ["missing-process", "unknown-role", "wrong-roles", "wrong-pid", "extra-field",
                                  "missing-lock", "invalid-lock"])
def test_incomplete_or_forged_expected_snapshot_is_rejected(owners, case):
    expected = deepcopy(capture(owners))
    if case == "missing-process": expected["processes"].pop("7002")
    elif case == "unknown-role": expected["workers"]["unexpected"] = expected["workers"]["ui"]
    elif case == "wrong-roles": expected["processes"]["7002"]["roles"] = []
    elif case == "wrong-pid": expected["processes"]["7002"]["pid"] = 7001
    elif case == "missing-lock": expected["processes"]["7002"]["locks"] = {}
    elif case == "invalid-lock": expected["processes"]["7002"]["locks"]["ready-worker"]["sha256"] = ""
    else: expected["extra"] = True
    with pytest.raises(DeploymentDenied, match="OWNER_EXPECTED_INVALID"):
        probe.verify_owners(owners.control, owners.root, expected, allow_missing=True)

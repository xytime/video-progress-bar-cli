"""只读采集待退休执行者身份；旧 source_hash 不是源码采用或可安全停机证明。

本模块不检查业务排空、不发信号、不接触数据库，也不改变维护状态。
调用方仍须独立证明准入、账本和业务锁为空，并在动作前再次复验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-30 | Codex | 角色 flock、PID birth、完整已知 argv、真实 cwd 与退出后集合复验。 |
"""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys

from .deployment import DeploymentDenied, require
from .maintenance_recovery import boot_identity
from .maintenance_runtime import PROTOCOL, process_birth

UI_ROLES = frozenset({"ui", "auto-pipeline", "queue-runner", "ready-supervisor", "keepalive-watchdog"})
WORKER_SCRIPTS = {
    "ready-worker": "run_ready_publications.py",
    "wallstreet-worker": "run_wallstreet_ab.py",
    "publishing-recovery-worker": "run_publishing_recovery.py",
}
ALLOWED_ROLES = UI_ROLES | WORKER_SCRIPTS.keys()


def _read(arguments):
    return subprocess.run(arguments, text=True, capture_output=True, timeout=3, check=True).stdout


def _file_identity(path):
    value = path.lstat()
    require(stat.S_ISREG(value.st_mode), "OWNER_LOCK_NOT_REGULAR")
    return value.st_dev, value.st_ino


def _locked_row(path, identity):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        value = os.fstat(stream.fileno())
        require((value.st_dev, value.st_ino) == identity, "OWNER_LOCK_CHANGED")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raw = stream.read(65537)
            require(len(raw) <= 65536, "OWNER_ROW_INVALID")
            row = json.loads(raw)
            require(isinstance(row, dict) and bool(row), "OWNER_ROW_INVALID")
            return row, hashlib.sha256(raw).hexdigest()
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return None


def _workers(control, root):
    directory = control.path.with_suffix(".workers")
    if not directory.exists():
        return {}, {}
    require(not directory.is_symlink() and directory.is_dir(), "OWNER_DIRECTORY_INVALID")
    workers, identities = {}, {}
    for path in sorted(directory.iterdir()):
        identity = _file_identity(path)
        observed = _locked_row(path, identity)
        require(_file_identity(path) == identity, "OWNER_LOCK_CHANGED")
        if observed is None:
            continue  # 无内核占用的旧行不构成执行者。
        row, raw_hash = observed
        role = path.stem
        require(path.name == role + ".lock" and role in ALLOWED_ROLES, "OWNER_ROLE_UNKNOWN")
        require(isinstance(row, dict) and row.get("role") == role
                and type(row.get("pid")) is int and row["pid"] > 1
                and type(row.get("protocol")) is int and row["protocol"] == PROTOCOL
                and row.get("cwd") == str(root)
                and isinstance(row.get("birth"), str) and bool(row["birth"])
                and isinstance(row.get("source_hash"), str)
                and re.fullmatch(r"[0-9a-f]{64}", row["source_hash"]), "OWNER_ROW_INVALID")
        workers[role] = row
        identities[role] = dict(dev=identity[0], inode=identity[1], sha256=raw_hash)
    return workers, identities


def _role_groups(workers):
    ui = {role: row for role, row in workers.items() if role in UI_ROLES}
    require(not ui or "ui" in ui, "OWNER_UI_MISSING")
    if ui:
        base = ui["ui"]
        require(all((row["pid"], row["birth"], row["source_hash"]) ==
                    (base["pid"], base["birth"], base["source_hash"]) for row in ui.values()), "OWNER_UI_SPLIT")
    independent = [row["pid"] for role, row in workers.items() if role in WORKER_SCRIPTS]
    require(len(independent) == len(set(independent))
            and (not ui or ui["ui"]["pid"] not in independent), "OWNER_WORKER_SHARED_PID")
    groups = {}
    for role, row in workers.items():
        groups.setdefault(row["pid"], []).append(role)
    return {pid: sorted(roles) for pid, roles in groups.items()}


def _arguments(pid, root, roles):
    # ps 不读取环境。仅接受无空白参数的已知后台入口；含引号/转义的歧义一律拒绝。
    raw = _read(["ps", "-ww", "-p", str(pid), "-o", "command="]).strip()
    require(bool(raw) and not any(char in raw for char in "\n\r\t'\"\\"), "OWNER_ARGV_AMBIGUOUS")
    arguments = raw.split(" ")
    require(all(arguments), "OWNER_ARGV_AMBIGUOUS")
    python = str(root / ".venv/bin/python")
    ui = bool(set(roles) & UI_ROLES)
    accepted = arguments[0] == python
    if ui and not accepted:
        interpreter = Path(arguments[0])
        accepted = interpreter.is_absolute() and interpreter.resolve(strict=True) == Path(python).resolve(strict=True)
    require(accepted, "OWNER_INTERPRETER_UNKNOWN")
    tail = arguments[1:]
    if tail[:1] == ["-u"]:
        tail = tail[1:]
    entry = root / ("src/web/app.py" if ui else "scripts/" + WORKER_SCRIPTS[roles[0]])
    require(entry.is_file() and not entry.is_symlink()
            and str(entry.resolve(strict=True)) == str(entry)
            and tail[:1] == [str(entry)], "OWNER_ENTRY_UNKNOWN")
    # 只退休长期后台模式，不把临时的 --activate/--bind-publication 等命令纳入。
    allowed = [[], ["--once"]] if roles[0] == "ready-worker" else [[]]
    require(tail[1:] in allowed, "OWNER_ARGUMENTS_UNKNOWN")
    return arguments


def _no_live_children(pid):
    rows = {}
    for line in _read(["ps", "-axo", "pid=,ppid="]).splitlines():
        if not line.strip():
            continue
        parts = line.split()
        require(len(parts) == 2 and all(part.isdecimal() for part in parts), "OWNER_CHILD_TREE_UNKNOWN")
        child, parent = map(int, parts)
        require(child not in rows, "OWNER_CHILD_TREE_UNKNOWN")
        rows[child] = parent
    require(pid in rows, "OWNER_CHILD_TREE_UNKNOWN")
    for child, parent in rows.items():
        if parent != pid:
            continue
        try:
            process_birth(child)
        except ProcessLookupError:
            continue  # 已退出/僵尸子进程不构成活业务；权限未知仍闭锁。
        raise DeploymentDenied("OWNER_LIVE_CHILD")


def _cwd(pid, root):
    lsof = "/usr/sbin/lsof" if sys.platform == "darwin" else "lsof"
    output = _read([lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    paths = [line[1:] for line in output.splitlines() if line.startswith("n")]
    require(paths == [str(root)], "OWNER_CWD_MISMATCH")
    return str(root)


def _role_descriptors(pid, control, roles, identities):
    lsof = "/usr/sbin/lsof" if sys.platform == "darwin" else "lsof"
    directory = control.path.with_suffix(".workers")
    paths = {str(directory / (role + ".lock")): (identities[role]["dev"], identities[role]["inode"])
             for role in roles}
    output = _read([lsof, "-a", "-p", str(pid), "-FpfDin", *sorted(paths)])
    records, current, seen_pid = [], None, None
    for line in output.splitlines():
        if line.startswith("p"):
            require(line == "p" + str(pid) and seen_pid is None, "OWNER_FD_PID_MISMATCH")
            seen_pid = pid
        elif line.startswith("f"):
            if current is not None:
                records.append(current)
            current = {"f": line[1:]}
        elif current is not None and line[:1] in {"D", "i", "n"}:
            require(line[0] not in current, "OWNER_FD_AMBIGUOUS")
            current[line[0]] = line[1:]
    if current is not None:
        records.append(current)
    require(seen_pid == pid, "OWNER_FD_PID_MISSING")
    seen = set()
    for row in records:
        name = row.get("n")
        require(name in paths and re.fullmatch(r"\d+[rwu]?", row.get("f", "")), "OWNER_FD_UNKNOWN")
        require((int(row["D"], 16), int(row["i"])) == paths[name], "OWNER_FD_IDENTITY_MISMATCH")
        seen.add(name)
    require(seen == set(paths), "OWNER_FD_MISSING")


def _capture(control, root):
    root = Path(root)
    require(root.is_absolute() and root.is_dir() and str(root.resolve()) == str(root), "OWNER_ROOT_INVALID")
    boot = boot_identity()
    workers, identities = _workers(control, root)
    groups, processes = _role_groups(workers), {}
    for pid, roles in groups.items():
        birth = process_birth(pid)
        require(all(workers[role]["birth"] == birth for role in roles), "OWNER_BIRTH_MISMATCH")
        _no_live_children(pid)
        arguments, cwd = _arguments(pid, root, roles), _cwd(pid, root)
        _role_descriptors(pid, control, roles, identities)
        _no_live_children(pid)
        require(process_birth(pid) == birth, "OWNER_BIRTH_CHANGED")
        processes[str(pid)] = dict(pid=pid, birth=birth, cwd=cwd, arguments=arguments, roles=roles,
                                   locks={role: identities[role] for role in roles})
    require(_workers(control, root) == (workers, identities), "OWNER_REGISTRY_CHANGED")
    require(boot_identity() == boot, "OWNER_BOOT_CHANGED")
    return dict(workers=workers, processes=processes, boot=boot)


def capture_owners(control, root):
    """采集当场真实身份；任何工具/权限/解析错误均拒绝，不返回部分证明。"""
    try:
        return _capture(control, root)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        if isinstance(exc, DeploymentDenied):
            raise
        raise DeploymentDenied("OWNER_PROBE_UNAVAILABLE") from exc


def _expected_groups(expected, root):
    require(isinstance(expected, dict) and set(expected) == {"workers", "processes", "boot"}
            and isinstance(expected["workers"], dict) and isinstance(expected["processes"], dict)
            and isinstance(expected["boot"], str) and bool(expected["boot"]), "OWNER_EXPECTED_INVALID")
    workers = expected["workers"]
    require(all(role in ALLOWED_ROLES and isinstance(row, dict)
                and row.get("role") == role and type(row.get("pid")) is int and row["pid"] > 1
                for role, row in workers.items()), "OWNER_EXPECTED_INVALID")
    groups = _role_groups(workers)
    require(set(expected["processes"]) == {str(pid) for pid in groups}, "OWNER_EXPECTED_INVALID")
    for pid, roles in groups.items():
        row = expected["processes"][str(pid)]
        require(isinstance(row, dict) and set(row) == {"pid", "birth", "cwd", "arguments", "roles", "locks"}
                and row["pid"] == pid and row["roles"] == roles and row["cwd"] == str(root)
                and isinstance(row["birth"], str) and bool(row["birth"])
                and isinstance(row["arguments"], list) and bool(row["arguments"])
                and all(isinstance(arg, str) and bool(arg) for arg in row["arguments"])
                and all(workers[role].get("birth") == row["birth"] for role in roles), "OWNER_EXPECTED_INVALID")
        require(isinstance(row["locks"], dict) and set(row["locks"]) == set(roles), "OWNER_EXPECTED_INVALID")
        for lock in row["locks"].values():
            require(isinstance(lock, dict) and set(lock) == {"dev", "inode", "sha256"}
                    and type(lock["dev"]) is int and lock["dev"] >= 0
                    and type(lock["inode"]) is int and lock["inode"] > 0
                    and isinstance(lock["sha256"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", lock["sha256"]), "OWNER_EXPECTED_INVALID")


def verify_owners(control, root, expected, allow_missing=False):
    """复验完整集合；仅明确退出且角色锁全部释放的 PID 可在退出后复验中缺席。"""
    require(type(allow_missing) is bool, "OWNER_EXPECTED_INVALID")
    try:
        _expected_groups(expected, Path(root))
    except (KeyError, TypeError, ValueError) as exc:
        raise DeploymentDenied("OWNER_EXPECTED_INVALID") from exc
    current = capture_owners(control, root)
    require(current["boot"] == expected["boot"], "OWNER_BOOT_CHANGED")
    if not allow_missing:
        require(current == expected, "OWNER_SNAPSHOT_CHANGED")
        return current
    require(set(current["workers"]) <= set(expected["workers"])
            and set(current["processes"]) <= set(expected["processes"]), "OWNER_SET_CHANGED")
    for key in ("workers", "processes"):
        require(all(row == expected[key][name] for name, row in current[key].items()), "OWNER_SNAPSHOT_CHANGED")
    for identity, row in expected["processes"].items():
        if identity in current["processes"]:
            continue
        require(str(row.get("pid")) == identity
                and all(role not in current["workers"] for role in row.get("roles", [])), "OWNER_EXPECTED_INVALID")
        try:
            process_birth(row["pid"])
        except ProcessLookupError:
            continue
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise DeploymentDenied("OWNER_EXIT_UNKNOWN") from exc
        raise DeploymentDenied("OWNER_EXIT_UNPROVEN")
    require(set(expected["workers"]) - set(current["workers"]) ==
            {role for identity, row in expected["processes"].items() if identity not in current["processes"]
             for role in row.get("roles", [])}, "OWNER_ROLE_DISAPPEARED")
    return current

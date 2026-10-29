"""显式对账失主准入；只归档登记，不判断业务成功，也不解除维护。

依赖：scripts → 本模块 → maintenance/deployment；运行探测按需读取本机身份。
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import errno
import fcntl
import hashlib
import json
import math
import os
import stat
import subprocess
import sys
import time
import uuid

from .deployment import digest, read_json, require, write_json


def boot_identity():
    if sys.platform == "darwin":
        value = subprocess.check_output(
            ["sysctl", "-n", "kern.boottime"], text=True, timeout=2).strip()
    else:
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    require(bool(value), "BOOT_UNKNOWN")
    return value


def process_identity(pid):
    """不发送信号；权限错误和无法确认的 PID 均拒绝回收。"""
    from .maintenance_runtime import process_birth
    try:
        birth = process_birth(pid)
    except ProcessLookupError:
        return {"state": "ABSENT"}
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return {"state": "ABSENT"}
        raise
    require(isinstance(birth, str) and bool(birth), "PROCESS_UNKNOWN")
    return {"state": "PRESENT", "birth": birth}


def _sync(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _identity(value):
    return (value.st_dev, value.st_ino)


def _write_raw(path, raw):
    """未完成的临时副本保留；正式副本持久化后才允许移除原登记。"""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with open(temporary, "xb", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path)
    _sync(path.parent)
    temporary.unlink()
    _sync(path.parent)


def _valid_ids(values):
    require(isinstance(values, list) and bool(values) and len(values) == len(set(values)), "RECORD_IDS_INVALID")
    require(all(isinstance(value, str) and len(value) == 32 and
                all(char in "0123456789abcdef" for char in value) for value in values), "RECORD_IDS_INVALID")


def _decode(raw, identity):
    row = json.loads(raw)
    require(isinstance(row, dict) and row.get("id") == identity
            and type(row.get("pid")) is int and row["pid"] > 0
            and row.get("phase") in {"WAITING", "ACTIVE"}
            and isinstance(row.get("role"), str) and bool(row["role"])
            and isinstance(row.get("object"), str)
            and type(row.get("at")) in {int, float} and math.isfinite(row["at"]), "RECORD_INVALID")
    return row


class MaintenanceRecovery:
    """显式 ID 白名单、真实 flock、全局锁及逐条可恢复的持久审计。"""
    def __init__(self, control, directory, *, boot_reader=boot_identity, process_reader=process_identity):
        self.control, self.directory = control, Path(directory).resolve()
        self.boot_reader, self.process_reader = boot_reader, process_reader
        require(not self.directory.is_relative_to(control.directory.resolve())
                and not control.directory.resolve().is_relative_to(self.directory), "AUDIT_DIRECTORY_INVALID")

    def _owner(self, row):
        observed = self.process_reader(row["pid"])
        require(isinstance(observed, dict), "PROCESS_UNKNOWN")
        if observed == {"state": "ABSENT"}:
            return dict(observed, verdict="PID_ABSENT")
        require(observed.get("state") == "PRESENT" and isinstance(observed.get("birth"), str)
                and bool(observed["birth"]), "PROCESS_UNKNOWN")
        recorded = row.get("birth")
        require(isinstance(recorded, str) and bool(recorded)
                and recorded != observed["birth"], "OWNER_STILL_ALIVE_OR_UNPROVEN")
        return {"state": "PRESENT", "birth": observed["birth"], "verdict": "PID_REUSED"}

    @contextmanager
    def _record(self, identity, expected=None):
        path = self.control.directory / (identity + ".json")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "RECORD_NOT_REGULAR")
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                from .deployment import DeploymentDenied
                raise DeploymentDenied("ADMISSION_HELD") from exc
            raw = stream.read()
            row = _decode(raw, identity)
            item = {"id": identity, "dev": info.st_dev, "inode": info.st_ino,
                    "sha256": hashlib.sha256(raw).hexdigest(), "row": row}
            require(_identity(path.lstat()) == _identity(info), "RECORD_REPLACED")
            if expected is not None:
                require(item == {key: expected[key] for key in item}, "RECORD_CHANGED")
            item["owner"] = self._owner(row)
            if expected is not None:
                require(item["owner"] == expected["owner"], "PROCESS_CHANGED")
            yield path, stream, raw, item

    def plan(self, identities):
        _valid_ids(identities)
        require(not self.directory.exists(), "NEW_PLAN_REQUIRED")
        with self.control._locked(), ExitStack() as stack:
            state = self.control._read()
            require(state["state"] == "MAINTENANCE", "MAINTENANCE_REQUIRED")
            boot = self.boot_reader()
            records = [stack.enter_context(self._record(value))[3] for value in sorted(identities)]
            require(self.boot_reader() == boot, "BOOT_CHANGED")
            plan = {"schema": 1, "id": uuid.uuid4().hex, "control": str(self.control.path.resolve()),
                    "leases": str(self.control.directory.resolve()), "gate": state, "boot": boot,
                    "at": time.time(), "records": records, "task_outcome": "NOT_ASSESSED"}
            self.directory.mkdir(mode=0o700)
            _sync(self.directory.parent)
            write_json(self.directory / "plan.json", plan)
            return plan

    def _load(self):
        plan = read_json(self.directory / "plan.json")
        require(isinstance(plan, dict) and plan.get("schema") == 1
                and plan.get("task_outcome") == "NOT_ASSESSED"
                and plan.get("control") == str(self.control.path.resolve())
                and plan.get("leases") == str(self.control.directory.resolve()), "PLAN_INVALID")
        _valid_ids([item["id"] for item in plan["records"]])
        require(self.control._read() == plan["gate"] and plan["gate"]["state"] == "MAINTENANCE",
                "MAINTENANCE_CHANGED")
        require(self.boot_reader() == plan["boot"], "BOOT_CHANGED")
        return plan, digest(plan)

    def _archive_path(self, item):
        return self.directory / (item["id"] + ".lease.json")

    def _receipt_path(self, item):
        return self.directory / (item["id"] + ".receipt.json")

    def _archive_valid(self, item):
        path = self._archive_path(item)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "ARCHIVE_NOT_REGULAR")
            raw = stream.read()
        require(hashlib.sha256(raw).hexdigest() == item["sha256"]
                and _decode(raw, item["id"]) == item["row"], "ARCHIVE_CHANGED")

    def _receipt_valid(self, item, plan_hash):
        expected = {"schema": 1, "plan": plan_hash, "record": item,
                    "result": "ADMISSION_ARCHIVED", "task_outcome": "NOT_ASSESSED"}
        receipt = read_json(self._receipt_path(item))
        require({key: receipt.get(key) for key in expected} == expected, "RECEIPT_CHANGED")

    def _prepare(self, plan, plan_hash, recover, stack):
        opened = {}
        for item in plan["records"]:
            source = self.control.directory / (item["id"] + ".json")
            archive, receipt = self._archive_path(item), self._receipt_path(item)
            if source.exists() or source.is_symlink():
                require(not receipt.exists(), "SOURCE_REAPPEARED")
                opened[item["id"]] = stack.enter_context(self._record(item["id"], item))
                require(recover or not archive.exists(), "ARCHIVE_ALREADY_EXISTS")
                if archive.exists() or archive.is_symlink():
                    self._archive_valid(item)
            else:
                require(recover, "RECORD_MISSING")
                self._archive_valid(item)
                if receipt.exists():
                    self._receipt_valid(item, plan_hash)
        return opened

    def _archive_one(self, item, opened, plan_hash):
        archive = self._archive_path(item)
        if opened is not None:
            path, stream, raw, _ = opened
            if not archive.exists():
                _write_raw(archive, raw)
            self._archive_valid(item)
            require(_identity(path.lstat()) == (item["dev"], item["inode"]), "RECORD_REPLACED")
            stream.seek(0)
            require(hashlib.sha256(stream.read()).hexdigest() == item["sha256"], "RECORD_CHANGED")
            require(self._owner(item["row"]) == item["owner"], "PROCESS_CHANGED")
            path.unlink()
            _sync(self.control.directory)
        receipt_path = self._receipt_path(item)
        if receipt_path.exists():
            self._receipt_valid(item, plan_hash)
        else:
            write_json(receipt_path, {"schema": 1, "plan": plan_hash, "record": item,
                       "result": "ADMISSION_ARCHIVED", "task_outcome": "NOT_ASSESSED", "at": time.time()})

    def apply(self, *, expected_plan, recover=False):
        with self.control._locked(), ExitStack() as stack:
            plan, plan_hash = self._load()
            require(expected_plan == plan_hash, "PLAN_CHANGED")
            intent_path = self.directory / "intent.json"
            intent = {"schema": 1, "plan": plan_hash, "action": "ARCHIVE_ADMISSIONS"}
            if intent_path.exists():
                require(recover, "RECOVERY_REQUIRED")
                require(read_json(intent_path) == intent, "INTENT_CHANGED")
            else:
                require(not recover, "INTENT_MISSING")
            opened = self._prepare(plan, plan_hash, recover, stack)
            if not intent_path.exists():
                write_json(intent_path, intent)
            for item in plan["records"]:
                self._archive_one(item, opened.get(item["id"]), plan_hash)
            require(self.control._read() == plan["gate"], "MAINTENANCE_CHANGED")
            result = {"schema": 1, "plan": plan_hash, "result": "ADMISSIONS_ARCHIVED",
                      "count": len(plan["records"]), "task_outcome": "NOT_ASSESSED",
                      "maintenance_resumed": False}
            write_json(self.directory / "complete.json", result)
            return result

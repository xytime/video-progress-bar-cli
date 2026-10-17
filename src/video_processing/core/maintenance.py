"""本机维护准入：原子状态、真实 flock 在途登记和显式恢复；缺失即拒绝。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | v0.2.1 跨进程单项准入、等待重检、CAS 与故障闭锁 |
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import fcntl
import json
import os
import time
import uuid
import threading


class MaintenanceDenied(RuntimeError):
    def __init__(self, code="MAINTENANCE"):
        self.code = code
        super().__init__("维护状态不允许领取新工作" if code == "MAINTENANCE" else "维护状态无法确认")


_CURRENT = ContextVar("maintenance_admission", default=None)


class MaintenanceGate:
    def __init__(self, path):
        self.path = Path(path)
        self.directory = self.path.with_suffix(".leases")

    @contextmanager
    def _locked(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a+") as stream:
                deadline = time.monotonic() + 2
                while True:
                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise MaintenanceDenied("UNKNOWN")
                        time.sleep(.02)
                yield
        except OSError as exc:
            raise MaintenanceDenied("UNKNOWN") from exc

    def _read(self):
        try:
            value = json.loads(self.path.read_text())
            if (value["schema"] != 1 or value["state"] not in {"MAINTENANCE", "RUNNING"}
                    or type(value["version"]) is not int or value["version"] < 1):
                raise ValueError()
            return value
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise MaintenanceDenied("UNKNOWN") from exc

    def _write(self, value):
        temporary = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("x") as stream:
                json.dump(value, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def enter(self, reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 160:
            raise ValueError("维护原因须为 1–160 字")
        with self._locked():
            try:
                value = self._read()
            except MaintenanceDenied:
                # 只有首次初始化可创建；损坏不能借 enter 静默修复。
                if self.path.exists():
                    raise
                value = {"schema": 1, "version": 0}
            if value.get("state") == "MAINTENANCE":
                return value
            value.update(state="MAINTENANCE", version=value["version"] + 1,
                         reason=reason.strip(), at=time.time())
            self._write(value)
            return value

    def _leases(self):
        active, unknown = [], []
        paths = sorted(self.directory.iterdir()) if self.directory.exists() else []
        for path in paths:
            if path.suffix != ".json":
                unknown.append({"code": "LEASE_UNKNOWN"})
                continue
            try:
                with path.open("r+") as stream:
                    row = json.load(stream)
                    if (not isinstance(row, dict) or row.get("id") != path.stem
                            or type(row.get("pid")) is not int or row["pid"] < 1
                            or row.get("phase") not in {"ACTIVE", "WAITING"}
                            or not isinstance(row.get("object"), str)):
                        raise ValueError("接纳记录无法确认")
                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        active.append(row)
                        continue
                    # 崩溃记录不当成空闲：需要诊断并显式回收。
                    unknown.append({"id": path.stem, "code": "ABANDONED_ADMISSION"})
            except (OSError, ValueError, TypeError):
                unknown.append({"id": path.stem, "code": "LEASE_UNKNOWN"})
        return active, unknown

    def status(self):
        try:
            with self._locked():
                value = self._read()
                active, unknown = self._leases()
                age = max(0, time.time() - value.get("at", time.time())) if value["state"] == "MAINTENANCE" else 0
                return dict(value, maintenance_age_seconds=round(age), maintenance_overdue=age >= 3600,
                            active=active, unknown=unknown,
                            phase="UNKNOWN" if unknown else "DRAINING" if active else "IDLE")
        except MaintenanceDenied:
            return {"state": "UNKNOWN", "phase": "UNKNOWN", "active": [], "unknown": [{"code": "CONTROL_UNKNOWN"}]}

    def resume(self, expected_version, *, validated=False):
        with self._locked():
            value = self._read()
            if value["version"] != expected_version:
                raise MaintenanceDenied("VERSION_CONFLICT")
            active, unknown = self._leases()
            if active or unknown or not validated:
                raise MaintenanceDenied("NOT_VERIFIED_IDLE")
            if value["state"] == "RUNNING":
                return value
            value.update(state="RUNNING", version=value["version"] + 1, at=time.time())
            self._write(value)
            return value

    def require_running(self):
        with self._locked():
            value = self._read()
            if value["state"] != "RUNNING":
                raise MaintenanceDenied()

    @contextmanager
    def admit(self, role, object_key):
        """资源等待也登记；开始业务前调用 ticket.start() 再核对。

        同一上下文的同对象内部阶段继续，不允许跨对象借用。
        """
        key = str(object_key)
        current = _CURRENT.get()
        if (current and current.gate.path == self.path and current.key == key
                and not current.stream.closed):
            yield current
            return
        ticket = self.acquire(role, key)
        token = _CURRENT.set(ticket)
        try:
            yield ticket
        finally:
            _CURRENT.reset(token)
            ticket.close()

    def acquire(self, role, key):
        return self._acquire(role, key)

    def _acquire(self, role, key, parent=None):
        with self._locked():
            continuation = (parent is not None and parent.key == str(key)
                            and parent.gate.path == self.path and parent.row["phase"] == "ACTIVE"
                            and not parent.stream.closed)
            if self._read()["state"] != "RUNNING" and not continuation:
                raise MaintenanceDenied()
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / (uuid.uuid4().hex + ".json")
            stream = path.open("x+")
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                row = dict(id=path.stem, role=str(role), object=str(key), pid=os.getpid(),
                           phase="WAITING", at=time.time())
                if continuation:
                    row.update(parent=parent.row["id"], phase="ACTIVE")
                json.dump(row, stream)
                stream.flush()
                return Admission(self, str(key), stream, row)
            except BaseException:
                stream.close()
                path.unlink(missing_ok=True)
                raise


class Admission:
    def __init__(self, gate, key, stream, row):
        self.gate, self.key, self.stream, self.row = gate, key, stream, row

    @contextmanager
    def bind(self):
        token = _CURRENT.set(self)
        try:
            yield self
        finally:
            _CURRENT.reset(token)

    def close(self):
        try:
            with self.gate._locked():
                (self.gate.directory / (self.row["id"] + ".json")).unlink(missing_ok=True)
        finally:
            self.stream.close()

    def start(self):
        if self.row["phase"] == "ACTIVE":
            return
        with self.gate._locked():
            if self.gate._read()["state"] != "RUNNING":
                raise MaintenanceDenied()
            self.row["phase"] = "ACTIVE"
            self.stream.seek(0)
            json.dump(self.row, self.stream)
            self.stream.truncate()
            self.stream.flush()


def gate():
    from config.settings import settings
    return MaintenanceGate(settings.maintenance_state_path)


def current():
    return _CURRENT.get()


def start_current():
    ticket = current()
    if ticket:
        ticket.start()


def entry(method):
    """批量入口校验启动；每次轮询/单项仍须重新准入。"""
    @wraps(method)
    def run(*args, **kwargs):
        gate().require_running()
        return method(*args, **kwargs)
    return run


def running():
    try:
        gate().require_running()
        return True
    except MaintenanceDenied:
        return False


def spawn_admitted(target, *, role, object_key, name, args=(), kwargs=None, continuation=False, waiting=False):
    """在启动线程前登记，取消等待项不产生业务副作用；只续同一个已开始对象。"""
    parent = current() if continuation and not waiting else None
    control = gate()
    ticket = control._acquire(role, object_key, parent)
    def run():
        try:
            with ticket.bind():
                if not waiting:
                    ticket.start()
                target(*args, **(kwargs or {}))
        except MaintenanceDenied:
            pass
        finally:
            ticket.close()
    thread = threading.Thread(target=run, daemon=True, name=name)
    try:
        thread.start()
    except BaseException:
        ticket.close()
        raise
    return thread


def guarded(role, identity=None, *, waiting=False):
    """有限执行单项的统一门面；不用于把整批任务当作已接纳项。"""
    def decorate(method):
        @wraps(method)
        def run(*args, **kwargs):
            key = identity(*args, **kwargs) if identity else role
            with gate().admit(role, key) as ticket:
                if not waiting:
                    ticket.start()
                return method(*args, **kwargs)
        return run
    return decorate


@contextmanager
def claimed(role, claim, identity):
    """在未知具体对象的原子领取前登记，领取结果绑定对象，覆盖至回写结束。"""
    with gate().admit(role, "claim:" + uuid.uuid4().hex) as ticket:
        ticket.start()
        result = claim()
        if result:
            with ticket.gate._locked():
                ticket.key = str(identity(result))
                ticket.row["object"] = ticket.key
                ticket.stream.seek(0)
                json.dump(ticket.row, ticket.stream)
                ticket.stream.truncate()
                ticket.stream.flush()
        yield result

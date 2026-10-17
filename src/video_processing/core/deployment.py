"""部署步骤事务日志：失败闭锁，显式恢复，不自动回滚业务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 串行步骤、项目互斥、持久回执与未知动作恢复 |
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import json
import os
import time
import uuid

STEPS = ("baseline", "freeze", "stop", "backup", "adopt", "start", "resume", "restore", "verify")


class DeploymentDenied(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise DeploymentDenied(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise DeploymentDenied("RECEIPT_UNREADABLE") from exc


def write_json(path, value):
    """先持久化文件，再原子替换和同步目录；失败不被吞掉。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with open(temporary, "x", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def project_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeploymentDenied("DEPLOYMENT_BUSY") from exc
        yield


class Deployment:
    """适配器必须实现 preflight/action/verify/reconcile/final_status。

    action 抛异常或返回非成功结构均立即停止；reconcile 只读，不重试未知动作。
    """
    def __init__(self, plan, directory, adapter):
        self.plan, self.directory, self.adapter = plan, Path(directory), adapter
        self.path = self.directory / "journal.json"
        self.identity = digest(plan)

    def status(self):
        if not self.path.exists():
            return {"schema": 1, "plan": self.identity, "done": [], "pending": None, "state": "NEW"}
        row = read_json(self.path)
        require(isinstance(row, dict) and row.get("schema") == 1 and row.get("plan") == self.identity,
                "JOURNAL_IDENTITY_MISMATCH")
        done = row.get("done")
        require(isinstance(done, list) and done == list(STEPS[:len(done)]), "JOURNAL_ORDER_INVALID")
        pending = row.get("pending")
        require(pending is None or (len(done) < len(STEPS) and pending == STEPS[len(done)]),
                "JOURNAL_PENDING_INVALID")
        require(row.get("state") in {"RUNNING", "FAILED", "COMPLETE"}, "JOURNAL_STATE_INVALID")
        require(row["state"] != "COMPLETE" or (len(done) == len(STEPS) and pending is None),
                "JOURNAL_INCOMPLETE")
        return row

    def run(self, *, recover=False):
        with project_lock(self.adapter.lock_path):
            row = self.status()
            if row["state"] == "COMPLETE":
                self.adapter.final_status()
                return row
            require(row["state"] == "NEW" or recover, "RECOVERY_REQUIRED")
            if recover:
                outcome = self.adapter.reconcile(row)
                require(outcome in {"DONE", "NOT_STARTED", "READY"}, "ACTION_RESULT_UNKNOWN")
                if row["pending"]:
                    require(outcome in {"DONE", "NOT_STARTED"}, "ACTION_RESULT_UNKNOWN")
                    if outcome == "DONE":
                        row["done"].append(row["pending"])
                    row["pending"] = None
                write_json(self.path, row)
            for step in STEPS[len(row["done"]):]:
                try:
                    self.adapter.preflight(step)
                    row.update(state="RUNNING", pending=step, at=time.time(), error=None)
                    write_json(self.path, row)
                    result = self.adapter.action(step)
                    require(isinstance(result, dict) and result.get("ok") is True, "ACTION_RESULT_INVALID")
                    self.adapter.verify(step, result)
                    write_json(self.directory / (step + ".json"), result)
                    row["done"].append(step)
                    row.update(pending=None, at=time.time())
                    write_json(self.path, row)
                except Exception as exc:
                    row.update(state="FAILED", failed_step=step, error=getattr(exc, "code", type(exc).__name__), at=time.time())
                    # 回执写失败仍向外抛出；绝不在 finally 中启动或恢复服务。
                    write_json(self.path, row)
                    raise
            self.adapter.final_status()
            row.update(state="COMPLETE", at=time.time())
            write_json(self.path, row)
            return row

"""已接纳单项的子进程凭据：真实继承 flock FD + 精确 argv 摘要。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 维护期间仅允许原单项的指定命令继续，拒绝伪造及错配 |
"""
from __future__ import annotations
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import sys
import subprocess
import time
import uuid
from .maintenance import Admission, current, gate, MaintenanceDenied


def argv_hash(argv):
    return hashlib.sha256(json.dumps([str(Path(argv[0]).resolve()), *map(str, argv[1:])]).encode()).hexdigest()


@contextmanager
def child_continuation(cmd, kwargs):
    """父项一直计入排空；子记录还在父崩溃后由继承 FD 保持真实占用。"""
    from config.settings import settings
    ticket = current()
    script = next((i for i, arg in enumerate(cmd) if str(arg).endswith(".py")), None)
    if ticket is None or ticket.row["phase"] != "ACTIVE" or script is None:
        yield kwargs
        return
    control = ticket.gate
    path = control.directory / (uuid.uuid4().hex + ".json")
    stream = None
    try:
        with control._locked():
            stream = path.open("x+")
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            row = dict(id=path.stem, parent=ticket.row["id"], role="continuation",
                       object=ticket.key, pid=os.getpid(), phase="ACTIVE", at=time.time(),
                       argv=argv_hash(cmd[script:]))
            json.dump(row, stream)
            stream.flush()
        result = dict(kwargs)
        env = dict(result.get("env") or settings.maintenance_child_environment())
        env.update(MAINTENANCE_STATE_PATH=str(control.path), MAINTENANCE_CHILD_RECEIPT=path.stem,
                   MAINTENANCE_CHILD_FD=str(stream.fileno()))
        result.update(env=env, pass_fds=tuple(result.get("pass_fds", ())) + (stream.fileno(),))
        yield result
    finally:
        if stream:
            try:
                with control._locked():
                    path.unlink(missing_ok=True)
            finally:
                stream.close()


def _inherited():
    from config.settings import settings
    if not re.fullmatch(r"[a-f0-9]{32}", settings.maintenance_child_receipt) or settings.maintenance_child_fd < 0:
        raise MaintenanceDenied("INVALID_CONTINUATION")
    control = gate()
    path = control.directory / (settings.maintenance_child_receipt + ".json")
    try:
        with path.open("r") as separate:
            own = os.fstat(settings.maintenance_child_fd)
            other = os.fstat(separate.fileno())
            if (own.st_dev, own.st_ino) != (other.st_dev, other.st_ino):
                raise MaintenanceDenied("INVALID_CONTINUATION")
            row = json.load(separate)
            if row["phase"] != "ACTIVE" or row["argv"] != argv_hash(sys.argv):
                raise MaintenanceDenied("INVALID_CONTINUATION")
            try:
                fcntl.flock(separate, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise MaintenanceDenied("INVALID_CONTINUATION")
            # 只验证同一个 open-file-description 的独占锁，不能偷取另一进程的 FD。
            fcntl.flock(settings.maintenance_child_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stream = os.fdopen(os.dup(settings.maintenance_child_fd), "r+")
        row.update(parent_pid=row["pid"], pid=os.getpid())
        stream.seek(0)
        json.dump(row, stream)
        stream.truncate()
        stream.flush()
        return Admission(control, row["object"], stream, row)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MaintenanceDenied("INVALID_CONTINUATION") from exc


def single_script(method):
    @wraps(method)
    def run(*args, **kwargs):
        from config.settings import settings
        if settings.maintenance_child_receipt:
            ticket = _inherited()
            try:
                with ticket.bind():
                    return method(*args, **kwargs)
            finally:
                ticket.stream.close()
        with gate().admit("script", argv_hash(sys.argv)) as ticket:
            ticket.start()
            return method(*args, **kwargs)
    return run


def run_admitted(cmd, **kwargs):
    """等待有限子执行者结束；只给同一在途单项传继承凭据。批次须逐项接入。"""
    ticket = current()
    if ticket and ticket.row["phase"] == "ACTIVE":
        with child_continuation(cmd, kwargs) as options:
            return subprocess.run(cmd, **options)
    with gate().admit("subprocess", argv_hash(list(map(str, cmd)))) as ticket:
        ticket.start()
        with child_continuation(cmd, kwargs) as options:
            return subprocess.run(cmd, **options)

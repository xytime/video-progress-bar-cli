"""有归属信息的非阻塞任务锁；退出即释放，文件残留不代表占用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-23 | Codex | 分离单视频、发布执行者与加工资源的互斥范围。 |
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class TaskLeaseBusy(RuntimeError):
    pass


class TaskLease:
    def __init__(self, path: Path, **owner):
        self.path = Path(path)
        self.owner = owner
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            payload = dict(self.owner, pid=os.getpid(), started_at=datetime.now(timezone.utc).isoformat())
            handle.seek(0)
            handle.truncate()
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
        except BlockingIOError as exc:
            handle.close()
            raise TaskLeaseBusy(str(self.path)) from exc
        except BaseException:
            handle.close()
            raise
        self.handle = handle
        return self

    def __exit__(self, *args):
        if self.handle:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None


def read_lease_owner(path: Path) -> dict:
    """只读检查内核锁；不将陈旧元数据当作活跃占用。"""
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    return json.load(handle) or {"stage": "占用信息正在更新"}
                except (ValueError, OSError):
                    return {"stage": "占用信息正在更新"}
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except FileNotFoundError:
        pass
    return {}

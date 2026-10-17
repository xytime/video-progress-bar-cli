"""隔离验收子进程；真实控制文件/锁/临时账本，无外部执行端。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 维护竞争、重启与正常生命周期证据 |
"""
import json
from pathlib import Path
import sqlite3
import sys
import time
import signal
from video_processing.core.maintenance import MaintenanceGate, MaintenanceDenied


def main():
    action, path, marker = sys.argv[1:4]
    control = MaintenanceGate(path)
    if action in {"enter", "resume"}:
        try:
            result = control.enter("并发暂停") if action == "enter" else control.resume(int(marker), validated=True)
            print(json.dumps(result), flush=True)
        except MaintenanceDenied as exc:
            print(json.dumps({"code": exc.code}), flush=True)
        return
    if action == "crash":
        import os
        os._exit(42)
    if action == "wait-resource":
        import fcntl
        with control.admit("resource", marker) as ticket:
            Path(marker + ".ready").touch()
            with Path(marker + ".lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    ticket.start()
                    Path(marker + ".begun").touch()
                except MaintenanceDenied as exc:
                    print(json.dumps({"code": exc.code}), flush=True)
        return
    if action in {"ui", "ignore-ui"}:
        from video_processing.core.maintenance_runtime import role_lease
        def stop(signum, frame):
            Path(marker + ".signal").write_text(str(signum))
            if action == "ui":
                raise SystemExit(0)
        signal.signal(signal.SIGTERM, stop)
        with role_lease("ui"):
            Path(marker + ".ready").touch()
            while not Path(marker + ".release").exists():
                time.sleep(.01)
        return
    if action == "continuation":
        from video_processing.core.maintenance_child import single_script
        @single_script
        def finish():
            Path(marker + ".finished").touch()
        try:
            finish()
        except MaintenanceDenied as exc:
            print(json.dumps({"code": exc.code}))
            raise SystemExit(2)
        return
    if action == "status":
        print(json.dumps(control.status()), flush=True)
        return
    with sqlite3.connect(str(path) + ".test.db", timeout=2) as db:
        db.execute("CREATE TABLE IF NOT EXISTS work (owner TEXT, item INTEGER, state TEXT)")
    for item in range(2):
        try:
            with control.admit("synthetic", marker + str(item)) as ticket:
                ticket.start()
                with sqlite3.connect(str(path) + ".test.db", timeout=2) as db:
                    db.execute("INSERT INTO work VALUES(?,?,?)", (marker, item, "STARTED"))
                if item == 0:
                    Path(marker + ".ready").touch()
                    deadline = time.monotonic() + 10
                    while not Path(marker + ".release").exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                with sqlite3.connect(str(path) + ".test.db", timeout=2) as db:
                    db.execute("UPDATE work SET state='FINISHED' WHERE owner=? AND item=?", (marker, item))
        except MaintenanceDenied as exc:
            print(json.dumps({"item": item, "code": exc.code}), flush=True)
            return


if __name__ == "__main__":
    main()

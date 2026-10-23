"""后台恢复执行者的独立启动互斥；不阻塞现有发布巡检。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 持久恢复队列独立执行。 |
"""
from pathlib import Path
import subprocess
from ..core.maintenance import guarded
from ..core.task_lease import TaskLease, TaskLeaseBusy, read_lease_owner
from .subprocess_env import build_subprocess_env


@guarded("publishing-recovery-launch")
def ensure_publishing_recovery_worker(db, root: Path):
    root = Path(root)
    out = root / "output"
    try:
        with TaskLease(out / "publishing_recovery_start.lock", stage="发布恢复启动互斥"):
            if read_lease_owner(out / "publishing_recovery_worker.lock"):
                return False
            if not (db.pending_publishing_recovery_setups() or db.pending_publishing_recovery_items()):
                return False
            with (out / "publishing_recovery_worker.log").open("a") as log:
                subprocess.Popen([str(root / ".venv/bin/python"), str(root / "scripts/run_publishing_recovery.py")],
                    cwd=root, env=build_subprocess_env(), stdout=log, stderr=log, start_new_session=True)
            return True
    except TaskLeaseBusy:
        return False

"""由现有巡检唤起持久恢复队列，任务执行期间不阻塞发布巡检。"""
from pathlib import Path
import subprocess

from video_processing.core.maintenance import guarded
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy, read_lease_owner
from .subprocess_env import build_subprocess_env


@guarded("delivery-recovery-launch")
def ensure_delivery_recovery_worker(db, root: Path):
    out = root / "output"
    try:
        with TaskLease(out / "delivery_recovery_start.lock", stage="恢复队列启动互斥"):
            if read_lease_owner(out / "delivery_recovery_worker.lock") or not db.has_due_delivery_recovery():
                return False
            with (out / "delivery_recovery_worker.log").open("a") as log:
                subprocess.Popen([str(root / ".venv/bin/python"), str(root / "scripts/run_delivery_recovery.py")],
                                 cwd=root, env=build_subprocess_env(), stdout=log, stderr=log,
                                 start_new_session=True)
            return True
    except TaskLeaseBusy:
        return False

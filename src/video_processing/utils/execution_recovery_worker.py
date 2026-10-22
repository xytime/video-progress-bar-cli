"""由既有统一巡检唤起人工等待队列；不占用发布巡检线程。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Codex | 复用维护准入、启动锁和独立工作进程。 |
"""
import subprocess
from video_processing.core.maintenance import guarded
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy, read_lease_owner
from .subprocess_env import build_subprocess_env
from .execution_recovery import execution_status


@guarded('execution-recovery-launch')
def ensure_execution_recovery_worker(db, root):
    out = root / 'output'
    if not db.list_execution_recovery(waiting_only=True):
        return False
    # 全局冷却期间不反复派生进程。任务优先级等由 worker 按真实身份检查。
    status = execution_status(db, out)
    if status['maintenance'] != 'RUNNING' or (status['cooldown'] or {}).get('active'):
        return False
    try:
        with TaskLease(out / 'execution_recovery_start.lock', stage='等待恢复启动互斥'):
            if read_lease_owner(out / 'execution_recovery_worker.lock'):
                return False
            with (out / 'execution_recovery_worker.log').open('a') as log:
                subprocess.Popen([str(root / '.venv/bin/python'), str(root / 'scripts/run_execution_recovery.py')],
                    cwd=root, env=build_subprocess_env(), stdout=log, stderr=log, start_new_session=True)
            return True
    except TaskLeaseBusy:
        return False

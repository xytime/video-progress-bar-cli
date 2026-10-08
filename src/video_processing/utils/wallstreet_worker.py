"""现有巡航启动独立二创执行者，主发布循环不等待渲染。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 借助现有 cron 和内核锁恢复二创队列，无 Codex GUI 依赖 |
"""
import subprocess
import time
from config.settings import settings
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy, read_lease_owner
from video_processing.utils.subprocess_env import build_subprocess_env


def ensure_wallstreet_worker():
    root = settings.project_root
    out = settings.default_output_dir
    try:
        with TaskLease(out/'wallstreet_start.lock',stage='二创启动互斥'):
            if read_lease_owner(out/'wallstreet_worker.lock'):
                return False
            poll = out/'wallstreet_last_poll.txt'
            try:
                if time.time()-float(poll.read_text()) < settings.wallstreet_ab_poll_seconds:
                    return False
            except (OSError, ValueError):
                pass
            from video_processing.db.database import PipelineDB
            db = PipelineDB(str(out/'pipeline.db'))
            if not db.get_wallstreet_experiment() and not db.get_wallstreet_pairs():
                return False
            with (out/'wallstreet_worker.log').open('a') as log:
                subprocess.Popen([str(root/'.venv/bin/python'),str(root/'scripts/run_wallstreet_ab.py'),'--once'],
                    cwd=root,env=build_subprocess_env(include_telegram=False),stdout=log,stderr=log,
                    start_new_session=True)
            poll.write_text(str(time.time()))
            return True
    except TaskLeaseBusy:
        return False

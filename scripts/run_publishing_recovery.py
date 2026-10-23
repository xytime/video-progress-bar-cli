"""每轮恢复最多正式启动一项；等待和进程重启由持久批次衔接。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 后台恢复执行入口，保留维护和所有原发布门禁。 |
"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from video_processing.core.maintenance import entry, guarded
from video_processing.core.maintenance_runtime import registered
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing.publishing_recovery import PublishingRecoveryService


@entry
@registered("publishing-recovery-worker")
@guarded("publishing-recovery")
def main():
    try:
        with TaskLease(ROOT / "output/publishing_recovery_worker.lock", stage="发布恢复执行者"):
            db = PipelineDB()
            PublishingRecoveryService(db, ROOT).dispatch_once(PipelineManager())
            return 0
    except TaskLeaseBusy:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

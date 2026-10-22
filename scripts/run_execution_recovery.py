"""统一调度唤起的人工等待任务执行者；不清除冷却，不重新领取未知结果。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Codex | 独立消费人工执行意图，复用单视频维护准入。 |
"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from video_processing.core.maintenance_child import single_script
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy
from video_processing.pipeline_manager import PipelineManager
from video_processing.utils.execution_recovery import dispatch_recovery_once


@single_script
def main():
    try:
        with TaskLease(ROOT / 'output/execution_recovery_worker.lock', stage='等待恢复执行者'):
            manager = PipelineManager(trigger_source='execution_recovery')
            dispatch_recovery_once(manager)
            manager.wait_for_review_notifications(timeout=120)
    except TaskLeaseBusy:
        pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""运行一次默认关闭的三源 canary 预加工队列；绝不执行发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 有限独立进程派发入口。 |
| 1.0.1 | 2026-10-29 | Codex | 调度日志使用 control 角色，不增加整片加工尝试。 |
"""
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from config.settings import settings
from video_processing.core.preparation_dispatch import run_preparation_dispatch
from video_processing.db.database import PipelineDB
from video_processing.core.maintenance_runtime import registered
from video_processing.utils.stage_events import StageJournal, bind_journal


@registered('preparation-dispatch')
def main():
    owner = uuid.uuid4().hex
    journal = StageJournal(settings.default_output_dir / '.stage-events' / 'preparation-dispatch' / (owner+'.jsonl'),
                           task_id='preparation-dispatch', attempt_id=owner,
                           role='control') if settings.enable_pipeline_stage_events else None
    outcome = 'unknown'
    try:
        with bind_journal(journal):
            result = run_preparation_dispatch(PipelineDB(), settings, output=settings.default_output_dir,
                                              project=Path(__file__).resolve().parents[1])
            outcome = result['state'].lower()
    finally:
        if journal:
            journal.close(outcome)
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

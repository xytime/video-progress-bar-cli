"""非发布窗口的字幕先行预加工入口。

crontab 可高频调用本脚本；PipelineManager 会在发布窗口和美股盘中直接退出，
并通过共享任务锁与发布巡航、仪表盘和手动任务串行化。本入口绝不调用平台上传器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增源字幕预检与后台预加工的受管 cron 入口 |
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_processing.pipeline_manager import PipelineManager


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    PipelineManager().run_preparation_job()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

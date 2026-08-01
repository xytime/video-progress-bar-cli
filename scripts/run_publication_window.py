"""自动发布巡航入口。

crontab 每分钟调用一次本脚本，确保完成处理与审查的候选无需等待发布时段。
跨进程非阻塞锁确保上一轮尚未结束时不并发启动。发布时段限制仅在
``ENABLE_PUBLIC_PUBLISH_WINDOWS=true`` 时由 PipelineManager 的平台提交闸门恢复。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增窗口内巡航入口，以 Settings 作为唯一窗口判定并避免定时任务重叠 |
| 1.1.0 | 2026-08-02 | Codex | 改为每分钟自动巡航，不再因发布时段跳过完整流水线 |
"""

from __future__ import annotations

import fcntl
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_processing.pipeline_manager import PipelineManager


LOCK_PATH = PROJECT_ROOT / "output" / "publication_window_runner.lock"


def run_publication_window() -> int:
    """串行执行一轮完整流水线；仅在已有巡航仍运行时跳过。"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("[PublicationWindow] 上一轮流水线仍在运行，本轮跳过。")
            return 0

        try:
            logging.info("[AutoPublish] 启动完整流水线。")
            PipelineManager().run_daily_job()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run_publication_window()


if __name__ == "__main__":
    raise SystemExit(main())

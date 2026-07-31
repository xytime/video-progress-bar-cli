"""发布窗口巡航入口。

crontab 每 15 分钟调用一次本脚本；只有 Settings 判定为有效发布窗口时，
才会运行完整 PipelineManager。跨进程非阻塞锁确保上一轮尚未结束时不并发启动。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增窗口内巡航入口，以 Settings 作为唯一窗口判定并避免定时任务重叠 |
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

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager


LOCK_PATH = PROJECT_ROOT / "output" / "publication_window_runner.lock"


def run_publication_window() -> int:
    """在有效窗口内串行执行一轮完整流水线；窗口外与重叠轮次均无副作用退出。"""
    if not settings.is_public_publish_window():
        logging.info("[PublicationWindow] 当前不在有效发布窗口，跳过完整流水线。")
        return 0

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("[PublicationWindow] 上一轮流水线仍在运行，本轮跳过。")
            return 0

        try:
            # 获锁后再判断一次，避免等待锁期间跨过窗口边界后仍启动发布。
            if not settings.is_public_publish_window():
                logging.info("[PublicationWindow] 等待锁期间窗口已关闭，跳过完整流水线。")
                return 0
            logging.info("[PublicationWindow] 有效窗口内，启动完整流水线。")
            PipelineManager().run_daily_job()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run_publication_window()


if __name__ == "__main__":
    raise SystemExit(main())

"""自动发布巡航入口。

crontab 每分钟调用一次本脚本，确保完成处理与审查的候选无需等待发布时段。
跨进程非阻塞锁确保上一轮尚未结束时不并发启动。发布时段限制仅在
``ENABLE_PUBLIC_PUBLISH_WINDOWS=true`` 时由 PipelineManager 的平台提交闸门恢复。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增窗口内巡航入口，以 Settings 作为唯一窗口判定并避免定时任务重叠 |
| 1.1.0 | 2026-08-02 | Codex | 改为每分钟自动巡航，不再因发布时段跳过完整流水线 |
| 1.2.0 | 2026-08-04 | Codex | 记录巡航实例 PID、Git revision 与心跳，区分已推送代码和实际运行版本 |
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_processing.pipeline_manager import PipelineManager


LOCK_PATH = PROJECT_ROOT / "output" / "publication_window_runner.lock"
RUN_STATUS_PATH = PROJECT_ROOT / "output" / "publication_window_status.json"
_HEARTBEAT_INTERVAL_SEC = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_revision() -> str:
    """读取本次实例启动时的 Git revision；不可用时显式标记未知。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write_run_status(status: dict[str, Any]) -> None:
    """原子写入单实例运行状态，供日志、面板和事故排查读取。"""
    RUN_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = RUN_STATUS_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(status, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(RUN_STATUS_PATH)


def _read_run_status() -> dict[str, Any]:
    try:
        return json.loads(RUN_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _start_heartbeat(status: dict[str, Any]) -> tuple[threading.Event, threading.Thread]:
    """低频刷新存活时间，避免锁跳过日志看起来像无进度。"""
    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(_HEARTBEAT_INTERVAL_SEC):
            status["last_heartbeat_at"] = _now_iso()
            _write_run_status(status)

    thread = threading.Thread(target=heartbeat, name="publication-window-heartbeat", daemon=True)
    thread.start()
    return stop_event, thread


def run_publication_window() -> int:
    """串行执行一轮完整流水线；仅在已有巡航仍运行时跳过。"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            active = _read_run_status()
            logging.info(
                "[PublicationWindow] 上一轮流水线仍在运行，本轮跳过。"
                " run_id=%s pid=%s revision=%s heartbeat=%s",
                active.get("run_id", "unknown"),
                active.get("pid", "unknown"),
                active.get("git_revision", "unknown"),
                active.get("last_heartbeat_at", "unknown"),
            )
            return 0

        started_at = _now_iso()
        status: dict[str, Any] = {
            "run_id": f"{int(time.time())}-{os.getpid()}",
            "pid": os.getpid(),
            "git_revision": _git_revision(),
            "state": "RUNNING",
            "started_at": started_at,
            "last_heartbeat_at": started_at,
        }
        _write_run_status(status)
        stop_heartbeat, heartbeat_thread = _start_heartbeat(status)
        try:
            logging.info(
                "[AutoPublish] 启动完整流水线。 run_id=%s revision=%s",
                status["run_id"],
                status["git_revision"],
            )
            PipelineManager().run_daily_job()
            status["state"] = "COMPLETED"
        except Exception as exc:
            status["state"] = "FAILED"
            status["error"] = str(exc)
            raise
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=1)
            status["last_heartbeat_at"] = _now_iso()
            status["ended_at"] = status["last_heartbeat_at"]
            _write_run_status(status)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run_publication_window()


if __name__ == "__main__":
    raise SystemExit(main())

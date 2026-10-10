"""独立成片发布执行者；不持加工锁，不受发布时间或重负载避让限制。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.5.0 | 2026-10-10 | Codex | 心跳回读当前 TED 原片清理开关和配方，验证独立执行者运行采用。 |
| 1.4.0 | 2026-10-09 | Codex | 非阻塞唤起独立二创执行者，不阻塞 A 发布。 |
| 1.3.0 | 2026-10-05 | Codex | 心跳暴露字幕共享期限、节流与源下载冷却配置，供运行采用验收。 |
| 1.2.0 | 2026-10-03 | Codex | 心跳暴露已加载的 TED 点赞率门槛及演讲评分线，支持运行采用回读。 |
| 1.0.0 | 2026-09-23 | Codex | 全天巡检已就绪成片，独立进程隔离与可回读心跳。 |
| 1.1.0 | 2026-09-27 | Codex | 心跳记录加载的封面首选方案与队列开关，验证部署采用。 |
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_processing.utils.wallstreet_worker import ensure_wallstreet_worker
from config.settings import settings
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy
from video_processing.pipeline_manager import PipelineManager


def dispatch_once(manager: PipelineManager) -> int:
    """只取就绪候选，不让高分未加工任务挤占发布名额。"""
    if settings.wechat_publishing_paused:
        return 0
    videos = manager.db.get_high_score_pending_videos(
        min_score=75, limit=1, ready_only=True,
        channel_min_scores=settings.auto_publish_channel_min_scores,
    )
    if not videos:
        return 0
    manager._process_single_video(videos[0], submission_only=True)
    return 1


def dispatch_english_world_once(manager: PipelineManager) -> int:
    """既有自动授权的英语世界成片同样独立续投，保留专用投稿器的全部闸门。"""
    if not settings.enable_english_world_auto_publish or settings.wechat_publishing_paused:
        return 0
    manager.db.restore_expired_english_world_operator_recoveries()
    item = manager.db.get_next_auto_approved_english_world_submission()
    if not item:
        return 0
    review_id = str(item["id"])
    manager._report_runtime_stage(review_id, "ENGLISH_WORLD_SUBMISSION")
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/submit_english_world_review.py"),
         "--review-id", review_id], cwd=ROOT, timeout=1800, check=False,
    )
    logging.info("英语世界提交执行者退出 review=%s code=%s", review_id, result.returncode)
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=5)
        git_revision = revision.stdout.strip() if revision.returncode == 0 else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        git_revision = "unknown"
    from video_processing.core.ffmpeg_slot import config_status
    from video_processing.processors.ted_source_cleanup import RECIPE as cleanup_recipe
    state = {"pid": os.getpid(), "stage": "IDLE", "current_video": None,
             "git_revision": git_revision,
             "ffmpeg_guard_enabled": subprocess.Popen.__module__ == "video_processing.core.ffmpeg_slot",
             **config_status(),
             "ai_cover_primary_provider": settings.ai_cover_primary_provider,
             "ai_cover_queue_enabled": settings.enable_codex_cover_queue,
             "ted_source_cleanup_enabled": settings.enable_ted_source_cleanup,
             "ted_opening_trim_enabled": settings.enable_ted_opening_trim,
             "ted_source_cleanup_recipe": cleanup_recipe,
             "ted_min_like_rate_pct": settings.ted_min_like_rate_pct,
             "speech_publish_score_line": settings.speech_publish_score_line,
             "subtitle_translation_total_timeout_seconds": settings.subtitle_translation_total_timeout_seconds,
             "google_translate_interval_seconds": settings.google_translate_interval_seconds,
             "youtube_auth_cooldown_seconds": settings.youtube_auth_cooldown_seconds,
             "started_at": time.time(), "stage_started_at": time.time()}
    stopped = threading.Event()
    state_lock = threading.Lock()
    status_path = out / "ready_publications_status.json"

    def report(update):
        with state_lock:
            if update.get("stage") != state.get("stage") or update.get("current_video") != state.get("current_video"):
                state["stage_started_at"] = time.time()
            state.update(update)

    def heartbeat():
        while not stopped.is_set():
            with state_lock:
                snapshot = dict(state, heartbeat_at=time.time(), **config_status())
            temp = status_path.with_suffix(".tmp")
            temp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            temp.replace(status_path)
            stopped.wait(5)

    try:
        with TaskLease(out / "ready_publications.lock", stage="全天发布巡检"):
            manager = PipelineManager(
                str(out / "pipeline.db"), status_reporter=report,
                trigger_source="ready_worker",
            )
            worker = threading.Thread(target=heartbeat, daemon=True)
            worker.start()
            try:
                while True:
                    try:
                        report({"stage": "POLLING", "current_video": None})
                        ensure_wallstreet_worker()
                        attempted = dispatch_once(manager)
                        attempted += dispatch_english_world_once(manager)
                        report({"stage": "IDLE", "current_video": None})
                    except Exception:
                        logging.exception("成片发布巡检失败；保留状态供下一轮恢复")
                        report({"stage": "ERROR"})
                        attempted = 0
                    if args.once:
                        return 0
                    # 完成一条即继续；被会话占用时最多每 15 秒重试。
                    wake = out / "ready_publications.wake"
                    version = wake.stat().st_mtime_ns if wake.exists() else 0
                    delay = 15
                    if attempted:
                        row = manager.db.get_high_score_pending_videos(limit=1, ready_only=True)
                        if row and not str(row[0].get("publication_wait_reason") or "").startswith("同账号"):
                            delay = 1
                    for _ in range(delay):
                        time.sleep(1)
                        if wake.exists() and wake.stat().st_mtime_ns != version:
                            break
            finally:
                stopped.set()
                worker.join(timeout=6)
    except TaskLeaseBusy:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

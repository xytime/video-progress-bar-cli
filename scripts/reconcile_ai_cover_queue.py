#!/usr/bin/env python3
"""程序消费 AGY 封面完成物，独立质量核验失败后执行本地兜底。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增两分钟巡查协调器，保证 AI 底图超时后确定性降级 |
| 1.1.0 | 2026-08-03 | Codex | AI 封面完成物也必须通过无大面积遮罩版式来源清单校验 |
| 1.2.0 | 2026-08-03 | Codex | 加锁并只允许 AI_COVER_PENDING 任务回到 PENDING，防止旧封面任务重发已发布视频 |
| 1.3.0 | 2026-08-20 | Codex | 记录 Anti-gravity 底图来源，并对不合格产物继续走确定性降级 |
| 1.4.0 | 2026-08-20 | Codex | 在 Codex deadline 与固定背景 deadline 之间自动调用 Anti-gravity 第一兜底 |
| 1.5.0 | 2026-09-18 | Antigravity | 传递 GEMINI_API_KEY 与 PATH 环境变量，并在非零退出时兜底写回失败记录 |
| 1.6.0 | 2026-09-18 | Antigravity | 接入统一子进程环境工厂 build_subprocess_env，统一管理子进程凭据与 PATH |
| 1.7.0 | 2026-09-27 | Codex | 备用生图使用项目 venv 与 agy CLI，不再调用 API Key SDK |
| 1.8.0 | 2026-09-27 | Codex | AGY 首选即时生成，三次失败或超时挂起，禁止新任务固定底图降级 |
"""

from __future__ import annotations

import fcntl
import hashlib
import shutil
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config.settings import settings
from video_processing.ai_cover_queue import AICoverQueue, AICoverTask
from video_processing.core.cover_policy import validate_dedicated_cover_file
from video_processing.db import PipelineDB
from video_processing.utils.subprocess_env import build_subprocess_env
from video_processing.utils.cover_agy import run_process, QUALITY_VERSION


logger = logging.getLogger(__name__)
LOCK_PATH = PROJECT_ROOT / "output" / "ai_cover_reconciler.lock"
_COVER_QUEUE_ACTIVE_STATUS = "AI_COVER_PENDING"


def _is_dedicated_cover(cover_path: Path) -> bool:
    provenance_path = cover_path.with_name(f"{cover_path.stem}_provenance.json")
    return validate_dedicated_cover_file(cover_path, provenance_path)


def _write_resolution(task: AICoverTask, source: str, visual_path: Path | None) -> None:
    payload = {
        "schema_version": 1,
        "task_id": task.task_id,
        "source": source,
        "cover_sha256": hashlib.sha256(Path(task.payload["final_cover_path"]).read_bytes()).hexdigest(),
        "provenance_sha256": hashlib.sha256(Path(task.payload["provenance_path"]).read_bytes()).hexdigest(),
        "resolved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "visual_filename": visual_path.name if visual_path else None,
    }
    temporary = task.finish_dir / ".resolution.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(task.finish_dir / "resolution.json")


def _write_antigravity_attempt(task: AICoverTask, status: str, error: str) -> None:
    path = task.finish_dir / "antigravity_attempt.json"
    try:
        previous = json.loads(path.read_text())
        count = int(previous.get("attempt_number", 0))
    except (OSError, ValueError, TypeError):
        count = 0
    path.write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "provider": "antigravity",
                "status": status,
                "attempt_number": count + 1,
                "stage": "worker_launch",
                "failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "error": error[:500],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_antigravity(task: AICoverTask) -> None:
    attempt_path = task.finish_dir / "antigravity_attempt.json"
    before = attempt_path.read_bytes() if attempt_path.exists() else None
    runtime_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not runtime_python.is_file():
        _write_antigravity_attempt(task, "failed", f"runtime not found: {runtime_python}")
        return
    command = [
        str(runtime_python),
        str(PROJECT_ROOT / "scripts" / "run_antigravity_cover_doer.py"),
        "--task-id",
        task.task_id,
        "--queue-dir",
        str(PROJECT_ROOT / settings.ai_cover_queue_dir),
        "--finish-dir",
        str(PROJECT_ROOT / settings.ai_cover_finish_dir),
        "--model",
        settings.antigravity_model,
        "--agy-bin",
        settings.agy_command,
        "--timeout-seconds",
        str(settings.antigravity_timeout_seconds),
        "--review-timeout-seconds", str(settings.ai_cover_quality_timeout_seconds),
    ]
    env = build_subprocess_env(include_gemini=False, include_telegram=False)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_IDS"):
        env.pop(key, None)
    try:
        result = run_process(command, cwd=PROJECT_ROOT,
                             timeout=settings.antigravity_timeout_seconds + settings.ai_cover_quality_timeout_seconds + 60,
                             env=env, cleanup_grace=15)
    except (RuntimeError, OSError) as exc:
        after = attempt_path.read_bytes() if attempt_path.exists() else None
        if after == before:
            _write_antigravity_attempt(task, "failed", str(exc))
        logger.warning("[%s] worker unavailable: %s", task.task_id, exc)
        return
    if result.returncode != 0:
        logger.warning(
            "[%s] Anti-gravity rejected; stderr=%s stdout=%s",
            task.task_id,
            result.stderr[-300:],
            result.stdout[-300:],
        )
        after = attempt_path.read_bytes() if attempt_path.exists() else None
        if after == before:
            _write_antigravity_attempt(
                task,
                "failed",
                (result.stderr or result.stdout)[-500:] or "unknown rejection",
            )


def _render_locked(
    task: AICoverTask,
    visual_path: Path | None,
    db: PipelineDB | None = None,
    visual_source: str | None = None,
) -> bool:
    db = db or PipelineDB()
    youtube_id = str(task.payload["youtube_id"])
    slice_index = int(task.payload["slice_index"])
    video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not video:
        logger.warning("[%s] video row missing; skip cover resolution", task.task_id)
        return False
    if video["status"] != _COVER_QUEUE_ACTIVE_STATUS:
        logger.warning(
            "[%s] skip cover resolution for %s_s%s because current status is %s",
            task.task_id,
            youtube_id,
            slice_index,
            video["status"],
        )
        return False
    if not db.can_resolve_ai_cover(youtube_id, slice_index=slice_index):
        return False

    target = Path(str(task.payload["final_cover_path"]))
    provenance = Path(str(task.payload["provenance_path"]))
    brief = Path(str(task.payload["brief_path"]))
    cover_payload = dict(task.payload["cover_payload"])
    if visual_path:
        cover_payload.update(
            {
                "visual_asset_path": str(visual_path),
                "headline_position": "upper_left",
                "visual_direction": str(task.payload["visual_brief"].get("visual_direction", "")),
            }
        )
    command = [
        str(PROJECT_ROOT / ".venv" / "bin" / "python"),
        str(PROJECT_ROOT / "scripts" / "cover_generator.py"),
        "--payload", json.dumps(cover_payload, ensure_ascii=False),
        "--output", str(target),
        "--provenance-output", str(provenance),
    ]
    if task.payload.get("content_aware"):
        command.extend(["--content-aware", "--brief-output", str(brief)])
    # 先在任务目录输出，避免子进程失败留下半成品正式封面。
    staged = task.finish_dir / "rendered"
    staged.mkdir(exist_ok=True)
    staged_target = staged / target.name
    staged_provenance = staged / provenance.name
    command[command.index("--output") + 1] = str(staged_target)
    command[command.index("--provenance-output") + 1] = str(staged_provenance)
    if "--brief-output" in command:
        command[command.index("--brief-output") + 1] = str(staged / brief.name)
    result = run_process(command, cwd=PROJECT_ROOT, timeout=90, env=build_subprocess_env())
    if result.returncode != 0 or not _is_dedicated_cover(staged_target):
        logger.error("[%s] cover render failed: %s", task.task_id, result.stderr[:400])
        return False
    current = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
    if not current or not db.can_resolve_ai_cover(youtube_id, slice_index=slice_index):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    for source, destination in ((staged_target, target), (staged_provenance, provenance), (staged / brief.name, brief)):
        if source.is_file():
            temporary = destination.with_name(destination.name + ".cover-tmp")
            shutil.copy2(source, temporary)
            temporary.replace(destination)
    _write_resolution(
        task,
        visual_source or ("codex_ai_visual" if visual_path else "deterministic_fallback"),
        visual_path,
    )
    if not db.mark_ai_cover_resolved(youtube_id, slice_index=slice_index):
        logger.warning("[%s] cover rendered but video status changed before requeue; leaving row unchanged", task.task_id)
        return False
    try:
        (target.parent / "ready_publications.wake").touch()
    except OSError as exc:
        logger.warning("发布唤醒标记写入失败，15 秒巡检继续兜底：%s", exc)
    logger.info("[%s] cover resolved via %s", task.task_id, visual_source or "fallback")
    return True


def _render(task, visual_path, db=None, visual_source=None):
    with (task.finish_dir / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        return _render_locked(task, visual_path, db, visual_source)


def _recover_resolution(task, db):
    """回执已落盘但数据库 CAS 尚未完成时，在哈希绑定后恢复。"""
    try:
        receipt = json.loads((task.finish_dir / "resolution.json").read_text())
        target, provenance = Path(task.payload["final_cover_path"]), Path(task.payload["provenance_path"])
        if (receipt.get("task_id") != task.task_id or not _is_dedicated_cover(target)
                or receipt.get("cover_sha256") != hashlib.sha256(target.read_bytes()).hexdigest()
                or receipt.get("provenance_sha256") != hashlib.sha256(provenance.read_bytes()).hexdigest()):
            return False
    except (OSError, ValueError, TypeError):
        return False
    return db.mark_ai_cover_resolved(str(task.payload["youtube_id"]), slice_index=int(task.payload["slice_index"]))


def reconcile() -> int:
    if not settings.enable_codex_cover_queue:
        return 0
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("[AI Cover] previous reconciler run is still active; skip this round")
            return 0

        try:
            logger.info("[AI Cover] loaded primary=%s; quality=agy-cover-quality-v1; local fallback enabled; Codex disabled",
                        settings.ai_cover_primary_provider)
            queue = AICoverQueue(
                PROJECT_ROOT / settings.ai_cover_queue_dir,
                PROJECT_ROOT / settings.ai_cover_finish_dir,
            )
            db = PipelineDB()
            resolved = 0
            for task in queue.list_tasks():
                video = db.get_video_by_youtube_id(str(task.payload["youtube_id"]), slice_index=int(task.payload["slice_index"]))
                if not video or not db.can_resolve_ai_cover(str(task.payload["youtube_id"]), slice_index=int(task.payload["slice_index"])):
                    continue
                # 旧 AGY 挂起项保留证据和状态，必须具名授权后恢复，避免升级批量触发历史投稿。
                if task.primary_provider == "agy" and task.payload.get("quality_contract") != QUALITY_VERSION:
                    continue
                if (task.finish_dir / "resolution.json").is_file():
                    resolved += int(_recover_resolution(task, db))
                    continue
                if (task.finish_dir / "fallback_attempt.json").is_file():
                    continue
                visual = queue.accepted_visual(task)
                generated_by = queue.accepted_source(task)
                if (
                    visual is None
                    and (task.primary_provider == "agy" or settings.enable_antigravity_cover_fallback)
                    and queue.antigravity_due(task)
                ):
                    _run_antigravity(task)
                    visual = queue.accepted_visual(task)
                    generated_by = queue.accepted_source(task)
                visual_source = "antigravity_ai_visual" if generated_by == "antigravity_imagegen" else "codex_ai_visual"
                render_failed = False
                if visual:
                    try:
                        rendered = _render(task, visual, db, visual_source)
                    except (RuntimeError, OSError) as exc:
                        rendered = False
                        logger.error("[%s] AI cover layout failed: %s", task.task_id, exc)
                    if rendered:
                        resolved += 1
                        continue
                    if rendered is None or (task.finish_dir / "resolution.json").is_file():
                        continue
                    render_failed = True
                if render_failed or (visual is None and queue.should_fallback(task)):
                    try:
                        fallback_ok = _render(task, None, db)
                    except (RuntimeError, OSError) as exc:
                        fallback_ok = False
                        logger.error("[%s] fallback failed: %s", task.task_id, exc)
                    if fallback_ok:
                        resolved += 1
                    elif fallback_ok is False and not queue._has_fresh_claim(task, datetime.now(timezone.utc)):
                        (task.finish_dir / "fallback_attempt.json").write_text(json.dumps(
                            {"task_id": task.task_id, "status": "failed", "reason": "LOCAL_COVER_FALLBACK_FAILED"}))
                        db.update_ai_cover_wait_reason(str(task.payload["youtube_id"]),
                            "本地封面兜底失败，需具名恢复；详见封面队列日志", slice_index=int(task.payload["slice_index"]))
                elif visual is None and task.primary_provider == "agy" and not queue.antigravity_due(task):
                    if not queue._has_fresh_claim(task, datetime.now(timezone.utc)):
                        reason = f"AGY 封面等待重试或本地兜底：{task.task_id}（详见 antigravity_attempt.json）"
                        if video.get("error_msg") != reason:
                            db.update_ai_cover_wait_reason(str(task.payload["youtube_id"]), reason,
                                                          slice_index=int(task.payload["slice_index"]))
                        logger.warning("[%s] %s", task.task_id, reason)
            return resolved
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    resolved = reconcile()
    logger.info("[AI Cover] resolved=%s", resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

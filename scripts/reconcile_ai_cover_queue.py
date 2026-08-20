#!/usr/bin/env python3
"""消费 Codex AI 封面完成物，并在 deadline 前后执行封面合成或降级。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增两分钟巡查协调器，保证 AI 底图超时后确定性降级 |
| 1.1.0 | 2026-08-03 | Codex | AI 封面完成物也必须通过无大面积遮罩版式来源清单校验 |
| 1.2.0 | 2026-08-03 | Codex | 加锁并只允许 AI_COVER_PENDING 任务回到 PENDING，防止旧封面任务重发已发布视频 |
| 1.3.0 | 2026-08-20 | Codex | 记录 Anti-gravity 底图来源，并对不合格产物继续走确定性降级 |
"""

from __future__ import annotations

import fcntl
import json
import logging
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
        "resolved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "visual_filename": visual_path.name if visual_path else None,
    }
    (task.finish_dir / "resolution.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _render(
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
    result = subprocess.run(command, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=90, check=False)
    if result.returncode != 0 or not _is_dedicated_cover(target):
        logger.error("[%s] cover render failed: %s", task.task_id, result.stderr[:400])
        return False
    _write_resolution(
        task,
        visual_source or ("codex_ai_visual" if visual_path else "deterministic_fallback"),
        visual_path,
    )
    if not db.mark_ai_cover_resolved(youtube_id, slice_index=slice_index):
        logger.warning("[%s] cover rendered but video status changed before requeue; leaving row unchanged", task.task_id)
        return False
    logger.info("[%s] cover resolved via %s", task.task_id, "Codex visual" if visual_path else "fallback")
    return True


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
            queue = AICoverQueue(
                PROJECT_ROOT / settings.ai_cover_queue_dir,
                PROJECT_ROOT / settings.ai_cover_finish_dir,
            )
            db = PipelineDB()
            resolved = 0
            for task in queue.list_tasks():
                if (task.finish_dir / "resolution.json").is_file():
                    continue
                target = Path(str(task.payload["final_cover_path"]))
                if _is_dedicated_cover(target):
                    continue
                visual = queue.accepted_visual(task)
                generated_by = queue.accepted_source(task)
                visual_source = "antigravity_ai_visual" if generated_by == "antigravity_imagegen" else "codex_ai_visual"
                if visual and _render(task, visual, db, visual_source):
                    resolved += 1
                elif visual is None and queue.should_fallback(task) and _render(task, None, db):
                    resolved += 1
            return resolved
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return reconcile()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""消费 Codex AI 封面完成物，并在 deadline 前后执行封面合成或降级。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增两分钟巡查协调器，保证 AI 底图超时后确定性降级 |
| 1.1.0 | 2026-08-03 | Codex | AI 封面完成物也必须通过无大面积遮罩版式来源清单校验 |
"""

from __future__ import annotations

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


def _render(task: AICoverTask, visual_path: Path | None) -> bool:
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
    _write_resolution(task, "codex_ai_visual" if visual_path else "deterministic_fallback", visual_path)
    PipelineDB().update_video_status(
        str(task.payload["youtube_id"]),
        "PENDING",
        error_msg=None,
        slice_index=int(task.payload["slice_index"]),
    )
    logger.info("[%s] cover resolved via %s", task.task_id, "Codex visual" if visual_path else "fallback")
    return True


def reconcile() -> int:
    if not settings.enable_codex_cover_queue:
        return 0
    queue = AICoverQueue(
        PROJECT_ROOT / settings.ai_cover_queue_dir,
        PROJECT_ROOT / settings.ai_cover_finish_dir,
    )
    resolved = 0
    for task in queue.list_tasks():
        target = Path(str(task.payload["final_cover_path"]))
        if _is_dedicated_cover(target):
            continue
        visual = queue.accepted_visual(task)
        if visual and _render(task, visual):
            resolved += 1
        elif visual is None and queue.should_fallback(task) and _render(task, None):
            resolved += 1
    return resolved


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return reconcile()


if __name__ == "__main__":
    raise SystemExit(main())

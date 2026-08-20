#!/usr/bin/env python3
"""将经过人工视觉验收的 Anti-gravity 产物接入 AI 封面队列。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-20 | Codex | 新增 Anti-gravity JPG/PNG 到队列 visual.png 的 fail-closed 适配器 |
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config.settings import settings
from video_processing.ai_cover_queue import AICoverQueue, AICoverTask


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _completed_at(source: Path, value: Optional[str]) -> datetime:
    if value:
        return _parse_time(value)
    return datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc)


def _has_unexpired_claim(task: AICoverTask, now: datetime) -> bool:
    claim_path = task.finish_dir / "claim.json"
    if not claim_path.is_file():
        return False
    try:
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        return claim.get("task_id") == task.task_id and _parse_time(str(claim["claim_expires_at"])) > now
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return False


def import_visual(
    queue: AICoverQueue,
    task: AICoverTask,
    source: Path,
    *,
    reviewed_no_text: bool,
    completed_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Path:
    """转换并原子接入一张 Anti-gravity 底图；任何门禁失败都不写 result.json。"""
    current = now or datetime.now(timezone.utc)
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not reviewed_no_text:
        raise ValueError("必须先人工确认无文字、无 logo、无水印、非视频帧，再传 --reviewed-no-text")
    if _has_unexpired_claim(task, current):
        raise RuntimeError(f"任务仍被其他生成器 claim：{task.task_id}")
    result_path = task.finish_dir / "result.json"
    if result_path.exists() or (task.finish_dir / "resolution.json").exists():
        raise FileExistsError(f"任务已有完成结果：{task.task_id}")
    generated_at = completed_at or datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc)
    if generated_at > task.generation_deadline:
        raise ValueError("Anti-gravity 产物晚于 generation_deadline_at，拒绝接入")

    visual_path = task.finish_dir / "visual.png"
    temporary_visual = task.finish_dir / f".visual.png.tmp.{os.getpid()}"
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            if image.width < 720 or image.height < 960:
                raise ValueError(f"底图尺寸不足：{image.width}x{image.height}")
            image.save(temporary_visual, format="PNG")
        digest = hashlib.sha256(temporary_visual.read_bytes()).hexdigest()
        result = {
            "task_id": task.task_id,
            "generated_by": "antigravity_imagegen",
            "completed_at": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "visual_filename": "visual.png",
            "sha256": digest,
            "uses_video_frame": False,
            "human_visual_review": "reviewed_no_text",
            "source_artifact": str(source),
        }
        temporary_visual.replace(visual_path)
        temporary_result = task.finish_dir / f".result.json.tmp.{os.getpid()}"
        temporary_result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_result.replace(result_path)
    finally:
        temporary_visual.unlink(missing_ok=True)
    return visual_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--source", required=True, type=Path, help="Anti-gravity brain 目录中的 JPG/PNG 产物")
    parser.add_argument("--reviewed-no-text", action="store_true", help="确认无文字/logo/水印/视频帧后才允许接入")
    parser.add_argument("--completed-at", help="生成完成时间，UTC ISO-8601；默认使用源文件 mtime")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    queue = AICoverQueue(PROJECT_ROOT / settings.ai_cover_queue_dir, PROJECT_ROOT / settings.ai_cover_finish_dir)
    task = next((item for item in queue.list_tasks() if item.task_id == args.task_id), None)
    if task is None:
        raise SystemExit(f"未找到任务：{args.task_id}")
    visual = import_visual(
        queue,
        task,
        args.source,
        reviewed_no_text=args.reviewed_no_text,
        completed_at=_parse_time(args.completed_at) if args.completed_at else None,
    )
    print(json.dumps({"task_id": task.task_id, "visual": str(visual), "generated_by": "antigravity_imagegen"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

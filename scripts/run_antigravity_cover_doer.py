#!/usr/bin/env python3
"""用 Antigravity SDK 生成一张队列底图，并原子写回完成物。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-20 | Codex | 新增 Anti-gravity 图像工具第一兜底适配器 |
| 1.1.0 | 2026-08-20 | Codex | 增加 claim、OCR 无文字验收、超时窗口和原子回执 |
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_processing.ai_cover_queue import AICoverQueue, AICoverTask


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_CLAIM_SECONDS = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _claim(task: AICoverTask, now: datetime) -> Path:
    claim_path = task.finish_dir / "claim.json"
    if claim_path.is_file():
        try:
            current = json.loads(claim_path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(str(current["claim_expires_at"]).replace("Z", "+00:00"))
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            expires_at = now
        if expires_at > now:
            raise RuntimeError("fresh claim exists")
        claim_path.unlink(missing_ok=True)
    _write_json(
        claim_path,
        {
            "task_id": task.task_id,
            "claimed_at": _iso(now),
            "claim_expires_at": _iso(now + timedelta(seconds=_CLAIM_SECONDS)),
            "provider": "antigravity",
        },
    )
    return claim_path


def _sips_png(source: Path, destination: Path) -> None:
    destination.unlink(missing_ok=True)
    if source.suffix.lower() == ".png":
        shutil.copy2(source, destination)
        return
    result = subprocess.run(
        ["/usr/bin/sips", "-s", "format", "png", str(source), "--out", str(destination)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0 or not destination.is_file():
        raise RuntimeError(f"image conversion failed: {result.stderr[-300:]}")


def _dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("image dimensions unavailable")
    values: dict[str, int] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() in {"pixelWidth", "pixelHeight"}:
            values[key.strip()] = int(value.strip())
    width, height = values.get("pixelWidth", 0), values.get("pixelHeight", 0)
    if width < 720 or height < 960 or width >= height:
        raise RuntimeError(f"invalid portrait dimensions: {width}x{height}")
    ratio = width / height
    if not 0.60 <= ratio <= 0.90:
        raise RuntimeError(f"invalid portrait ratio: {width}x{height}")
    return width, height


def _ocr_text(path: Path) -> str:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise RuntimeError("tesseract is required for automatic no-text acceptance")
    result = subprocess.run(
        [tesseract, str(path), "stdout", "--psm", "11"],
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    if result.returncode != 0:
        raise RuntimeError(f"OCR validation failed: {result.stderr[-300:]}")
    return " ".join(result.stdout.split())


def _candidate_images(work_dir: Path, started_at: float) -> list[Path]:
    candidates = []
    for path in work_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        try:
            if path.stat().st_mtime >= started_at:
                candidates.append(path)
        except OSError:
            continue
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


async def _generate(args: argparse.Namespace, task: AICoverTask, work_dir: Path) -> None:
    from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig
    from google.antigravity.types import BuiltinTools

    brief = task.payload.get("visual_brief", {})
    direction = str(brief.get("visual_direction", "abstract technology"))
    keywords = ", ".join(str(item) for item in brief.get("visual_keywords", []))
    prompt = (
        f"Generate one dedicated portrait 3:4 background image for a technology news video cover. "
        f"Visual direction: {direction}. Keywords: {keywords}. "
        "Use abstract or original visual content only. Leave deliberate dark negative space in the "
        "upper-left title-safe area. Absolutely no text, letters, numbers, logos, watermark, UI, "
        "screenshot, video frame, thumbnail, or readable symbol. Do not create a title card. "
        "Call the generate_image tool exactly once; if the tool reports an error, stop and report it."
    )
    config = LocalAgentConfig(
        system_instructions=(
            "You are an automated cover-background worker. You must call generate_image for the "
            "requested bitmap. Never use video frames or screenshots. Never claim success without "
            "a generated image artifact."
        ),
        workspaces=[str(work_dir)],
        save_dir=str(work_dir),
        model=args.model,
        capabilities=CapabilitiesConfig(
            enabled_tools=[BuiltinTools.GENERATE_IMAGE, BuiltinTools.FINISH],
            image_model=args.image_model,
        ),
    )
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        async for _ in response.chunks:
            pass


def run(args: argparse.Namespace) -> int:
    queue = AICoverQueue(Path(args.queue_dir), Path(args.finish_dir))
    task = next((item for item in queue.list_tasks() if item.task_id == args.task_id), None)
    if task is None:
        raise RuntimeError(f"task not found: {args.task_id}")
    if (task.finish_dir / "result.json").is_file() or (task.finish_dir / "resolution.json").is_file():
        return 0
    now = _now()
    if now < task.generation_deadline:
        raise RuntimeError("Anti-gravity fallback is not due before generation deadline")
    if now >= task.fallback_after:
        raise RuntimeError("Anti-gravity fallback window has closed")

    attempt_path = task.finish_dir / "antigravity_attempt.json"
    if attempt_path.is_file():
        return 0
    claim_path = _claim(task, now)
    _write_json(
        attempt_path,
        {"task_id": task.task_id, "provider": "antigravity", "status": "running", "started_at": _iso(now)},
    )
    # Antigravity 的 workspace 校验会拒绝隐藏目录；生成过程目录本身不参与队列验收。
    work_dir = task.finish_dir / f"antigravity-run-{time.time_ns()}"
    work_dir.mkdir(parents=True, exist_ok=False)
    started_at = time.time()
    try:
        asyncio.run(_generate(args, task, work_dir))
        candidates = _candidate_images(work_dir, started_at)
        if not candidates:
            raise RuntimeError("generate_image returned no image artifact")
        visual_tmp = task.finish_dir / ".visual.antigravity.tmp.png"
        _sips_png(candidates[0], visual_tmp)
        width, height = _dimensions(visual_tmp)
        ocr_text = _ocr_text(visual_tmp)
        if ocr_text:
            raise RuntimeError(f"OCR detected text: {ocr_text[:160]}")
        visual = task.finish_dir / "visual.png"
        visual_tmp.replace(visual)
        completed_at = _now()
        if completed_at >= task.fallback_after:
            raise RuntimeError("generated image arrived after Anti-gravity fallback window")
        _write_json(
            task.finish_dir / "result.json",
            {
                "task_id": task.task_id,
                "generated_by": "antigravity_imagegen",
                "completed_at": _iso(completed_at),
                "visual_filename": "visual.png",
                "sha256": _sha256(visual),
                "uses_video_frame": False,
                "machine_visual_review": "ocr_empty",
                "ocr_text": "",
                "dimensions": {"width": width, "height": height},
                "source_artifact": str(candidates[0]),
            },
        )
        claim_path.unlink(missing_ok=True)
        _write_json(
            attempt_path,
            {"task_id": task.task_id, "provider": "antigravity", "status": "succeeded", "completed_at": _iso(completed_at)},
        )
        return 0
    except Exception as exc:
        _write_json(
            attempt_path,
            {"task_id": task.task_id, "provider": "antigravity", "status": "failed", "failed_at": _iso(_now()), "error": str(exc)[:500]},
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--queue-dir", required=True)
    parser.add_argument("--finish-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--image-model", required=True)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

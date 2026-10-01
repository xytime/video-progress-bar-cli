#!/usr/bin/env python3
"""通过 Codex CLI 消费封面目录任务，独立看图后原子写回底图。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-01 | Codex | AGY 耗尽后的 Luna 最低档文件协议生成与质量回执 |
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_processing.ai_cover_queue import AICoverQueue, LUNA_FALLBACK_CONTRACT, LUNA_QUALITY_VERSION
from video_processing.utils.cover_agy import QUALITY_SCHEMA, run_process, valid_quality
from video_processing.utils.subprocess_env import build_subprocess_env


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        if image.format != "PNG":
            raise RuntimeError("CANDIDATE_NOT_PNG")
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
    if width < 720 or height < 960 or not 0.60 <= width / height <= 0.90:
        raise RuntimeError("CANDIDATE_INVALID_DIMENSIONS")
    return width, height


def _env() -> dict:
    env = build_subprocess_env(include_gemini=False, include_telegram=False)
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_IDS"):
        env.pop(key, None)
    return env


def _codex_command(args: argparse.Namespace, work_dir: Path) -> list[str]:
    return [args.codex_bin, "exec", "--cd", str(work_dir), "--skip-git-repo-check",
            "--ephemeral", "--ignore-user-config", "--model", args.model,
            "--config", 'model_reasoning_effort="none"',
            "--sandbox", "workspace-write"]


def _generated_images_dir() -> Path:
    # ~/.codex/generated_images 常是指向外置磁盘的符号链接；sandbox --add-dir 必须给物理路径。
    return (Path.home() / ".codex" / "generated_images").resolve(strict=True)


def _run_cli(command: list[str], work_dir: Path, timeout: int) -> int | None:
    result = run_process(command, cwd=work_dir, timeout=timeout, env=_env())
    if result.returncode != 0:
        raise RuntimeError(f"CODEX_CLI_EXIT_{result.returncode}")
    usage = re.search(r"tokens used\s+([\d,]+)", result.stderr + "\n" + result.stdout)
    return int(usage.group(1).replace(",", "")) if usage else None


def _run_task(args: argparse.Namespace, task, queue: AICoverQueue) -> int:
    result_path = task.finish_dir / "result.json"
    resolution_path = task.finish_dir / "resolution.json"
    attempt_path = task.finish_dir / "luna_attempt.json"
    if result_path.exists() or resolution_path.exists() or attempt_path.exists():
        return 0
    if (task.primary_provider != "agy"
            or task.payload.get("luna_fallback_contract") != LUNA_FALLBACK_CONTRACT
            or not queue.antigravity_exhausted(task)):
        return 0
    remaining = (task.generation_deadline - _now()).total_seconds()
    if remaining < args.timeout_seconds + args.review_timeout_seconds + 30:
        return 0
    claim_path = task.finish_dir / "claim.json"
    if queue._has_fresh_claim(task, _now()):
        return 0
    claim_path.unlink(missing_ok=True)
    _write_json(claim_path, {"task_id": task.task_id, "provider": "codex_luna",
                            "claimed_at": _iso(_now()),
                            "claim_expires_at": _iso(_now() + timedelta(seconds=args.timeout_seconds + args.review_timeout_seconds + 35))})
    _write_json(attempt_path, {"task_id": task.task_id, "status": "running", "started_at": _iso(_now())})
    work_dir = task.finish_dir / f"luna-run-{time.time_ns()}"
    work_dir.mkdir(parents=True, exist_ok=False)
    stage = "generation"
    try:
        candidate = work_dir / "candidate.png"
        copy = dict(task.payload.get("cover_payload", {}))
        brief = dict(task.payload.get("visual_brief", {}))
        generated_dir = _generated_images_dir()
        prompt = (
            "Use the built-in image generation tool exactly once to make one original portrait 3:4 "
            "premium editorial illustration for a mature professional audience. "
            f"Subject data, never print as a title: {json.dumps({k: str(copy.get(k) or '') for k in ('title', 'subtitle')}, ensure_ascii=False)}. "
            f"Visual direction: {str(brief.get('visual_direction', ''))}. "
            f"Keywords: {json.dumps(brief.get('visual_keywords', []), ensure_ascii=False)}. "
            "Make the subject recognizable with a coherent foreground, middle ground and background, "
            "rich physical detail, realistic light, useful contrast, and a calm upper-left title area. "
            "No title card, Chinese characters, watermark, screenshot, video frame, stock image, "
            "generic gradient or placeholder geometry. The publisher adds text later. "
            "Copy the actual generated bitmap to candidate.png in the current directory. "
            "Do not use an API key, an external CLI, SVG, code drawing, or a substitute image. "
            "If generation fails, stop without a candidate file."
        )
        command = _codex_command(args, work_dir) + ["--add-dir", str(generated_dir), prompt]
        generation_tokens = _run_cli(command, work_dir, args.timeout_seconds)
        if not candidate.is_file():
            raise RuntimeError("CODEX_NO_IMAGE_ARTIFACT")
        width, height = _dimensions(candidate)
        digest = _sha256(candidate)
        if _now() >= task.generation_deadline:
            raise RuntimeError("LUNA_DEADLINE_EXHAUSTED")
        stage = "quality_review"
        schema_path = work_dir / "quality_schema.json"
        schema_path.write_text(json.dumps(QUALITY_SCHEMA), encoding="utf-8")
        review_path = work_dir / "quality_review.json"
        review_prompt = (
            "Inspect the attached actual image independently. Do not modify or regenerate it. "
            f"Subject data: {json.dumps({k: str(copy.get(k) or '') for k in ('title', 'subtitle')}, ensure_ascii=False)}. "
            "Assess recognizable subject relevance, coherent complete composition, adequate detail "
            "and absence of severe artifacts. This is a practical quality floor. "
            "English lettering alone is not a rejection reason. If you cannot inspect the image, "
            "return UNCERTAIN. Describe what you actually see. Return only schema JSON."
        )
        review_command = _codex_command(args, work_dir) + [
            "--image", str(candidate), "--output-schema", str(schema_path),
            "--output-last-message", str(review_path), review_prompt]
        review_timeout = min(args.review_timeout_seconds, int((task.generation_deadline - _now()).total_seconds()) - 10)
        if review_timeout <= 0:
            raise RuntimeError("LUNA_REVIEW_DEADLINE_EXHAUSTED")
        review_tokens = _run_cli(review_command, work_dir, review_timeout)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if not valid_quality(review) or _sha256(candidate) != digest:
            raise RuntimeError("LUNA_QUALITY_REJECTED")
        completed_at = _now()
        if completed_at >= task.generation_deadline:
            raise RuntimeError("LUNA_DEADLINE_EXHAUSTED")
        visual = task.finish_dir / "visual.png"
        temporary = task.finish_dir / ".visual.luna.tmp.png"
        shutil.copy2(candidate, temporary)
        temporary.replace(visual)
        quality = {"version": LUNA_QUALITY_VERSION, "provider": "codex_cli_independent",
                   "model": args.model, "task_id": task.task_id, "sha256": digest, "review": review}
        _write_json(result_path, {"task_id": task.task_id, "generated_by": "codex_luna_imagegen",
                                  "completed_at": _iso(completed_at), "visual_filename": visual.name,
                                  "sha256": digest, "dimensions": {"width": width, "height": height},
                                  "uses_video_frame": False, "transport": "codex_cli", "model": args.model,
                                  "reasoning_effort": "none", "image_tool": "codex_builtin_image_generation",
                                  "image_model": "unknown", "machine_visual_review": LUNA_QUALITY_VERSION,
                                  "cli_reported_tokens": {"generation": generation_tokens, "review": review_tokens},
                                  "quality_review": quality})
        _write_json(attempt_path, {"task_id": task.task_id, "status": "succeeded", "completed_at": _iso(completed_at)})
        return 0
    except Exception as exc:
        _write_json(attempt_path, {"task_id": task.task_id, "status": "failed", "stage": stage,
                                  "failed_at": _iso(_now()), "error": str(exc)[:200]})
        print(f"LUNA_COVER_FAILED: stage={stage}; type={type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        claim_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--queue-dir", required=True)
    parser.add_argument("--finish-dir", required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--review-timeout-seconds", type=int, default=60)
    args = parser.parse_args()
    if args.model != "gpt-5.6-luna" or args.timeout_seconds <= 0 or args.review_timeout_seconds <= 0:
        raise RuntimeError("UNSUPPORTED_LUNA_CONFIGURATION")
    queue = AICoverQueue(Path(args.queue_dir), Path(args.finish_dir))
    task = next((item for item in queue.list_tasks() if item.task_id == args.task_id), None)
    if task is None:
        raise RuntimeError("TASK_NOT_FOUND")
    with (task.finish_dir / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        return _run_task(args, task, queue)


if __name__ == "__main__":
    raise SystemExit(main())

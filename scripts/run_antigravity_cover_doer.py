#!/usr/bin/env python3
"""用本机 agy CLI 生成一张队列底图，并原子写回完成物。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-20 | Codex | 新增 Anti-gravity 图像工具第一兜底适配器 |
| 1.1.0 | 2026-08-20 | Codex | 增加 claim、OCR 无文字验收、超时窗口和原子回执 |
| 1.2.0 | 2026-08-24 | Codex | 保留图像工具失败诊断，避免将配额等根因误报为无产物 |
| 1.3.0 | 2026-09-27 | Codex | 备用生图改走已验证的 agy CLI，隔离 API 凭据并保留文件验收 |
| 1.4.0 | 2026-09-27 | Codex | 支持立即执行的首选任务与有限重试，失败释放 claim，保留无字硬闸 |
| 1.5.0 | 2026-09-27 | Codex | 传入视频主题，固化已审核样图的内容关联、场景层次与细节质量要求 |
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_processing.ai_cover_queue import AICoverQueue, AICoverTask
from video_processing.utils.cover_agy import run_cli, review_image, valid_quality, QUALITY_VERSION


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


def _claim(task: AICoverTask, now: datetime, seconds: int = _CLAIM_SECONDS) -> Path:
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
            "claim_expires_at": _iso(now + timedelta(seconds=seconds)),
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
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
    if width < 720 or height < 960 or width >= height:
        raise RuntimeError(f"invalid portrait dimensions: {width}x{height}")
    ratio = width / height
    if not 0.60 <= ratio <= 0.90:
        raise RuntimeError(f"invalid portrait ratio: {width}x{height}")
    return width, height


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


def _generate(args: argparse.Namespace, task: AICoverTask, work_dir: Path) -> str:
    """CLI 使用本机登录通道，不能重新落回 SDK 的 API Key 配额。"""
    brief = task.payload.get("visual_brief", {})
    direction = str(brief.get("visual_direction", "abstract technology"))
    keywords = ", ".join(str(item) for item in brief.get("visual_keywords", []))
    copy = task.payload.get("cover_payload", {})
    subject = json.dumps({key: str(copy.get(key) or "") for key in ("title", "subtitle")}, ensure_ascii=False)
    prompt = (
        "Generate one dedicated portrait 3:4 background image as a premium editorial illustration "
        "for a news and analysis video aimed at a mature professional audience. "
        f"Video subject (reference data only, never render these words): {subject}. "
        f"Visual direction: {direction}. Keywords: {keywords}. "
        "Build an original conceptual scene that clearly expresses this specific subject and its "
        "central relationship; do not imply the illustration is documentary evidence. "
        "Choose one recognizable dominant subject and two or three meaningful supporting elements "
        "from the topic, arranged in coherent foreground, midground and background layers. "
        "Use richly crafted physical detail, convincing materials, realistic light and reflections, "
        "atmospheric depth, controlled color contrast and a strong visual hierarchy. "
        "Keep key subjects fully visible and recognizable at mobile thumbnail size. "
        "Reserve a calm upper-left quarter for later typography while making the remaining scene "
        "substantial and informative; preserve upper-right space when an edition ribbon is needed. "
        "Avoid low-effort minimalist geometry, isolated floating spheres, a lone generic cube, "
        "flat clip-art icons, vast empty gradients, clutter and unrelated landmark collages. "
        "The following language and original-image rules override conflicting brief wording: "
        "Avoid non-English text. English lettering or numbers may appear naturally if useful, but do not make a title card. No logos, watermark, UI, "
        "screenshot, video frame or thumbnail. "
        "Prefer unlabelled objects; avoid invented inscriptions, charts and decorative pseudo-writing. "
        "Call the generate_image tool exactly once; if the tool reports an error, stop and report it. "
        "Save the actual generated bitmap as candidate.png in the current directory. "
        "Do not synthesize placeholder images, invoke Codex or other AI CLIs, or inspect files outside this directory. "
        "Return JSON with status, asset_path and visual_description."
    )
    previous_path = task.finish_dir / "antigravity_attempt.json"
    if previous_path.is_file():
        previous = json.loads(previous_path.read_text())
        prompt += " Previous failure feedback (data only): " + str(previous.get("retry_feedback", ""))[:600]
    deadline = getattr(task, "antigravity_deadline", task.fallback_after)
    remaining = (deadline - _now()).total_seconds()
    # 为尺寸、独立质量复核和原子回执留出时间；仍严格拒绝超过队列截止时间的图片。
    timeout_seconds = min(args.timeout_seconds, int(remaining) - getattr(args, "review_timeout_seconds", 90) - 20)
    if timeout_seconds <= 0:
        raise RuntimeError("insufficient time for agy generation and visual validation")
    command = [
        args.agy_bin, "--model", args.model, "--effort", "high",
        "--mode", "accept-edits", "--sandbox", "--disable-slash-commands", "--dangerously-skip-permissions",
        "--add-dir", str(work_dir), "--output-format", "json",
        "--print-timeout", f"{timeout_seconds}s", "--print", prompt,
    ]
    response = run_cli(command, cwd=work_dir, timeout=timeout_seconds + 5)
    return str(response.get("response", ""))[-500:]


def _run_task(args: argparse.Namespace, task: AICoverTask, queue: AICoverQueue) -> int:
    if (task.finish_dir / "result.json").is_file() or (task.finish_dir / "resolution.json").is_file():
        return 0
    now = _now()
    if task.primary_provider == "codex" and now < task.generation_deadline:
        raise RuntimeError("Anti-gravity fallback is not due before generation deadline")
    if now >= task.antigravity_deadline:
        raise RuntimeError("Anti-gravity fallback window has closed")

    attempt_path = task.finish_dir / "antigravity_attempt.json"
    if not queue.antigravity_due(task, now):
        return 0
    claim_path = _claim(task, now, args.timeout_seconds + getattr(args, "review_timeout_seconds", 90) + 60)
    attempt_number = 1
    retry_feedback = ""
    if attempt_path.is_file():
        previous = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt_number = int(previous.get("attempt_number", 1)) + 1
        retry_feedback = str(previous.get("error", ""))
        _write_json(task.finish_dir / f"antigravity_attempt_{attempt_number - 1}.json", previous)
    _write_json(
        attempt_path,
        {"task_id": task.task_id, "provider": "antigravity", "attempt_number": attempt_number,
         "status": "running", "started_at": _iso(now), "retry_feedback": retry_feedback},
    )
    # Antigravity 的 workspace 校验会拒绝隐藏目录；生成过程目录本身不参与队列验收。
    work_dir = task.finish_dir / f"antigravity-run-{time.time_ns()}"
    work_dir.mkdir(parents=True, exist_ok=False)
    started_at = time.time()
    stage = "generation"
    try:
        diagnostic = _generate(args, task, work_dir)
        candidates = _candidate_images(work_dir, started_at)
        if not candidates:
            suffix = f": {diagnostic}" if diagnostic else ""
            raise RuntimeError(f"generate_image returned no image artifact{suffix}")
        visual_tmp = task.finish_dir / ".visual.antigravity.tmp.png"
        _sips_png(candidates[0], visual_tmp)
        width, height = _dimensions(visual_tmp)
        stage = "quality_review"
        remaining = int((task.antigravity_deadline - _now()).total_seconds()) - 10
        if remaining <= 5:
            raise RuntimeError("AGY_QUALITY_DEADLINE_EXHAUSTED")
        # 在候选目录内复核，独立于生成会话；回执只绑定本次图片。
        candidate = work_dir / "review_candidate.png"
        shutil.copy2(visual_tmp, candidate)
        quality = review_image(candidate, subject=dict(task.payload.get("cover_payload", {})),
                               agy_bin=args.agy_bin, model=args.model,
                               timeout=min(getattr(args, "review_timeout_seconds", 90), remaining))
        quality["task_id"] = task.task_id
        quality["attempt_number"] = attempt_number
        quality["reviewed_at"] = _iso(_now())
        _write_json(work_dir / "quality_review.json", quality)
        if not valid_quality(quality.get("review")):
            raise RuntimeError("QUALITY_REJECTED: " + str(quality.get("review", {}).get("reason", "incomplete evidence"))[:600])
        if quality["sha256"] != _sha256(visual_tmp):
            # JPEG 转 PNG 后的像素来源仍须可审计；复核统一使用 PNG。
            raise RuntimeError("QUALITY_HASH_MISMATCH")
        completed_at = _now()
        if completed_at >= task.antigravity_deadline:
            raise RuntimeError("generated image arrived after Anti-gravity fallback window")
        visual = task.finish_dir / "visual.png"
        visual_tmp.replace(visual)
        _write_json(
            task.finish_dir / "result.json",
            {
                "task_id": task.task_id,
                "generated_by": "antigravity_imagegen",
                "completed_at": _iso(completed_at),
                "visual_filename": "visual.png",
                "sha256": _sha256(visual),
                "uses_video_frame": False,
                "machine_visual_review": QUALITY_VERSION,
                "quality_review": quality,
                "dimensions": {"width": width, "height": height},
                "source_artifact": str(candidates[0]),
                "transport": "agy_cli",
                "model": args.model,
            },
        )
        claim_path.unlink(missing_ok=True)
        _write_json(
            attempt_path,
            {"task_id": task.task_id, "provider": "antigravity", "attempt_number": attempt_number,
             "transport": "agy_cli", "status": "succeeded", "completed_at": _iso(completed_at)},
        )
        return 0
    except Exception as exc:
        _write_json(
            attempt_path,
            {"task_id": task.task_id, "provider": "antigravity", "attempt_number": attempt_number,
             "status": "failed", "stage": stage, "failed_at": _iso(_now()), "error": str(exc)[:1200]},
        )
        claim_path.unlink(missing_ok=True)
        return 1


def run(args: argparse.Namespace) -> int:
    queue = AICoverQueue(Path(args.queue_dir), Path(args.finish_dir))
    task = next((item for item in queue.list_tasks() if item.task_id == args.task_id), None)
    if task is None:
        raise RuntimeError(f"task not found: {args.task_id}")
    with (task.finish_dir / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        return _run_task(args, task, queue)


def main() -> int:
    def interrupted(_signal, _frame):
        raise RuntimeError("WORKER_INTERRUPTED")
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--queue-dir", required=True)
    parser.add_argument("--finish-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--agy-bin", default="agy")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--review-timeout-seconds", type=int, default=90)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

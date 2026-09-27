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
from video_processing.utils.subprocess_env import build_subprocess_env


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


def _diagnostic_text(chunks: list[object]) -> str:
    """提取 SDK 的安全失败摘要，不把根因压缩成“无图片”。"""
    messages: list[str] = []
    for chunk in chunks:
        error = getattr(chunk, "error", None)
        if error:
            messages.append(str(error))
            continue
        # Thought 是模型过程性推理，常把真正的工具错误挤出 500 字符窗口；
        # 只保留用户可见的 Text 终态，确保账本留下可行动的失败根因。
        text = getattr(chunk, "text", None) if type(chunk).__name__ == "Text" else None
        if text:
            messages.append(str(text))
    return " ".join(messages).strip()[:500]


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
        "The following no-text and original-image rules override any conflicting brief wording: "
        "Absolutely no text, letters, numbers, logos, watermark, UI, "
        "screenshot, video frame, thumbnail, or readable symbol. Do not create a title card. "
        "Avoid displays, signs, labels, charts, patterns resembling glyphs, and small decorative marks. "
        "Call the generate_image tool exactly once; if the tool reports an error, stop and report it. "
        "Save the actual generated bitmap as candidate.png in the current directory. "
        "Do not synthesize placeholder images or inspect files outside this directory. "
        "Return JSON with status, asset_path and visual_description."
    )
    deadline = getattr(task, "antigravity_deadline", task.fallback_after)
    remaining = (deadline - _now()).total_seconds()
    # 为尺寸、OCR 和原子回执留出时间；仍严格拒绝超过队列截止时间的图片。
    timeout_seconds = min(args.timeout_seconds - 15, int(remaining) - 10)
    if timeout_seconds <= 0:
        raise RuntimeError("insufficient time for agy generation and visual validation")
    env = build_subprocess_env(include_gemini=False, include_telegram=False)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_IDS"):
        env.pop(key, None)
    command = [
        args.agy_bin, "--model", args.model, "--effort", "high",
        "--mode", "accept-edits", "--sandbox", "--dangerously-skip-permissions",
        "--add-dir", str(work_dir), "--output-format", "json",
        "--print-timeout", f"{timeout_seconds}s", "--print", prompt,
    ]
    result = subprocess.run(
        command, cwd=str(work_dir), capture_output=True, text=True,
        timeout=timeout_seconds + 5, check=False, env=env,
    )
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError):
        response = {}
    diagnostic = str(response.get("response", "")) if isinstance(response, dict) else ""
    status = str(response.get("status", "")).lower() if isinstance(response, dict) else ""
    if result.returncode != 0 or status in {"error", "failed", "timeout", "cancelled"}:
        raise RuntimeError(f"agy CLI failed: {(result.stderr or diagnostic or result.stdout)[-500:]}")
    return diagnostic[-500:]


def run(args: argparse.Namespace) -> int:
    queue = AICoverQueue(Path(args.queue_dir), Path(args.finish_dir))
    task = next((item for item in queue.list_tasks() if item.task_id == args.task_id), None)
    if task is None:
        raise RuntimeError(f"task not found: {args.task_id}")
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
    claim_path = _claim(task, now)
    attempt_number = 1
    if attempt_path.is_file():
        previous = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt_number = int(previous.get("attempt_number", 1)) + 1
        _write_json(task.finish_dir / f"antigravity_attempt_{attempt_number - 1}.json", previous)
    _write_json(
        attempt_path,
        {"task_id": task.task_id, "provider": "antigravity", "attempt_number": attempt_number,
         "status": "running", "started_at": _iso(now)},
    )
    # Antigravity 的 workspace 校验会拒绝隐藏目录；生成过程目录本身不参与队列验收。
    work_dir = task.finish_dir / f"antigravity-run-{time.time_ns()}"
    work_dir.mkdir(parents=True, exist_ok=False)
    started_at = time.time()
    try:
        diagnostic = _generate(args, task, work_dir)
        candidates = _candidate_images(work_dir, started_at)
        if not candidates:
            suffix = f": {diagnostic}" if diagnostic else ""
            raise RuntimeError(f"generate_image returned no image artifact{suffix}")
        visual_tmp = task.finish_dir / ".visual.antigravity.tmp.png"
        _sips_png(candidates[0], visual_tmp)
        width, height = _dimensions(visual_tmp)
        ocr_text = _ocr_text(visual_tmp)
        if ocr_text:
            raise RuntimeError(f"OCR detected text: {ocr_text[:160]}")
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
                "machine_visual_review": "ocr_empty",
                "ocr_text": "",
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
             "status": "failed", "failed_at": _iso(_now()), "error": str(exc)[:500]},
        )
        claim_path.unlink(missing_ok=True)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--queue-dir", required=True)
    parser.add_argument("--finish-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--agy-bin", default="agy")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

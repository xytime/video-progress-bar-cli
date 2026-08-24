#!/usr/bin/env python3
"""以 agy + Gemini 生成英语世界短视频的无字主视觉并合成封面。

该入口只写入指定输出目录；不发送 Telegram、不触发投稿，也不覆盖既有审核包。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 新增 agy 首选主视觉干跑入口与本地验收合成链路。 |
| 1.1.0 | 2026-08-24 | Codex | 支持 Telegram 人审待决主视觉及投稿包指定输出路径。 |
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cover import accept_and_normalize, build_agy_prompt, build_english_world_cover_payload, build_visual_brief
from cover.antigravity import generated_images, write_json


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "asset_path": {"type": "string"},
            "visual_description": {"type": "string"},
        },
        "required": ["status", "asset_path", "visual_description"],
        "additionalProperties": False,
    }


def _run_agy(*, agy_bin: str, model: str, work_dir: Path, prompt: str, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    """在候选隔离目录运行一次 Gemini 图像任务。"""
    schema_path = work_dir / "agy_result_schema.json"
    write_json(schema_path, _result_schema())
    command = [
        agy_bin,
        "--model", model,
        "--effort", "high",
        "--mode", "accept-edits",
        "--sandbox",
        "--dangerously-skip-permissions",
        "--add-dir", str(work_dir),
        "--output-format", "json",
        "--json-schema", str(schema_path),
        "--print-timeout", f"{timeout_seconds}s",
        "--print", prompt,
    ]
    return subprocess.run(command, cwd=str(work_dir), capture_output=True, text=True, timeout=timeout_seconds + 30, check=False)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--variants", type=int, default=3)
    parser.add_argument("--model", default="gemini-3.7-flash-high")
    parser.add_argument("--agy-bin", default=shutil.which("agy") or "agy")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--allow-ocr-suspect", action="store_true", help="仅允许标记为待 Telegram 人审，不视为机器无字通过")
    parser.add_argument("--cover-output", type=Path, help="最终投稿封面输出路径")
    parser.add_argument("--provenance-output", type=Path, help="最终封面来源审计输出路径")
    parser.add_argument("--payload-output", type=Path, help="最终规范化封面 payload 输出路径")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.variants < 1 or args.variants > 3:
        raise ValueError("--variants 必须在 1 到 3 之间")
    if args.timeout_seconds < 30:
        raise ValueError("--timeout-seconds 至少为 30")
    if not args.timeline.is_file():
        raise FileNotFoundError(args.timeline)

    timeline = json.loads(args.timeline.read_text(encoding="utf-8"))
    payload = build_english_world_cover_payload(timeline)
    output_dir = args.output_dir.resolve()
    run_dir = output_dir / f"agy-run-{datetime.now().strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "cover_payload.json", payload)
    brief = build_visual_brief(timeline, payload)
    write_json(run_dir / "cover_brief.json", brief)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "provider": "agy",
        "model": args.model,
        "started_at": _iso_now(),
        "brief_path": str((run_dir / "cover_brief.json").resolve()),
        "candidates": [],
    }
    selected_visual: Path | None = None
    selected_record: dict[str, Any] | None = None
    for index in range(args.variants):
        label = chr(ord("a") + index)
        variant_dir = run_dir / f"variant-{label}"
        variant_dir.mkdir()
        (variant_dir / "cover_brief.json").write_text((run_dir / "cover_brief.json").read_text(encoding="utf-8"), encoding="utf-8")
        prompt = build_agy_prompt(brief, variant_dir / "candidate.png")
        (variant_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
        try:
            result = _run_agy(
                agy_bin=args.agy_bin,
                model=args.model,
                work_dir=variant_dir,
                prompt=prompt,
                timeout_seconds=args.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            manifest["candidates"].append({"variant": label, "status": "runner_failed", "error": str(exc)[:500]})
            continue
        (variant_dir / "agy_stdout.json").write_text(result.stdout, encoding="utf-8")
        (variant_dir / "agy_stderr.txt").write_text(result.stderr[-4000:], encoding="utf-8")
        images = generated_images(variant_dir)
        if result.returncode != 0 or not images:
            manifest["candidates"].append(
                {"variant": label, "status": "generation_failed", "exit_code": result.returncode, "image_count": len(images)}
            )
            continue
        try:
            normalized = variant_dir / "visual.png"
            evidence = accept_and_normalize(images[0], normalized, allow_ocr_suspect=args.allow_ocr_suspect)
        except (OSError, RuntimeError, ValueError) as exc:
            manifest["candidates"].append({"variant": label, "status": "rejected", "error": str(exc)[:500]})
            continue
        record = {"variant": label, "status": "accepted", "visual_path": str(normalized.resolve()), **evidence}
        manifest["candidates"].append(record)
        if selected_visual is None:
            selected_visual = normalized
            selected_record = record

    manifest["completed_at"] = _iso_now()
    manifest["selected_variant"] = selected_record["variant"] if selected_record else None
    manifest_path = run_dir / "candidate_manifest.json"
    write_json(manifest_path, manifest)
    if selected_visual is None:
        print(json.dumps({"status": "no_accepted_visual", "manifest": str(manifest_path)}, ensure_ascii=False))
        return 2

    final_cover = (args.cover_output or output_dir / "cover_agi_primary_sample.jpg").resolve()
    final_provenance = (args.provenance_output or output_dir / "cover_agi_primary_sample_provenance.json").resolve()
    final_payload = (args.payload_output or output_dir / "cover_agi_primary_sample_payload.json").resolve()
    command = [
        str(PROJECT_ROOT / ".venv" / "bin" / "python"),
        str(PROJECT_ROOT / "scripts" / "generate_english_cover.py"),
        "--payload-file", str(run_dir / "cover_payload.json"),
        "--visual-asset", str(selected_visual),
        "--visual-asset-manifest", str(manifest_path),
        "--output", str(final_cover),
        "--provenance-output", str(final_provenance),
        "--payload-output", str(final_payload),
    ]
    rendered = subprocess.run(command, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180, check=False)
    if rendered.returncode != 0:
        raise RuntimeError(f"本地封面合成失败：{rendered.stderr[-500:]}")
    print(
        json.dumps(
            {
                "status": "accepted",
                "selected_variant": selected_record["variant"],
                "cover": str(final_cover),
                "provenance": str(final_provenance),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

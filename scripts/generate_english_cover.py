#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英语世界短视频专属封面生成 CLI (generate_english_cover.py)

支持通过 Timeline JSON、Payload JSON 或命令行参数直接生成符合 6:7 规范的报刊封面。

# Modification History
| Version | Date       | Author                         | Description                                            |
|---------|------------|--------------------------------|--------------------------------------------------------|
| 1.0.0   | 2026-08-24 | Gemini_3.7_Flash_High_planning | 初始创建：提供确定性 Prompt/JSON/Timeline 的多模式命令行封面生成入口 |
| 1.1.0   | 2026-08-24 | Codex | 改用共享载荷构建器，并输出 payload/timeline 哈希审计信息。 |
| 1.2.0   | 2026-08-24 | Codex | 支持绑定已验收的无字 Antigravity 主视觉。 |
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cover import CoverEngine, build_english_world_cover_payload, validate_english_world_cover_payload
from video_processing.core.cover_policy import compliant_cover_layout_policy


def extract_payload_from_timeline(timeline_data: dict) -> dict:
    """兼容旧调用；真实提取逻辑位于 core 层的共享纯函数。"""
    return build_english_world_cover_payload(timeline_data)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成英语世界短视频专属 6:7 报刊封面")
    parser.add_argument("--timeline", type=Path, help="已 enriched 的时间轴 JSON 文件路径")
    parser.add_argument("--payload", type=str, help="直接传入的 JSON payload 字符串")
    parser.add_argument("--payload-file", type=Path, help="JSON payload 文件路径")
    parser.add_argument("--output", "-o", required=True, type=Path, help="输出的封面 JPG/PNG 绝对路径")
    parser.add_argument("--provenance-output", type=Path, help="可选：输出的来源审计 JSON 文件路径")
    parser.add_argument("--payload-output", type=Path, help="可选：写入实际渲染的规范化 payload JSON")
    parser.add_argument("--visual-asset", type=Path, help="已通过无字验收的本地主视觉 PNG/JPG")
    parser.add_argument("--visual-asset-manifest", type=Path, help="可选：主视觉候选验收记录 JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = {}
    source_timeline_sha256 = None
    if sum(bool(value) for value in (args.timeline, args.payload, args.payload_file)) != 1:
        print("Error: 必须且只能提供 --timeline, --payload 或 --payload-file 之一", file=sys.stderr)
        return 1

    if args.timeline:
        if not args.timeline.is_file():
            print(f"Error: timeline file not found: {args.timeline}", file=sys.stderr)
            return 1
        timeline_bytes = args.timeline.read_bytes()
        timeline_data = json.loads(timeline_bytes)
        payload = extract_payload_from_timeline(timeline_data)
        source_timeline_sha256 = hashlib.sha256(timeline_bytes).hexdigest()
    elif args.payload_file:
        if not args.payload_file.is_file():
            print(f"Error: payload file not found: {args.payload_file}", file=sys.stderr)
            return 1
        payload = json.loads(args.payload_file.read_text(encoding="utf-8"))
    elif args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            print(f"Error: invalid JSON payload: {exc}", file=sys.stderr)
            return 1
    else:
        print("Error: 必须提供 --timeline, --payload 或 --payload-file 之一", file=sys.stderr)
        return 1

    try:
        payload = validate_english_world_cover_payload(payload)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    visual_asset = None
    if args.visual_asset:
        visual_asset = args.visual_asset.expanduser().resolve()
        if not visual_asset.is_file():
            print(f"Error: visual asset file not found: {visual_asset}", file=sys.stderr)
            return 1
        payload["visual_asset_path"] = str(visual_asset)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    engine = CoverEngine()
    layout = engine.generate(payload, str(args.output))
    payload_sha256 = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    if args.payload_output:
        args.payload_output.parent.mkdir(parents=True, exist_ok=True)
        args.payload_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.provenance_output:
        digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
        args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
        args.provenance_output.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "cover_kind": "dedicated_generated_image",
                    "uses_video_frame": False,
                    "cover_filename": args.output.name,
                    "cover_sha256": digest,
                    "audio_edition": payload.get("audio_edition", "original_audio_subtitled"),
                    "visual_asset": (
                        {
                            "kind": "dedicated_generated_visual",
                            "filename": visual_asset.name,
                            "sha256": hashlib.sha256(visual_asset.read_bytes()).hexdigest(),
                            "manifest": str(args.visual_asset_manifest.resolve()) if args.visual_asset_manifest and args.visual_asset_manifest.is_file() else None,
                        }
                        if visual_asset
                        else None
                    ),
                    "layout_policy": compliant_cover_layout_policy(),
                    "template_variant": layout["template_variant"],
                    "payload_sha256": payload_sha256,
                    "source_timeline_sha256": source_timeline_sha256,
                    "generator": "scripts/generate_english_cover.py@1.1.0",
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    print(f"✅ 英语封面生成成功: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

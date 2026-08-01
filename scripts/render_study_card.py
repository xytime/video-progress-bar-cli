#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将已对齐的新闻片段渲染为模板 A 学习卡片。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：提供不接入发布流程的独立渲染命令。 |
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.study_cards import StudyCardContent, StudyCardRenderer  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="渲染原片小窗 + 唱片 + 逐词红线的新闻精读卡片")
    parser.add_argument("--source", required=True, type=Path, help="采集后的原新闻视频")
    parser.add_argument("--timeline", required=True, type=Path, help="逐词时间线及学习内容 JSON")
    parser.add_argument("--output", required=True, type=Path, help="输出 MP4")
    parser.add_argument("--source-start", default=0.0, type=float, help="从原视频截取的起点（秒）")
    parser.add_argument("--duration", default=None, type=float, help="截取时长（秒，最大 30）")
    parser.add_argument("--keep-assets", action="store_true", help="保留静态底图与唱片资产，便于人工验收")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = json.loads(args.timeline.read_text(encoding="utf-8"))
        content = StudyCardContent.from_mapping(payload)
        StudyCardRenderer().render(
            args.source,
            content,
            args.output,
            source_start=args.source_start,
            duration=args.duration,
            keep_assets=args.keep_assets,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"render_study_card: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

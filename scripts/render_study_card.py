#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将已对齐的新闻片段渲染为模板 A 学习卡片。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：提供不接入发布流程的独立渲染命令。 |
| 1.1.0 | 2026-08-02 | Codex | 增加显式长样片测试开关，仅用于验收正文滚动，不改变生产 30 秒上限。 |
| 1.2.0 | 2026-08-02 | Codex | 支持传入六维时空真实小程序码，独立渲染支路不依赖发布系统。 |
| 1.3.0 | 2026-08-03 | Codex | 移除小程序码入口，改为支持右上影子跟读 Banner 参考图。 |
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.study_cards import StudyCardContent, StudyCardRenderer  # noqa: E402
from video_processing.study_cards.template_a import RecordUnderlineTemplate  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="渲染原片小窗 + 影子跟读 Banner + 逐词红线的新闻精读卡片")
    parser.add_argument("--source", required=True, type=Path, help="采集后的原新闻视频")
    parser.add_argument("--timeline", required=True, type=Path, help="逐词时间线及学习内容 JSON")
    parser.add_argument("--output", required=True, type=Path, help="输出 MP4")
    parser.add_argument("--source-start", default=0.0, type=float, help="从原视频截取的起点（秒）")
    parser.add_argument("--duration", default=None, type=float, help="截取时长（秒，生产最大 30）")
    parser.add_argument(
        "--allow-long-test",
        action="store_true",
        help="仅测试：允许最长 60 秒，用于验收长正文滚动；不可用于生产成片",
    )
    parser.add_argument("--keep-assets", action="store_true", help="保留静态底图与 Banner 资产，便于人工验收")
    parser.add_argument("--feature-reference", type=Path, help="右上影子跟读 Banner 参考图；不传则使用项目内置素材")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = json.loads(args.timeline.read_text(encoding="utf-8"))
        content = StudyCardContent.from_mapping(payload)
        StudyCardRenderer(RecordUnderlineTemplate(args.feature_reference)).render(
            args.source,
            content,
            args.output,
            source_start=args.source_start,
            duration=args.duration,
            keep_assets=args.keep_assets,
            allow_long_test=args.allow_long_test,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"render_study_card: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

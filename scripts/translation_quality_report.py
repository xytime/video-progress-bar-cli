#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""翻译质量审计报告汇总工具。

默认扫描 output/ 下的 *.translation_quality.json 与 *_copy_quality.json，
输出 provider、issue code、阻断/降级事件统计，便于排查字幕与文案翻译质量。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：命令行汇总翻译质量审计报告 |
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PRJ = Path(__file__).parent.parent
sys.path.insert(0, str(PRJ / "src"))

from video_processing.utils.translation_quality_report import aggregate_quality_reports  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate translation quality audit reports.")
    parser.add_argument("--root", type=Path, default=PRJ / "output", help="Directory or report file to scan.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    summary = aggregate_quality_reports(args.root)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()

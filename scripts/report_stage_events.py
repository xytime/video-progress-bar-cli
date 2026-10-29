#!/usr/bin/env python
"""只读汇总指定执行证据目录；不导入配置/数据库，不修改任何任务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 汇总尝试与阶段计时，未知交付证据不推断为发布。 |
| 1.0.1 | 2026-10-29 | Codex | 显式 UTC epoch 观测窗口；缺少窗口时有效吞吐未知。 |
"""
import argparse
import json
from pathlib import Path

from video_processing.utils.stage_events import summarize_events


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events_root', type=Path)
    parser.add_argument('--task', action='append', help='固定验收队列的任务ID；重复指定，缺证据仍保留在分母。')
    parser.add_argument('--window-start', type=float, help='显式观测窗口起点，UTC epoch 秒。')
    parser.add_argument('--window-end', type=float, help='显式观测窗口终点（不含），UTC epoch 秒。')
    args = parser.parse_args(argv)
    if not args.events_root.is_dir():
        parser.error('events_root must be an existing directory')
    if (args.window_start is None) != (args.window_end is None):
        parser.error('--window-start and --window-end must be provided together')
    window = None if args.window_start is None else (args.window_start, args.window_end)
    try:
        summary = summarize_events(sorted(args.events_root.rglob('*.jsonl')), cohort=args.task,
                                   observation_window=window)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()

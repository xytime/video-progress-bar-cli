#!/usr/bin/env python3
"""人工配音再制中心命令入口。

日常自动管线不调用此脚本；所有平台动作必须经 publish --confirm 明示触发。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 提供人工创建、质检放行、显式发布与状态查询命令 |
"""

import argparse
import json
import sys

from video_processing.dubbing import DubbingService


def main() -> int:
    parser = argparse.ArgumentParser(description="人工配音再制中心")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "status", "approve", "publish", "run"):
        item = subparsers.add_parser(command)
        item.add_argument("youtube_id", nargs="+" if command == "create" else None)
        item.add_argument("--slice-index", type=int, default=0)
        if command == "create":
            item.add_argument("--platform", action="append", default=[], choices=["wechat", "douyin", "kuaishou"])
            item.add_argument("--force-new-version", action="store_true")
        if command in {"publish", "run"}:
            item.add_argument("--platform", action="append", default=[], choices=["all", "wechat", "douyin", "kuaishou"])
            item.add_argument("--confirm", action="store_true")
        if command == "run":
            item.add_argument("--force-new-version", action="store_true")
    args = parser.parse_args()
    service = DubbingService()
    try:
        if args.command == "create":
            result = [
                service.create(youtube_id, slice_index=args.slice_index, platforms=args.platform, force_new_version=args.force_new_version)
                for youtube_id in args.youtube_id
            ]
        elif args.command == "status":
            result = service.status(args.youtube_id, slice_index=args.slice_index)
        elif args.command == "approve":
            result = service.approve(args.youtube_id, slice_index=args.slice_index)
        elif args.command == "run":
            result = service.run_selected(
                args.youtube_id, slice_index=args.slice_index, platforms=args.platform,
                confirm=args.confirm, force_new_version=args.force_new_version,
            )
        else:
            result = service.publish(args.youtube_id, slice_index=args.slice_index, platforms=args.platform, confirm=args.confirm)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "job": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

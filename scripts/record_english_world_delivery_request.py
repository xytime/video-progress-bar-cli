#!/usr/bin/env python3
"""记录英语世界成片的宿主交付请求。

生产代理在受限工作区内只负责制作与质检；封面、Telegram 审计和视频号上传由
日更协调器的宿主进程领取这个原子请求后执行。这样 Chromium 不会再由受限
工作区启动，而真实的宿主标准封面链路仍是首选。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-08-28 | Codex | 新增生产代理到宿主交付器的原子请求协议，隔离 Chromium 权限边界。 |
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="协调器指定的交付请求 JSON")
    parser.add_argument("--title", required=True, help="学习成片标题")
    parser.add_argument("--mp4", type=Path, help="已质检 MP4 的绝对路径")
    parser.add_argument("--manifest", type=Path, help="与 MP4 对应的 manifest 绝对路径")
    parser.add_argument("--failure", help="无可交付成片时的准确失败原因")
    return parser


def main() -> int:
    args = _parser().parse_args()
    title = args.title.strip()
    failure = (args.failure or "").strip()
    if not title:
        raise ValueError("--title must not be blank")
    if bool(failure) == bool(args.mp4 or args.manifest):
        raise ValueError("provide either --failure or both --mp4 and --manifest")
    if not failure and (args.mp4 is None or args.manifest is None):
        raise ValueError("successful delivery request requires --mp4 and --manifest")

    payload: dict[str, str] = {"title": title}
    if failure:
        payload.update({"kind": "failure", "failure": failure})
    else:
        payload.update(
            {
                "kind": "production",
                "mp4": str(args.mp4.resolve()),
                "manifest": str(args.manifest.resolve()),
            }
        )

    request_path = args.request.resolve()
    request_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = request_path.with_suffix(request_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(request_path)
    print(f"English World delivery request recorded: {request_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

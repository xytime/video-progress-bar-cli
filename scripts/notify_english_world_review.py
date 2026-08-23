#!/usr/bin/env python3
"""向 Telegram 发送英语世界短视频的人工审核回执。

该脚本只发送人工审核材料，绝不调用任何平台上传或投稿逻辑。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-22 | Codex | 新增每日英语世界短视频的 Telegram 审核材料通知。 |
"""

from __future__ import annotations

import argparse
import html
import logging
from pathlib import Path
import sys

import requests

from config.settings import settings

logger = logging.getLogger(__name__)


def _post_message(text: str) -> None:
    """发送文字回执；凭据只从 settings 读取。"""
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.active_telegram_chat_id or "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram 凭据或审核 chat_id 未配置")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=20,
    )
    response.raise_for_status()


def _post_document(path: Path, caption: str) -> None:
    """发送审核文件；不把发送成功误作平台发布成功。"""
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.active_telegram_chat_id or "").strip()
    with path.open("rb") as source:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (path.name, source)},
            timeout=120,
        )
    response.raise_for_status()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发送英语世界短视频 Telegram 审核回执")
    parser.add_argument("--title", required=True, help="成片标题")
    parser.add_argument("--mp4", type=Path, help="通过质检的成片 MP4")
    parser.add_argument("--manifest", type=Path, help="与成片对应的 manifest JSON")
    parser.add_argument("--failure", help="无合格素材或制作失败时的原因")
    return parser


def main() -> int:
    args = _parser().parse_args()
    safe_title = html.escape(args.title.strip())
    if args.failure:
        _post_message(
            "⚠️ <b>英语世界短视频｜今日未交付</b>\n"
            f"任务：{safe_title}\n"
            f"原因：{html.escape(args.failure.strip())}\n"
            "未生成成片，未触发任何视频号操作。"
        )
        return 0

    if not args.mp4 or not args.manifest:
        raise ValueError("成功审核回执必须同时提供 --mp4 与 --manifest")
    for artifact in (args.mp4, args.manifest):
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise FileNotFoundError(f"审核文件不存在或为空：{artifact}")

    _post_message(
        "✅ <b>英语世界短视频｜待人工审核</b>\n"
        f"标题：{safe_title}\n"
        "已生成学习成片与质检清单；仅发送 Telegram 审核，未提交视频号。"
    )
    _post_document(args.mp4, "英语世界短视频成片｜待审核，未提交视频号")
    _post_document(args.manifest, "英语世界短视频 manifest｜审核证据")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - launchd 必须获得非零退出码和可诊断错误
        logger.exception("英语世界 Telegram 审核回执失败：%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

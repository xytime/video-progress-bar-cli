"""每三小时只读质检报告，输出并可推送 Telegram。

报告只汇总数据库、监控快照和会话状态文件，绝不触发下载、重试、登录或发布。
本地 processed_videos 的 PUBLISHED 仅代表本地流程记录；快手/抖音的审核中和不确定
状态始终保留为待人工在作品管理中确认，不能据此推断平台侧已发布。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-07-28 | Codex | 初版：三小时只读质检、阻塞归因、遗留项和 Telegram 投递 |
| 1.1.0 | 2026-07-28 | Codex | 区分平台人工核验遗留与普通待投递队列，并提炼失败原因 |
| 1.2.0 | 2026-07-28 | Codex | 报告渲染迁入 video_processing.quality_report，并改为三秒可读值班面板 |
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.settings import settings  # noqa: E402
from video_processing.quality_report import (  # noqa: E402,F401
    ACTIVE_STALE_MINUTES,
    MONITOR_BACKOFF_PATH,
    MONITOR_HEALTH_PATH,
    SHANGHAI,
    WECHAT_STATE_PATH,
    WINDOW_HOURS,
    collect,
    format_report,
)

OUTPUT_DIR = PROJECT_ROOT / "output"
HISTORY_PATH = OUTPUT_DIR / "periodic_qa_report_history.log"


def push_telegram(report: str) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    chat = (settings.active_telegram_chat_id or (settings.telegram_admin_ids or "").split(",")[0]).strip()
    if not token or not chat:
        print("Telegram 未配置：缺少 bot token 或 chat id", file=sys.stderr)
        return False
    try:
        payload = urllib.parse.urlencode({"chat_id": chat, "text": report, "parse_mode": "HTML"}).encode()
        request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload)
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        return bool(result.get("ok"))
    except Exception as exc:
        print(f"Telegram 推送失败：{type(exc).__name__}", file=sys.stderr)
        return False


def _append_history(report: str, now: dt.datetime) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plain = report.replace("<b>", "").replace("</b>", "")
    HISTORY_PATH.open("a", encoding="utf-8").write(f"[{now.isoformat()}]\n{plain}\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="三小时视频管线只读质检报告")
    parser.add_argument("--send", action="store_true", help="推送到已配置的 Telegram 会话")
    args = parser.parse_args()
    now = dt.datetime.now(SHANGHAI)
    report = collect(now=now)
    _append_history(report, now)
    print(report)
    if args.send and not push_telegram(report):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

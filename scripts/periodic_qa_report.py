"""每三小时只读质检报告，默认本地留档；人工可显式推送 Telegram。

报告只汇总数据库、监控快照和会话状态文件，绝不触发下载、重试、登录或发布。
本地 processed_videos 的 PUBLISHED 仅代表本地流程记录；快手/抖音的审核中和不确定
状态始终保留为待人工在作品管理中确认，不能据此推断平台侧已发布。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-07-28 | Codex | 初版：三小时只读质检、阻塞归因、遗留项和 Telegram 投递 |
| 1.1.0 | 2026-07-28 | Codex | 区分平台人工核验遗留与普通待投递队列，并提炼失败原因 |
| 1.2.0 | 2026-07-28 | Codex | 报告渲染迁入 video_processing.quality_report，并改为三秒可读值班面板 |
| 1.3.0 | 2026-08-24 | Codex | 手工 Telegram 发送迁入统一回执账本，自动任务仅保留本地报告。 |
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.telegram_delivery import send_text  # noqa: E402
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
    result = send_text(event_type="periodic_qa.manual_report", priority="P2", text=report, timeout_seconds=20)
    if result.state != "ACCEPTED":
        print(f"Telegram 推送未获 API 接受：{result.error_kind or result.state}", file=sys.stderr)
        return False
    return True


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

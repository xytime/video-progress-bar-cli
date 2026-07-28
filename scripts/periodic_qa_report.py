"""每三小时只读质检报告，输出并可推送 Telegram。

报告只汇总数据库、监控快照和会话状态文件，绝不触发下载、重试、登录或发布。
本地 processed_videos 的 PUBLISHED 仅代表本地流程记录；快手/抖音的审核中和不确定
状态始终保留为待人工在作品管理中确认，不能据此推断平台侧已发布。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-07-28 | Codex | 初版：三小时只读质检、阻塞归因、遗留项和 Telegram 投递 |
| 1.1.0 | 2026-07-28 | Codex | 区分平台人工核验遗留与普通待投递队列，并提炼失败原因 |
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.settings import settings  # noqa: E402
from video_processing.db.database import PipelineDB  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
WINDOW_HOURS = 3
ACTIVE_STALE_MINUTES = 90
OUTPUT_DIR = PROJECT_ROOT / "output"
MONITOR_HEALTH_PATH = OUTPUT_DIR / "monitor_health.json"
MONITOR_BACKOFF_PATH = OUTPUT_DIR / "monitor_access_backoff.json"
WECHAT_STATE_PATH = OUTPUT_DIR / "wechat_state.json"
HISTORY_PATH = OUTPUT_DIR / "periodic_qa_report_history.log"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _format_time(value: str | None) -> str:
    if not value:
        return "未知"
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(SHANGHAI).strftime("%m-%d %H:%M")
    except ValueError:
        return value


def _monitor_summary(now: dt.datetime, monitor_path: Path, backoff_path: Path) -> dict[str, Any]:
    report = _read_json(monitor_path)
    backoffs = _read_json(backoff_path) or {}
    if not report:
        return {"state": "缺失", "backoffs": len(backoffs), "detail": "没有 monitor_health.json"}

    generated_at = str(report.get("generated_at") or "")
    try:
        generated = dt.datetime.fromisoformat(generated_at)
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=SHANGHAI)
        age_minutes = max(0, int((now - generated.astimezone(SHANGHAI)).total_seconds() // 60))
    except ValueError:
        age_minutes = None
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    unhealthy = sum(int(summary.get(key) or 0) for key in ("limited", "timeout", "error", "degraded"))
    state = "健康" if unhealthy == 0 and (age_minutes is None or age_minutes <= 90) else "需关注"
    return {
        "state": state,
        "generated_at": generated_at,
        "age_minutes": age_minutes,
        "approved": int(report.get("approved_count") or 0),
        "polled": int(report.get("polled_count") or 0),
        "summary": summary,
        "backoffs": len(backoffs),
    }


def _session_summary(state_path: Path) -> str:
    if not state_path.is_file():
        return "会话状态文件缺失"
    modified = dt.datetime.fromtimestamp(state_path.stat().st_mtime, tz=SHANGHAI)
    return f"状态文件存在，最近写入 {_format_time(modified.isoformat())}"


def _platform_items(platform_states: list[dict[str, Any]], states: set[str]) -> list[str]:
    lines = []
    labels = {"kuaishou": "快手", "douyin": "抖音"}
    for item in platform_states:
        state = str(item.get("state") or "")
        if state in states:
            platform = labels.get(str(item.get("platform") or ""), str(item.get("platform") or "未知"))
            lines.append(f"{platform} {state} {int(item.get('count') or 0)}")
    return lines


def _short_reason(value: Any) -> str:
    ignored_prefixes = ("% Total", "Dload", "Current", "Time", "  %")
    lines = [line.strip() for line in str(value or "").splitlines()]
    useful = [
        line for line in lines
        if line
        and not line.startswith(ignored_prefixes)
        and not (line[:1].isdigit() and line.count(" ") >= 8 and "k" in line)
        and " --:--:-- " not in line
    ]
    return (useful[-1] if useful else "未记录原因")[:160]


def _blocker(snapshot: dict[str, Any], monitor: dict[str, Any], manual_review_items: list[str]) -> str:
    statuses = snapshot["status_counts"]
    if snapshot["stale_active"]:
        row = snapshot["stale_active"][0]
        return f"在途任务超过 {ACTIVE_STALE_MINUTES} 分钟未更新：{row['youtube_id']} ({row['status']})；仅人工核对，勿自动重试。"
    if monitor["state"] != "健康":
        return f"频道监控{monitor['state']}：{monitor.get('detail') or '检查 monitor_health.json 的异常频道和时间戳。'}"
    if statuses.get("LOGIN_REQUIRED", 0):
        return f"微信登录阻塞：{statuses['LOGIN_REQUIRED']} 条任务等待会话恢复。"
    if manual_review_items:
        return "平台账本存在待确认项：先在相应作品管理页核验，勿重复提交。"
    if snapshot["eligible_queue"] == 0 and not snapshot["active"]:
        return "可自动发布队列为空：检查频道监控、评分和候选供给。"
    if snapshot["recent_failures"]:
        return "近三小时有新失败：查看下方首条失败原因后再决定是否干预。"
    return "未发现阻塞；管线按当前队列运行。"


def format_report(
    snapshot: dict[str, Any],
    monitor: dict[str, Any],
    session: str,
    now: dt.datetime,
) -> str:
    statuses = snapshot["status_counts"]
    active_lines = [
        f"{html.escape(str(row['status']))} {html.escape(str(row['youtube_id']))} ({_format_time(row.get('updated_at'))})"
        for row in snapshot["active"]
    ]
    failure_lines = []
    for row in snapshot["recent_failures"][:3]:
        reason = _short_reason(row.get("error_msg"))
        failure_lines.append(f"{row['youtube_id']} {row['status']}: {reason}")
    manual_review_items = _platform_items(
        snapshot["platform_states"], {"UNDER_REVIEW", "UNCERTAIN", "BANNED", "RETRYABLE_FAILED"}
    )
    queued_platform_items = _platform_items(snapshot["platform_states"], {"QUEUED", "UPLOADING"})
    summary = monitor.get("summary") or {}
    monitor_line = (
        f"{monitor['state']} | 已轮询 {monitor.get('polled', 0)}/{monitor.get('approved', 0)} | "
        f"ok {summary.get('ok', 0)} / 空 {summary.get('empty', 0)} / 降级 {summary.get('degraded', 0)} / "
        f"限流 {summary.get('limited', 0)} / 超时 {summary.get('timeout', 0)} / 错误 {summary.get('error', 0)} | "
        f"冷却 {monitor.get('backoffs', 0)}"
    )
    local_published_note = (
        f"本地 PUBLISHED {snapshot['local_published']}（近 {snapshot['hours']}h；不等同平台侧可见确认）"
    )
    outstanding = manual_review_items or ["无平台账本待人工确认项"]
    return "\n".join(
        [
            f"<b>三小时管线质检 {now.strftime('%Y-%m-%d %H:%M')} CST</b>",
            "━━ 当前状态 ━━",
            f"{local_published_note} | 可发队列(>=75) {snapshot['eligible_queue']} | "
            f"在途 {snapshot.get('active_count', len(snapshot['active']))} | 现存失败 {statuses.get('FAILED', 0)} | "
            f"待补元数据 {statuses.get('METADATA_PENDING', 0)}",
            "━━ 频道供给 ━━",
            monitor_line,
            "━━ 在途 ━━",
            *([html.escape(item) for item in active_lines] or ["无"]),
            "━━ 阻塞判定 ━━",
            html.escape(_blocker(snapshot, monitor, manual_review_items)),
            "━━ 遗留项 ━━",
            *([html.escape(item) for item in outstanding]),
            *([f"待投递队列: {html.escape(item)}" for item in queued_platform_items] or ["待投递平台队列: 无"]),
            *([f"近3h失败: {html.escape(item)}" for item in failure_lines] or ["近3h无新失败"]),
            "━━ 会话 ━━",
            html.escape(session),
        ]
    )


def collect(
    db: PipelineDB | None = None,
    *,
    now: dt.datetime | None = None,
    monitor_path: Path = MONITOR_HEALTH_PATH,
    backoff_path: Path = MONITOR_BACKOFF_PATH,
    state_path: Path = WECHAT_STATE_PATH,
) -> str:
    current = now or dt.datetime.now(SHANGHAI)
    snapshot = (db or PipelineDB()).get_quality_report_snapshot(
        hours=WINDOW_HOURS,
        active_stale_minutes=ACTIVE_STALE_MINUTES,
    )
    return format_report(snapshot, _monitor_summary(current, monitor_path, backoff_path), _session_summary(state_path), current)


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

"""src/video_processing/quality_report.py — 视频管线只读质检报告。

从数据库、频道监控快照和会话状态文件汇总当前健康信号，只负责读取和渲染，
不触发下载、重试、登录或发布。processed_videos.PUBLISHED 仅代表本地流程记录；
平台审核中和不确定状态必须继续保留为待人工核验，不能推断为平台侧可见发布。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-07-28 | Codex | 抽出三小时质检只读快照和三秒可读 Telegram HTML 渲染 |
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from video_processing.db.database import PipelineDB

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHANGHAI = ZoneInfo("Asia/Shanghai")
WINDOW_HOURS = 3
ACTIVE_STALE_MINUTES = 90
OUTPUT_DIR = PROJECT_ROOT / "output"
MONITOR_HEALTH_PATH = OUTPUT_DIR / "monitor_health.json"
MONITOR_BACKOFF_PATH = OUTPUT_DIR / "monitor_access_backoff.json"
WECHAT_STATE_PATH = OUTPUT_DIR / "wechat_state.json"


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
        "unhealthy": unhealthy,
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


def _platform_total(platform_states: list[dict[str, Any]], states: set[str]) -> int:
    total = 0
    for item in platform_states:
        if str(item.get("state") or "") in states:
            total += int(item.get("count") or 0)
    return total


def _short_reason(value: Any) -> str:
    ignored_prefixes = ("% Total", "Dload", "Current", "Time", "  %")
    lines = [line.strip() for line in str(value or "").splitlines()]
    useful = []
    for line in lines:
        if not line or line.startswith(ignored_prefixes) or " --:--:-- " in line:
            continue
        if re.fullmatch(r"[\d\s.%:kKmMgGtTpP/iIbsBS-]+", line):
            continue
        useful.append(line)
    return (useful[-1] if useful else "未记录原因")[:120]


def _blocker(snapshot: dict[str, Any], monitor: dict[str, Any], manual_review_items: list[str]) -> str:
    statuses = snapshot["status_counts"]
    if snapshot["stale_active"]:
        row = snapshot["stale_active"][0]
        return f"在途任务超过 {ACTIVE_STALE_MINUTES} 分钟未更新：{row['youtube_id']} ({row['status']})；先人工核对。"
    if monitor["state"] != "健康":
        return f"频道监控{monitor['state']}：{monitor.get('detail') or '检查 monitor_health.json 的异常频道和时间戳。'}"
    if statuses.get("LOGIN_REQUIRED", 0):
        return f"微信登录阻塞：{statuses['LOGIN_REQUIRED']} 条任务等待会话恢复。"
    if snapshot["eligible_queue"] == 0 and not snapshot["active"]:
        return "可自动发布队列为空：检查频道监控、评分和候选供给。"
    if snapshot["recent_failures"]:
        return "近三小时有新失败：先看首条失败原因，再决定是否重试。"
    if manual_review_items:
        return "平台账本有待确认项；管线可继续，但勿重复提交。"
    return "未发现阻塞；管线按当前队列运行。"


def _verdict(snapshot: dict[str, Any], monitor: dict[str, Any], manual_total: int) -> tuple[str, str]:
    statuses = snapshot["status_counts"]
    if snapshot["stale_active"]:
        return "🔴", "异常：在途任务疑似卡住"
    if monitor["state"] != "健康":
        return "🔴", "异常：频道供给监控需关注"
    if statuses.get("LOGIN_REQUIRED", 0):
        return "🔴", "异常：微信登录阻塞"
    if snapshot["eligible_queue"] == 0 and not snapshot["active"]:
        return "🟠", "卡点：自动发布队列为空"
    if snapshot["recent_failures"]:
        return "🟠", f"异常：近{snapshot['hours']}h 有新失败"
    if manual_total:
        return "🟡", f"待核验：平台账本 {manual_total} 项"
    if snapshot["active"]:
        return "🟢", "正常：管线正在运行"
    if snapshot["eligible_queue"]:
        return "🟢", "正常：有可发队列"
    return "🟢", "正常：空闲"


def _join_or_none(items: list[str], *, limit: int = 3) -> str:
    if not items:
        return "无"
    shown = items[:limit]
    suffix = f" 等 {len(items)} 项" if len(items) > limit else ""
    return "；".join(shown) + suffix


def format_report(
    snapshot: dict[str, Any],
    monitor: dict[str, Any],
    session: str,
    now: dt.datetime,
) -> str:
    statuses = snapshot["status_counts"]
    manual_states = {"UNDER_REVIEW", "UNCERTAIN", "BANNED", "RETRYABLE_FAILED"}
    queued_states = {"QUEUED", "UPLOADING"}
    manual_review_items = _platform_items(snapshot["platform_states"], manual_states)
    queued_platform_items = _platform_items(snapshot["platform_states"], queued_states)
    manual_total = _platform_total(snapshot["platform_states"], manual_states)
    queued_total = _platform_total(snapshot["platform_states"], queued_states)
    icon, headline = _verdict(snapshot, monitor, manual_total)
    blocker = _blocker(snapshot, monitor, manual_review_items)

    summary = monitor.get("summary") or {}
    monitor_bad = sum(int(summary.get(key) or 0) for key in ("degraded", "limited", "timeout", "error"))
    active_lines = [
        f"{row['status']} {row['youtube_id']} {_format_time(row.get('updated_at'))}"
        for row in snapshot["active"][:3]
    ]
    failure_lines = [
        f"{row['youtube_id']}: {_short_reason(row.get('error_msg'))}"
        for row in snapshot["recent_failures"][:3]
    ]

    key_line = (
        f"队列 {snapshot['eligible_queue']} | 在途 {snapshot.get('active_count', len(snapshot['active']))} | "
        f"新失败 {len(snapshot['recent_failures'])} | 登录阻塞 {statuses.get('LOGIN_REQUIRED', 0)} | "
        f"监控异常 {monitor_bad} | 遗留 {manual_total}"
    )
    publish_line = (
        f"本地 PUBLISHED {snapshot['local_published']}（近 {snapshot['hours']}h；不等同平台侧可见确认）"
    )
    monitor_line = (
        f"{monitor['state']} {monitor.get('polled', 0)}/{monitor.get('approved', 0)} | "
        f"ok {summary.get('ok', 0)} 空 {summary.get('empty', 0)} 降级 {summary.get('degraded', 0)} "
        f"限流 {summary.get('limited', 0)} 超时 {summary.get('timeout', 0)} 错误 {summary.get('error', 0)} | "
        f"冷却 {monitor.get('backoffs', 0)}"
    )

    return "\n".join(
        [
            f"<b>{icon} {html.escape(headline)}</b> <code>{now.strftime('%m-%d %H:%M')} CST</code>",
            f"<b>卡点</b>：{html.escape(blocker)}",
            f"<b>信号</b>：<code>{html.escape(key_line)}</code>",
            "",
            f"<b>供给</b>：{html.escape(monitor_line)}",
            f"<b>发布</b>：{html.escape(publish_line)}",
            f"<b>在途</b>：{html.escape(_join_or_none(active_lines))}",
            f"<b>新失败</b>：{html.escape(_join_or_none(failure_lines))}",
            f"<b>遗留</b>：{html.escape(_join_or_none(manual_review_items, limit=4))}",
            f"<b>待投递</b>：{html.escape(_join_or_none(queued_platform_items))}（合计 {queued_total}）",
            f"<b>会话</b>：{html.escape(session)}",
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

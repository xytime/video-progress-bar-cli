"""src/video_processing/quality_report.py — 视频管线只读质检报告。

从数据库、频道监控快照和会话状态文件汇总当前健康信号，只负责读取和渲染，
不触发下载、重试、登录或发布。processed_videos.PUBLISHED 仅代表本地流程记录；
平台审核中和不确定状态必须继续保留为待人工核验，不能推断为平台侧可见发布。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-07-28 | Codex | 抽出三小时质检只读快照和三秒可读 Telegram HTML 渲染 |
| 1.1.0 | 2026-07-28 | Codex | 增加总览行：最近发布间隔与各平台成功/待核验/失败态势 |
| 1.2.0 | 2026-08-30 | Codex | 增加抖音上游门禁 shadow 计数和样本，区分候选饥饿与上传器故障 |
| 1.3.0 | 2026-08-30 | Codex | 抖音 shadow 展示显式门禁开关，关闭时不再把候选误报为被阻塞 |
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import settings
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
    parsed = _parse_time(value)
    if parsed is not None:
        return parsed.astimezone(SHANGHAI).strftime("%m-%d %H:%M")
    return value or "未知"


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError:
        return None


def _age_text(value: str | None, now: dt.datetime) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "未知"
    seconds = max(0, int((now - parsed.astimezone(SHANGHAI)).total_seconds()))
    minutes = seconds // 60
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes}分钟"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}小时{minutes % 60}分钟"
    days = hours // 24
    return f"{days}天{hours % 24}小时"


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
    douyin_shadow = snapshot.get("douyin_upstream_shadow") or {}
    shadow_count = int(douyin_shadow.get("count") or 0)
    shadow_eligible = int(douyin_shadow.get("independent_eligible_count") or 0)
    shadow_policy_active = bool(douyin_shadow.get("policy_active", True))
    if shadow_count and shadow_policy_active:
        return f"抖音有 {shadow_count} 条候选被视频号公开确认门禁阻塞；当前仅 shadow 观测，不会自动入队。"
    if shadow_eligible and not shadow_policy_active:
        return f"抖音公开确认门禁已关闭；{shadow_eligible} 条当前窗口无账本候选可在下一轮独立入队。"
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


def _platform_overview(snapshot: dict[str, Any], now: dt.datetime) -> str:
    labels = {"kuaishou": "快手", "douyin": "抖音"}
    rows = {str(row.get("platform") or ""): row for row in snapshot.get("platform_overview", [])}
    parts = ["微信 本地有产出" if snapshot.get("last_local_published") else "微信 尚无本地成功"]

    for platform in ("kuaishou", "douyin"):
        row = rows.get(platform)
        label = labels[platform]
        if not row:
            parts.append(f"{label} 无账本")
            continue
        published_count = int(row.get("published_count") or 0)
        review_count = int(row.get("review_count") or 0)
        failed_count = int(row.get("failed_count") or 0)
        queued_count = int(row.get("queued_count") or 0)
        if published_count:
            parts.append(
                f"{label} 最近确认已发布 {_format_time(row.get('last_published_at'))}"
                f"（{_age_text(row.get('last_published_at'), now)}前）"
            )
        elif failed_count and not review_count and not queued_count:
            parts.append(f"{label} 疑似失败阻塞 {failed_count}，最新 {row.get('latest_state') or 'UNKNOWN'}")
        elif review_count:
            suffix = f"/待投递 {queued_count}" if queued_count else ""
            parts.append(f"{label} 无平台成功证明，待核验 {review_count}{suffix}")
        elif queued_count:
            parts.append(f"{label} 暂无平台成功证明，待投递 {queued_count}")
        else:
            parts.append(f"{label} 最新 {row.get('latest_state') or 'UNKNOWN'}")
    return " | ".join(parts)


def _local_publish_overview(snapshot: dict[str, Any], now: dt.datetime) -> str:
    latest = snapshot.get("last_local_published")
    if not latest:
        return "最近本地发布：无记录"
    return (
        f"最近本地发布 {_format_time(latest.get('updated_at'))}"
        f"（距今 {_age_text(latest.get('updated_at'), now)}；非平台可见证明）"
    )


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
    douyin_shadow = snapshot.get("douyin_upstream_shadow") or {}
    shadow_count = int(douyin_shadow.get("count") or 0)
    shadow_eligible = int(douyin_shadow.get("independent_eligible_count") or 0)
    shadow_policy_active = bool(douyin_shadow.get("policy_active", True))
    shadow_samples = [
        f"{row.get('youtube_id')}({row.get('wechat_state') or row.get('local_state') or 'UNKNOWN'})"
        for row in (douyin_shadow.get("items") or [])
    ]
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
    douyin_signal = (
        f"抖音门禁 {shadow_count}"
        if shadow_policy_active
        else f"抖音可独立 {shadow_eligible}"
    )

    key_line = (
        f"队列 {snapshot['eligible_queue']} | 在途 {snapshot.get('active_count', len(snapshot['active']))} | "
        f"新失败 {len(snapshot['recent_failures'])} | 登录阻塞 {statuses.get('LOGIN_REQUIRED', 0)} | "
        f"监控异常 {monitor_bad} | 遗留 {manual_total} | {douyin_signal}"
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
            f"<b>总览</b>：{html.escape(_local_publish_overview(snapshot, now))}",
            f"<b>平台</b>：{html.escape(_platform_overview(snapshot, now))}",
            f"<b>卡点</b>：{html.escape(blocker)}",
            f"<b>信号</b>：<code>{html.escape(key_line)}</code>",
            "",
            f"<b>供给</b>：{html.escape(monitor_line)}",
            f"<b>发布</b>：{html.escape(publish_line)}",
            f"<b>在途</b>：{html.escape(_join_or_none(active_lines))}",
            f"<b>新失败</b>：{html.escape(_join_or_none(failure_lines))}",
            f"<b>遗留</b>：{html.escape(_join_or_none(manual_review_items, limit=4))}",
            f"<b>待投递</b>：{html.escape(_join_or_none(queued_platform_items))}（合计 {queued_total}）",
            (
                f"<b>抖音 shadow</b>：{html.escape(_join_or_none(shadow_samples))}"
                + (
                    f"（门禁阻塞 {shadow_count}；未入队）"
                    if shadow_policy_active
                    else (
                        f"（门禁已关闭；当前窗口可独立入队 {shadow_eligible}；"
                        f"其余 shadow 不在本轮资格 {max(0, shadow_count - shadow_eligible)}）"
                    )
                )
            ),
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
        douyin_new_lookback_hours=settings.douyin_new_sync_lookback_hours,
    )
    shadow = snapshot.get("douyin_upstream_shadow")
    if isinstance(shadow, dict):
        shadow["policy_active"] = settings.douyin_require_wechat_public_confirmation
    return format_report(snapshot, _monitor_summary(current, monitor_path, backoff_path), _session_summary(state_path), current)

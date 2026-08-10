"""Telegram 今日运营简报的只读渲染器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-10 | Codex | 将自然语言今日简报改为本地账本确定性生成，不依赖外部 AI 服务 |
"""
from __future__ import annotations

import html
import re
import datetime
from typing import Any

from .db import PipelineDB


def _text(value: Any, *, limit: int = 120) -> str:
    """压平用户/平台文本后转义，避免 Telegram HTML 被标题内容破坏。"""
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(normalized) > limit:
        normalized = f"{normalized[:limit - 1]}…"
    return html.escape(normalized or "—")


def _source_link(youtube_id: str) -> str:
    safe_id = html.escape(youtube_id)
    return f'<a href="https://youtu.be/{safe_id}">YouTube</a>'


def _beijing_time(value: Any) -> str:
    """数据库时间按 UTC 存储；Telegram 向用户统一展示北京时间。"""
    raw = str(value or "").strip()
    if not raw:
        return "—"
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def _platform_rows(label: str, rows: list[dict[str, Any]], *, local_only: bool) -> list[str]:
    if not rows:
        return [f"<b>{label}</b>：无"]

    lines = [f"<b>{label}</b>（{len(rows)} 条）"]
    for index, row in enumerate(rows, start=1):
        title = _text(row.get("zh_title") or row.get("title"))
        youtube_id = str(row.get("youtube_id") or "")
        time_key = "updated_at" if local_only else "published_at"
        published_at = _text(_beijing_time(row.get(time_key)), limit=32)
        if local_only:
            post_ref = "创作者页链接：未核验"
        elif row.get("external_url"):
            post_ref = f'<a href="{html.escape(str(row["external_url"]), quote=True)}">平台作品链接</a>'
        elif row.get("external_post_id"):
            post_ref = f"平台作品 ID：<code>{_text(row['external_post_id'], limit=80)}</code>"
        else:
            post_ref = "平台链接/作品 ID：账本未记录"
        lines.append(
            f"{index}. {title}\n"
            f"   YouTube ID：<code>{html.escape(youtube_id)}</code> | {_source_link(youtube_id)}\n"
            f"   时间：{published_at} | {post_ref}"
        )
    return lines


def collect_daily_brief(db: PipelineDB | None = None) -> str:
    """生成可直接发送 Telegram 的今日只读简报。"""
    snapshot = (db or PipelineDB()).get_daily_operations_snapshot()
    wechat_rows = snapshot["wechat_local_completed"]
    kuaishou_rows = snapshot["kuaishou_confirmed_published"]
    douyin_rows = snapshot["douyin_confirmed_published"]
    lines = [
        f"<b>📋 今日运营简报 {snapshot['date']}（北京时间）</b>",
        "<pre>指标                 数量\n"
        f"今日入库采编           {snapshot['collected_count']}\n"
        f"今日失败               {snapshot['failed_count']}\n"
        f"敏感词拦截(P0/P1/P2)   {snapshot['sensitive_blocked_count']}\n"
        f"视频号本地完成         {len(wechat_rows)}\n"
        f"快手已确认发布         {len(kuaishou_rows)}\n"
        f"抖音已确认发布         {len(douyin_rows)}</pre>",
        "<i>口径：视频号“本地完成”不是创作者后台可见证明；快手/抖音仅统计独立发布账本已确认的 PUBLISHED。频道策略(CP)拦截不计入敏感词拦截。</i>",
        "\n<b>视频明细</b>",
    ]
    lines.extend(_platform_rows("视频号（本地完成）", wechat_rows, local_only=True))
    lines.extend(_platform_rows("快手（已确认发布）", kuaishou_rows, local_only=False))
    lines.extend(_platform_rows("抖音（已确认发布）", douyin_rows, local_only=False))
    return "\n".join(lines)

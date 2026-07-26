#!/usr/bin/env python
"""三平台补录预览（只读）。

根据运营规则预览微信/抖音补录候选，不创建发布任务、不修改视频状态：
1. 已发布/已产出视频中属于访谈类或演讲类；
2. 最近 N 天 Wall Street Truthbombs 频道发布的视频。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-23 | Codex | 新增微信/抖音补录候选预览与日批次切分 |
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

PRJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PRJ / "src"))

from video_processing.db.database import PipelineDB  # noqa: E402


def default_since_upload_date(days: int) -> str:
    """按本机日期给出 YYYYMMDD 源视频发布日期下界。"""
    return (dt.date.today() - dt.timedelta(days=max(0, days))).strftime("%Y%m%d")


def candidate_rules(row: Dict[str, Any]) -> List[str]:
    rules = []
    if int(row.get("is_speech_or_interview") or 0):
        rules.append("访谈/演讲")
    if int(row.get("is_recent_wall_street") or 0):
        rules.append("Wall Street Truthbombs 最近窗口")
    return rules or ["未标注规则"]


def split_batches(rows: List[Dict[str, Any]], daily_limit: int) -> List[List[Dict[str, Any]]]:
    limit = max(1, int(daily_limit))
    return [rows[index:index + limit] for index in range(0, len(rows), limit)]


def build_preview(
    db: PipelineDB,
    *,
    since_upload_date: str,
    wechat_daily_limit: int,
    douyin_daily_limit: int,
    limit: int,
) -> Dict[str, Any]:
    platforms = {
        "wechat": {"label": "微信", "daily_limit": wechat_daily_limit},
        "douyin": {"label": "抖音", "daily_limit": douyin_daily_limit},
    }
    result: Dict[str, Any] = {
        "since_upload_date": since_upload_date,
        "platforms": {},
    }
    for platform, meta in platforms.items():
        candidates = db.get_platform_backfill_preview_candidates(
            platform,
            wall_street_since_upload_date=since_upload_date,
            limit=limit,
        )
        batches = split_batches(candidates, int(meta["daily_limit"]))
        result["platforms"][platform] = {
            "label": meta["label"],
            "daily_limit": meta["daily_limit"],
            "candidate_count": len(candidates),
            "estimated_days": len(batches),
            "batches": batches,
        }
    return result


def _format_candidate(row: Dict[str, Any]) -> str:
    rules = " + ".join(candidate_rules(row))
    title = str(row.get("title") or "").strip()
    if len(title) > 64:
        title = title[:61] + "..."
    upload_date = row.get("upload_date") or "未知日期"
    channel = row.get("channel_name") or row.get("channel_id") or "未知频道"
    suffix = f" | 抖音状态={row.get('platform_state')}" if row.get("platform_state") else ""
    return (
        f"- {row['youtube_id']} s{row.get('slice_index', 0)} | {upload_date} | "
        f"{channel} | {rules}{suffix}\n"
        f"  {title}"
    )


def format_text(preview: Dict[str, Any], *, wechat_max_daily_limit: int) -> str:
    lines = [
        "三平台补录预览（只读，不入队、不发布）",
        f"Wall Street Truthbombs 源发布日期下界: {preview['since_upload_date']}",
        "",
    ]
    for platform in ("wechat", "douyin"):
        payload = preview["platforms"][platform]
        label = payload["label"]
        daily_limit = int(payload["daily_limit"])
        extra = ""
        if platform == "wechat":
            extra = f"；前三天建议 {daily_limit}/天，无异常后可升至 {wechat_max_daily_limit}/天"
        lines.append(
            f"{label}: 候选 {payload['candidate_count']} 条 | 当前切批 {daily_limit}/天 | "
            f"预计 {payload['estimated_days']} 天{extra}"
        )
        for day_index, batch in enumerate(payload["batches"][:3], start=1):
            lines.append(f"  Day {day_index}:")
            lines.extend("  " + _format_candidate(row).replace("\n", "\n  ") for row in batch)
        if payload["estimated_days"] > 3:
            lines.append(f"  ... 还有 {payload['estimated_days'] - 3} 个批次未展开")
        lines.append("")
    lines.append("无异常口径: 无重复发布、无 UNCERTAIN 未核实、无登录阻断、无审核拒绝/下架、无连续上传失败。")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读预览微信/抖音补录候选与每日批次")
    parser.add_argument("--db", default=str(PRJ / "output" / "pipeline.db"), help="pipeline.db 路径")
    parser.add_argument("--wall-street-days", type=int, default=10, help="Wall Street Truthbombs 回看天数")
    parser.add_argument("--since-upload-date", help="覆盖源视频发布日期下界，格式 YYYYMMDD")
    parser.add_argument("--wechat-daily-limit", type=int, default=5, help="微信前三天补录日限额")
    parser.add_argument("--wechat-max-daily-limit", type=int, default=8, help="微信稳定后建议日限额")
    parser.add_argument("--douyin-daily-limit", type=int, default=5, help="抖音补录日限额")
    parser.add_argument("--limit", type=int, default=500, help="每个平台最多预览候选数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    since_upload_date = args.since_upload_date or default_since_upload_date(args.wall_street_days)
    db = PipelineDB(args.db)
    preview = build_preview(
        db,
        since_upload_date=since_upload_date,
        wechat_daily_limit=args.wechat_daily_limit,
        douyin_daily_limit=args.douyin_daily_limit,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
    else:
        print(format_text(preview, wechat_max_daily_limit=args.wechat_max_daily_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

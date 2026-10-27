"""将宿主已经核验的字幕质量告警格式化为 Telegram 通知。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 按选中候选和问题摘要生成幂等键，明确继续处理与平台发布的区别。 |
"""
from __future__ import annotations

import html
import re


EVENT_TYPE = "pipeline.subtitle_quality_warning"


def warning_dedupe_key(youtube_id, slice_index, warning):
    """同一任务同候选同问题永久一致，新问题不会被旧任务通知吞掉。"""
    candidate, summary = warning.get("candidate_sha256"), warning.get("summary_sha256")
    if (not isinstance(youtube_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", youtube_id)
            or type(slice_index) is not int or slice_index < 0
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in (candidate, summary))):
        raise ValueError("invalid subtitle warning notification identity")
    return f"{EVENT_TYPE}:{youtube_id}:{slice_index}:{candidate}:{summary}"


def _timestamp(seconds):
    try:
        seconds = max(0, int(float(seconds)))
    except (ValueError, TypeError, OverflowError):
        return "?"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _percentage(value):
    try:
        return f"{float(value):.2%}"
    except (ValueError, TypeError):
        return "未知"


def _issue_types(issues):
    values = sorted({str(item.get("severity") or "?") + " " + str(item.get("code") or "质量疑点")
                     for item in issues if isinstance(item, dict)})
    return html.escape(", ".join(values[:4]) + (f"（共{len(values)}类，详见证据）" if len(values) > 4 else ""))


def format_subtitle_quality_warning(youtube_id, slice_index, warning, *, title=""):
    """只描述字幕告警允许继续，不能声称已发布或全文正确。"""
    warning_dedupe_key(youtube_id, slice_index, warning)
    report = warning["report"]
    prefix = youtube_id + (f"_s{slice_index}" if slice_index else "")
    numbers = report.get("affected_segments") or report.get("affected_segment_numbers") or sorted({
        issue.get("segment_number") for issue in report.get("issues", ())
        if type(issue.get("segment_number")) is int
    })
    lines = ["⚠️ <b>字幕质量告警：带问题继续</b>",
             f"YouTube ID: <code>{html.escape(prefix)}</code>"]
    if title:
        lines.append("标题：" + html.escape(str(title)[:160]))
    repaired = any(isinstance(item, dict) and item.get("executed") is True
                   for item in report.get("repair_history") or ())
    lines.extend([
        "已尝试针对性修复；少量残留问题按已确认规则继续处理。" if repaired
        else "宿主复核后按既有软告警规则继续处理；疑点与处理记录见证据。",
        "后续仍须通过审查与发布门禁；本通知不代表平台已发布。",
        "受影响段：" + html.escape(", ".join(map(str, numbers)) or "见证据"),
        "段数比例：" + _percentage(report.get("segment_ratio", report.get("segment_fraction")))
        + "；字幕覆盖时长比例：" + _percentage(report.get("duration_ratio", report.get("duration_fraction"))),
    ])
    for issue in list(report.get("issues") or ())[:6]:
        if not isinstance(issue, dict):
            continue
        number = issue.get("segment_number", "?")
        start, end = _timestamp(issue.get("start")), _timestamp(issue.get("end"))
        code = html.escape(str(issue.get("code") or "质量疑点")[:100])
        severity = html.escape(str(issue.get("severity") or "?")[:10])
        source = html.escape(str(issue.get("source_signal") or "")[:100])
        translation = html.escape(str(issue.get("translation_signal") or "")[:100])
        lines.append(f"第{number}段 {start}–{end}：[{severity}] {code}" + (f"；{source} → {translation}" if source or translation else ""))
    if report.get("global_warnings"):
        lines.append("全片一致性疑点：" + _issue_types(report["global_warnings"]))
    if report.get("removed_vocab_issues"):
        lines.append("已处理词注：" + _issue_types(report["removed_vocab_issues"]))
    lines.append("处置：保留完整原文、译文和时间轴；"
                 + ("无效词注已移除；" if report.get("removed_vocab_issues") else "")
                 + "检测疑点仍待复核。")
    bad_case = warning.get("bad_case") or {}
    lines.extend([
        "Bad case：<code>" + html.escape(str(bad_case.get("case_id") or "")[:64]) + "</code>",
        "证据：" + html.escape(str(bad_case.get("path") or "")[:500]),
        "候选/问题：<code>" + warning["candidate_sha256"][:12] + "/" + warning["summary_sha256"][:12] + "</code>",
    ])
    return "\n".join(lines)

"""多平台发布事件格式化工具。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0   | 2026-07-27 | Codex  | 新增平台事件数据结构与 HTML 告警格式，供管线与 Telegram 助手 bot 共用 |
"""

from __future__ import annotations

import html
from dataclasses import dataclass


_SEVERITY_LABELS = {
    "info": "INFO",
    "success": "SUCCESS",
    "warning": "WARNING",
    "critical": "CRITICAL",
}

_SEVERITY_ICONS = {
    "info": "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "critical": "🚨",
}


@dataclass(frozen=True)
class PlatformEvent:
    """平台发布链事件：只表达事实与动作建议，不触发任何外部 I/O。"""

    platform: str
    youtube_id: str
    reason: str
    state: str = ""
    source_kind: str = ""
    action: str = ""
    severity: str = "warning"

    @property
    def normalized_severity(self) -> str:
        key = (self.severity or "warning").strip().lower()
        return key if key in _SEVERITY_LABELS else "warning"


def format_platform_event_html(event: PlatformEvent) -> str:
    """渲染 Telegram HTML 告警；调用方负责发送。"""
    severity = event.normalized_severity
    icon = _SEVERITY_ICONS[severity]
    label = _SEVERITY_LABELS[severity]
    lines = [
        f"{icon} <b>{html.escape(event.platform)} Platform Alert</b>",
        f"Severity: <code>{label}</code>",
        f"ID: <code>{html.escape(event.youtube_id)}</code>",
    ]
    if event.state:
        lines.append(f"State: <code>{html.escape(event.state)}</code>")
    if event.source_kind:
        lines.append(f"Source: <code>{html.escape(event.source_kind)}</code>")
    if event.action:
        lines.append(f"Action: {html.escape(event.action)}")
    if event.reason:
        reason = " ".join(event.reason.split())[:500]
        lines.append(f"Reason: {html.escape(reason)}")
    return "\n".join(lines)

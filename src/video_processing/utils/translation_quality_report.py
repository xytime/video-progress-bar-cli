# -*- coding: utf-8 -*-
"""翻译质量审计报告聚合器。

汇总字幕侧 *.translation_quality.json 与文案侧 *_copy_quality.json，
为运营排障、供应商质量对比和后续多模型仲裁提供统一统计。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：聚合字幕/文案质量报告，统计 provider、issue code 与阻断项 |
| 1.1.0   | 2026-07-05 | Codex  | 新增 warning_count/warning_files，让非阻断一致性告警可运营观测 |
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List


@dataclass
class TranslationQualityAggregate:
    """翻译质量审计聚合结果。"""

    files_scanned: int = 0
    event_count: int = 0
    warning_count: int = 0
    blocked_count: int = 0
    provider_counts: Counter = field(default_factory=Counter)
    issue_counts: Counter = field(default_factory=Counter)
    warning_files: List[Dict[str, Any]] = field(default_factory=list)
    blocked_files: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "event_count": self.event_count,
            "warning_count": self.warning_count,
            "blocked_count": self.blocked_count,
            "provider_counts": dict(sorted(self.provider_counts.items())),
            "issue_counts": dict(sorted(self.issue_counts.items())),
            "warning_files": self.warning_files,
            "blocked_files": self.blocked_files,
        }


def collect_quality_report_paths(root: Path) -> List[Path]:
    """收集翻译质量审计报告路径。"""
    root = Path(root)
    if root.is_file():
        return [root]
    if not root.exists():
        return []
    paths = list(root.rglob("*.translation_quality.json"))
    paths.extend(root.rglob("*_copy_quality.json"))
    return sorted({p for p in paths if p.is_file()})


def aggregate_quality_reports(root: Path) -> Dict[str, Any]:
    """聚合目录下所有翻译质量审计报告。"""
    aggregate = TranslationQualityAggregate()
    for path in collect_quality_report_paths(root):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        aggregate.files_scanned += 1
        for event in _iter_events(payload):
            aggregate.event_count += 1
            provider = str(event.get("provider") or "unknown")
            aggregate.provider_counts[provider] += 1

            warning_issues = list(event.get("warning_issues") or [])
            blocking_issues = list(event.get("blocking_issues") or [])
            issues = warning_issues + blocking_issues
            for issue in issues:
                code = str(issue.get("code") or "UNKNOWN")
                aggregate.issue_counts[code] += 1

            if warning_issues:
                aggregate.warning_count += 1
                aggregate.warning_files.append(
                    {
                        "path": str(path),
                        "provider": provider,
                        "issue_codes": [str(issue.get("code") or "UNKNOWN") for issue in warning_issues],
                    }
                )

            if event.get("status") == "blocked" or event.get("action") in {"fallback", "fail"}:
                aggregate.blocked_count += 1
                aggregate.blocked_files.append(
                    {
                        "path": str(path),
                        "provider": provider,
                        "action": event.get("action", ""),
                        "issue_codes": [str(issue.get("code") or "UNKNOWN") for issue in issues],
                    }
                )
    return aggregate.to_dict()


def _iter_events(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """兼容字幕报告(events 列表)与文案报告(单事件 dict)。"""
    events = payload.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                yield event
        return

    if "status" in payload or "action" in payload:
        yield payload

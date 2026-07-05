# -*- coding: utf-8 -*-
"""翻译质量审计报告聚合器。

汇总字幕侧 *.translation_quality.json 与文案侧 *_copy_quality.json，
为运营排障、供应商质量对比和后续多模型仲裁提供统一统计。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：聚合字幕/文案质量报告，统计 provider、issue code 与阻断项 |
| 1.1.0   | 2026-07-05 | Codex  | 新增 warning_count/warning_files，让非阻断一致性告警可运营观测 |
| 1.2.0   | 2026-07-05 | Codex  | 分离 warning/blocking issue 计数，让日报可同时展示最高频告警与阻断 |
| 1.3.0   | 2026-07-06 | Codex  | 新增 provider_issue_counts，定位不同翻译供应商的高频质量问题 |
| 1.4.0   | 2026-07-06 | Codex  | 新增 selected 维度统计，区分尝试候选与最终采用候选质量 |
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
    selected_count: int = 0
    selected_warning_count: int = 0
    warning_count: int = 0
    blocked_count: int = 0
    provider_counts: Counter = field(default_factory=Counter)
    selected_provider_counts: Counter = field(default_factory=Counter)
    issue_counts: Counter = field(default_factory=Counter)
    selected_issue_counts: Counter = field(default_factory=Counter)
    selected_warning_issue_counts: Counter = field(default_factory=Counter)
    warning_issue_counts: Counter = field(default_factory=Counter)
    blocking_issue_counts: Counter = field(default_factory=Counter)
    provider_issue_counts: Dict[str, Counter] = field(default_factory=dict)
    warning_files: List[Dict[str, Any]] = field(default_factory=list)
    blocked_files: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "event_count": self.event_count,
            "selected_count": self.selected_count,
            "selected_warning_count": self.selected_warning_count,
            "warning_count": self.warning_count,
            "blocked_count": self.blocked_count,
            "provider_counts": dict(sorted(self.provider_counts.items())),
            "selected_provider_counts": dict(sorted(self.selected_provider_counts.items())),
            "issue_counts": dict(sorted(self.issue_counts.items())),
            "selected_issue_counts": dict(sorted(self.selected_issue_counts.items())),
            "selected_warning_issue_counts": dict(sorted(self.selected_warning_issue_counts.items())),
            "warning_issue_counts": dict(sorted(self.warning_issue_counts.items())),
            "blocking_issue_counts": dict(sorted(self.blocking_issue_counts.items())),
            "provider_issue_counts": _sorted_nested_counters(self.provider_issue_counts),
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
            selected = event.get("selected") is True
            if selected:
                aggregate.selected_count += 1
                aggregate.selected_provider_counts[provider] += 1
                if warning_issues:
                    aggregate.selected_warning_count += 1
            for issue in issues:
                code = str(issue.get("code") or "UNKNOWN")
                aggregate.issue_counts[code] += 1
                aggregate.provider_issue_counts.setdefault(provider, Counter())[code] += 1
                if selected:
                    aggregate.selected_issue_counts[code] += 1
            for issue in warning_issues:
                code = str(issue.get("code") or "UNKNOWN")
                aggregate.warning_issue_counts[code] += 1
                if selected:
                    aggregate.selected_warning_issue_counts[code] += 1
            for issue in blocking_issues:
                code = str(issue.get("code") or "UNKNOWN")
                aggregate.blocking_issue_counts[code] += 1

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


def _sorted_nested_counters(counters: Dict[str, Counter]) -> Dict[str, Dict[str, int]]:
    """把 provider -> Counter 转成稳定排序的 JSON 结构。"""
    return {
        provider: dict(sorted(counter.items()))
        for provider, counter in sorted(counters.items())
    }

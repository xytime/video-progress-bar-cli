# -*- coding: utf-8 -*-
"""字幕翻译候选质量决策。

本模块把事实保真守门器的结果转换成 provider-neutral 的候选决策：
接受、降级到下一供应商，或阻断流水线。它不直接调用翻译 API，也不写文件，
便于后续接入 LLM judge、回译检查、术语一致性等更多评估器。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：抽象字幕翻译候选质量决策和审计事件 |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .translation_quality_guard import QualityIssue, evaluate_translation_batch


@dataclass(frozen=True)
class SubtitleTranslationQualityDecision:
    """一个字幕翻译候选的质量决策。"""

    provider: str
    accepted: bool
    action: str
    status: str
    warning_issues: List[QualityIssue] = field(default_factory=list)
    blocking_issues: List[QualityIssue] = field(default_factory=list)

    @property
    def should_fallback(self) -> bool:
        return self.action == "fallback"

    @property
    def should_fail(self) -> bool:
        return self.action == "fail"

    def to_audit_event(self, *, final_provider: bool) -> Dict[str, Any]:
        """转换为可落盘的审计事件。"""
        return {
            "provider": self.provider,
            "final_provider": final_provider,
            "status": self.status,
            "action": self.action,
            "warning_issues": [_issue_to_dict(issue) for issue in self.warning_issues],
            "blocking_issues": [_issue_to_dict(issue) for issue in self.blocking_issues],
        }

    def blocking_summary(self, limit: int = 3) -> str:
        """给异常/日志使用的简短阻断摘要。"""
        return "; ".join(
            f"{issue.code}: {issue.message}"
            for issue in self.blocking_issues[:limit]
        )


def evaluate_subtitle_translation_candidate(
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
    *,
    provider: str,
    final_provider: bool,
    context_text: str = "",
) -> SubtitleTranslationQualityDecision:
    """评估一个 provider 候选，返回接受/降级/失败决策。"""
    summary = evaluate_translation_batch(
        source_texts,
        translated_texts,
        context_text=context_text,
    )
    warning_issues = summary.warning_issues
    blocking_issues = summary.blocking_issues

    if blocking_issues:
        if final_provider:
            return SubtitleTranslationQualityDecision(
                provider=provider,
                accepted=False,
                status="blocked",
                action="fail",
                warning_issues=warning_issues,
                blocking_issues=blocking_issues,
            )
        return SubtitleTranslationQualityDecision(
            provider=provider,
            accepted=False,
            status="blocked",
            action="fallback",
            warning_issues=warning_issues,
            blocking_issues=blocking_issues,
        )

    return SubtitleTranslationQualityDecision(
        provider=provider,
        accepted=True,
        status="passed",
        action="accept",
        warning_issues=warning_issues,
        blocking_issues=[],
    )


def _issue_to_dict(issue: QualityIssue) -> Dict[str, str]:
    return {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "source_signal": issue.source_signal,
        "translation_signal": issue.translation_signal,
        "suggested_fix": issue.suggested_fix,
    }

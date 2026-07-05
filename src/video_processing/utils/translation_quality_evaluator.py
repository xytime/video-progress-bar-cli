# -*- coding: utf-8 -*-
"""通用翻译质量评估器。

本模块把事实保真、整片术语一致性、候选决策和审计事件统一到一个
provider-neutral 入口。字幕、标题、短标题、文案都可以复用它，避免各链路
各自拼接 issue 和 report 结构。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：统一事实守门、一致性检查、候选决策和审计事件输出 |
| 1.1.0   | 2026-07-06 | Codex  | 质量上下文加入受保护实体，并传递给整片一致性检查 |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .translation_consistency_guard import evaluate_translation_consistency
from .translation_quality_guard import QualityIssue, evaluate_translation_batch


@dataclass(frozen=True)
class TranslationQualityContext:
    """候选质量评估可复用的上下文。"""

    source_context_text: str = ""
    domain: str = "general"
    facts: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    term_notes: List[str] = field(default_factory=list)
    style_notes: List[str] = field(default_factory=list)

    def to_guard_context_text(self) -> str:
        """渲染为事实守门器可扫描的上下文文本。"""
        parts: List[str] = []
        if self.source_context_text.strip():
            parts.append(self.source_context_text.strip())
        parts.extend(self.facts)
        parts.extend(self.term_notes)
        return "\n".join(part for part in parts if part)

    def to_audit_context(self) -> Dict[str, Any]:
        """转换为审计报告中的上下文摘要。"""
        return {
            "domain": self.domain,
            "facts": list(self.facts),
            "entities": list(self.entities),
            "term_notes": list(self.term_notes),
            "style_notes": list(self.style_notes),
        }


@dataclass(frozen=True)
class TranslationQualityDecision:
    """一个翻译候选的质量决策。"""

    provider: str
    accepted: bool
    action: str
    status: str
    warning_issues: List[QualityIssue] = field(default_factory=list)
    blocking_issues: List[QualityIssue] = field(default_factory=list)
    quality_context: TranslationQualityContext | None = None

    @property
    def should_fallback(self) -> bool:
        return self.action == "fallback"

    @property
    def should_fail(self) -> bool:
        return self.action == "fail"

    @property
    def issues(self) -> List[QualityIssue]:
        """全部 issue，warning 在前、blocking 在后。"""
        return self.warning_issues + self.blocking_issues

    def to_audit_event(self, *, final_provider: bool | None = None) -> Dict[str, Any]:
        """转换为可落盘的审计事件。"""
        event: Dict[str, Any] = {
            "provider": self.provider,
            "status": self.status,
            "action": self.action,
            "warning_issues": [issue_to_dict(issue) for issue in self.warning_issues],
            "blocking_issues": [issue_to_dict(issue) for issue in self.blocking_issues],
        }
        if final_provider is not None:
            event["final_provider"] = final_provider
        if self.quality_context is not None:
            event["quality_context"] = self.quality_context.to_audit_context()
        return event

    def blocking_summary(self, limit: int = 3) -> str:
        """给异常/日志使用的简短阻断摘要。"""
        return "; ".join(
            f"{issue.code}: {issue.message}"
            for issue in self.blocking_issues[:limit]
        )


def evaluate_translation_candidate(
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
    *,
    provider: str,
    final_provider: bool = True,
    context_text: str = "",
    quality_context: TranslationQualityContext | None = None,
) -> TranslationQualityDecision:
    """评估一个翻译候选，返回接受/降级/失败决策。"""
    guard_context_text = (
        quality_context.to_guard_context_text()
        if quality_context is not None
        else context_text
    )
    summary = evaluate_translation_batch(
        source_texts,
        translated_texts,
        context_text=guard_context_text,
    )
    consistency_issues = evaluate_translation_consistency(
        source_texts,
        translated_texts,
        protected_entities=quality_context.entities if quality_context is not None else None,
    )
    warning_issues = summary.warning_issues + consistency_issues
    blocking_issues = summary.blocking_issues

    if blocking_issues:
        return TranslationQualityDecision(
            provider=provider,
            accepted=False,
            status="blocked",
            action="fail" if final_provider else "fallback",
            warning_issues=warning_issues,
            blocking_issues=blocking_issues,
            quality_context=quality_context,
        )

    return TranslationQualityDecision(
        provider=provider,
        accepted=True,
        status="passed",
        action="accept",
        warning_issues=warning_issues,
        blocking_issues=[],
        quality_context=quality_context,
    )


def issue_to_dict(issue: QualityIssue) -> Dict[str, str]:
    """把 QualityIssue 转成报告稳定 JSON 结构。"""
    return {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "source_signal": issue.source_signal,
        "translation_signal": issue.translation_signal,
        "suggested_fix": issue.suggested_fix,
    }

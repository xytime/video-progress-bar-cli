# -*- coding: utf-8 -*-
"""翻译候选仲裁工具。

把多 provider 候选的 warning-aware 选择策略从字幕处理器中抽离出来。
本模块只依赖通用质量决策，不关心字幕段、文案字段或具体翻译供应商。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：抽象 warning-aware 翻译候选仲裁状态机 |
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .translation_quality_evaluator import TranslationQualityDecision


_WARNING_SEVERITY_RANK = {
    "P0": 4,
    "P1": 3,
    "P2": 2,
    "P3": 1,
    "PASS": 0,
}


@dataclass(frozen=True)
class CandidateArbitrationOutcome:
    """一次候选仲裁的动作。"""

    action: str
    candidate: Any | None = None
    event: Dict[str, Any] | None = None

    @property
    def should_use_candidate(self) -> bool:
        return self.action == "use_candidate"

    @property
    def should_fail(self) -> bool:
        return self.action == "fail"


class TranslationCandidateArbiter:
    """在多个翻译 provider 候选之间选择质量更好的结果。"""

    def __init__(self) -> None:
        self._best_warning_candidate: Any | None = None
        self._best_warning_event: Dict[str, Any] | None = None

    def consider(
        self,
        *,
        candidate: Any,
        decision: TranslationQualityDecision,
        event: Dict[str, Any],
        final_provider: bool,
    ) -> CandidateArbitrationOutcome:
        """纳入一个候选的质量决策，返回下一步动作。"""
        if decision.should_fallback:
            return CandidateArbitrationOutcome("keep_looking")

        if decision.should_fail:
            if self._best_warning_candidate is not None:
                return self._select_best_warning()
            return CandidateArbitrationOutcome("fail")

        if not decision.warning_issues:
            event["selected"] = True
            return CandidateArbitrationOutcome("use_candidate", candidate=candidate, event=event)

        if self._should_replace_best_warning(decision):
            self._best_warning_candidate = candidate
            self._best_warning_event = event

        if final_provider and self._best_warning_candidate is not None:
            return self._select_best_warning()

        return CandidateArbitrationOutcome("keep_looking")

    def finish(self) -> CandidateArbitrationOutcome:
        """provider 列表结束后，选择最佳 warning 候选或宣告耗尽。"""
        if self._best_warning_candidate is not None:
            return self._select_best_warning()
        return CandidateArbitrationOutcome("exhausted")

    def _should_replace_best_warning(self, decision: TranslationQualityDecision) -> bool:
        if self._best_warning_event is None:
            return True
        return _warning_rank(decision) < _warning_rank_from_event(self._best_warning_event)

    def _select_best_warning(self) -> CandidateArbitrationOutcome:
        self._best_warning_event["selected"] = True
        return CandidateArbitrationOutcome(
            "use_candidate",
            candidate=self._best_warning_candidate,
            event=self._best_warning_event,
        )


def _warning_rank(decision: TranslationQualityDecision) -> tuple[int, int]:
    """候选 warning 排序键：优先更低严重度，其次更少 warning。"""
    max_rank = max(
        (_WARNING_SEVERITY_RANK.get(issue.severity, 0) for issue in decision.warning_issues),
        default=0,
    )
    return (max_rank, len(decision.warning_issues))


def _warning_rank_from_event(event: Dict[str, Any]) -> tuple[int, int]:
    """从审计事件计算 warning 排序键。"""
    warning_issues = list(event.get("warning_issues") or [])
    max_rank = max(
        (_WARNING_SEVERITY_RANK.get(str(issue.get("severity") or ""), 0) for issue in warning_issues),
        default=0,
    )
    return (max_rank, len(warning_issues))

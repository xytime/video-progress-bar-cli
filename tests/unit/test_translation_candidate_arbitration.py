# -*- coding: utf-8 -*-
"""Unit tests for translation_candidate_arbitration.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：覆盖 warning-aware 候选仲裁状态机 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_candidate_arbitration import (  # noqa: E402
    TranslationCandidateArbiter,
)
from video_processing.utils.translation_quality_guard import QualityIssue  # noqa: E402
from video_processing.utils.translation_quality_evaluator import (  # noqa: E402
    TranslationQualityDecision,
)


def _decision(
    *,
    action: str = "accept",
    status: str = "passed",
    warning_codes: list[str] | None = None,
    warning_severity: str = "P1",
) -> TranslationQualityDecision:
    return TranslationQualityDecision(
        provider="UnitTest",
        accepted=action == "accept",
        action=action,
        status=status,
        warning_issues=[
            QualityIssue(
                severity=warning_severity,
                code=code,
                message="warning",
                source_signal="source",
                translation_signal="translation",
            )
            for code in (warning_codes or [])
        ],
    )


def _event(decision: TranslationQualityDecision) -> dict:
    return decision.to_audit_event()


def test_arbiter_uses_clean_candidate_immediately():
    arbiter = TranslationCandidateArbiter()
    decision = _decision()
    event = _event(decision)

    outcome = arbiter.consider(
        candidate="clean",
        decision=decision,
        event=event,
        final_provider=False,
    )

    assert outcome.should_use_candidate
    assert outcome.candidate == "clean"
    assert event["selected"] is True


def test_arbiter_keeps_warning_candidate_until_clean_candidate_arrives():
    arbiter = TranslationCandidateArbiter()
    warning_decision = _decision(warning_codes=["TERM_DRIFT"])
    warning_event = _event(warning_decision)

    warning_outcome = arbiter.consider(
        candidate="warning",
        decision=warning_decision,
        event=warning_event,
        final_provider=False,
    )
    clean_decision = _decision()
    clean_event = _event(clean_decision)
    clean_outcome = arbiter.consider(
        candidate="clean",
        decision=clean_decision,
        event=clean_event,
        final_provider=False,
    )

    assert warning_outcome.action == "keep_looking"
    assert clean_outcome.should_use_candidate
    assert clean_outcome.candidate == "clean"
    assert warning_event.get("selected") is None
    assert clean_event["selected"] is True


def test_arbiter_uses_best_warning_candidate_when_no_clean_candidate():
    arbiter = TranslationCandidateArbiter()
    p1_decision = _decision(warning_codes=["P1_WARNING"], warning_severity="P1")
    p1_event = _event(p1_decision)
    p2_decision = _decision(warning_codes=["P2_WARNING"], warning_severity="P2")
    p2_event = _event(p2_decision)

    arbiter.consider(candidate="p1", decision=p1_decision, event=p1_event, final_provider=False)
    outcome = arbiter.consider(candidate="p2", decision=p2_decision, event=p2_event, final_provider=True)

    assert outcome.should_use_candidate
    assert outcome.candidate == "p2"
    assert p2_event["selected"] is True
    assert p1_event.get("selected") is None


def test_arbiter_fails_when_final_candidate_blocked_and_no_warning_candidate():
    arbiter = TranslationCandidateArbiter()
    decision = _decision(action="fail", status="blocked")

    outcome = arbiter.consider(
        candidate="blocked",
        decision=decision,
        event=_event(decision),
        final_provider=True,
    )

    assert outcome.should_fail


def test_arbiter_finishes_with_exhausted_when_no_candidate_is_available():
    outcome = TranslationCandidateArbiter().finish()

    assert outcome.action == "exhausted"

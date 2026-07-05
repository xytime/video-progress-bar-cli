# -*- coding: utf-8 -*-
"""Unit tests for subtitle_translation_quality.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖字幕翻译候选质量决策与审计事件 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.subtitle_translation_quality import (  # noqa: E402
    evaluate_subtitle_translation_candidate,
)


def test_quality_decision_accepts_candidate_with_no_blocking_issues():
    source = ["MGX announced the final close of Fund I at $49 billion."]
    translated = ["MGX宣布一期基金最终募集规模达490亿美元。"]

    decision = evaluate_subtitle_translation_candidate(
        source,
        translated,
        provider="UnitTest",
        final_provider=False,
    )

    assert decision.accepted
    assert decision.action == "accept"
    assert decision.status == "passed"
    assert not decision.should_fallback
    assert not decision.should_fail


def test_quality_decision_falls_back_on_blocking_issue_before_final_provider():
    source = ["MGX announced the final close of Fund I at $49 billion."]
    translated = ["490亿主权基金撤退。"]

    decision = evaluate_subtitle_translation_candidate(
        source,
        translated,
        provider="UnitTest",
        final_provider=False,
    )

    assert not decision.accepted
    assert decision.should_fallback
    assert not decision.should_fail
    assert decision.blocking_issues[0].code == "FINANCE_EVENT_DIRECTION_REVERSAL"


def test_quality_decision_fails_on_blocking_issue_at_final_provider():
    source = ["MGX announced the final close of Fund I at $49 billion."]
    translated = ["490亿主权基金撤退。"]

    decision = evaluate_subtitle_translation_candidate(
        source,
        translated,
        provider="UnitTest",
        final_provider=True,
    )

    assert not decision.accepted
    assert decision.should_fail
    assert not decision.should_fallback
    assert "FINANCE_EVENT_DIRECTION_REVERSAL" in decision.blocking_summary()


def test_quality_decision_audit_event_is_report_ready():
    source = ["MGX announced that it has closed its Fund I at $49 billion."]
    translated = ["MGX宣布第一期基金已以490亿美元关闭。"]

    decision = evaluate_subtitle_translation_candidate(
        source,
        translated,
        provider="UnitTest",
        final_provider=True,
    )
    event = decision.to_audit_event(final_provider=True)

    assert event["provider"] == "UnitTest"
    assert event["final_provider"] is True
    assert event["status"] == "passed"
    assert event["action"] == "accept"
    assert event["warning_issues"][0]["code"] == "FINANCE_TERM_AMBIGUOUS_CLOSE"

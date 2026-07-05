# -*- coding: utf-8 -*-
"""Unit tests for subtitle_translation_quality.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖字幕翻译候选质量决策与审计事件 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖质量上下文参与守门与审计事件输出 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.subtitle_translation_quality import (  # noqa: E402
    SubtitleTranslationQualityContext,
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


def test_quality_context_is_included_in_audit_event():
    source = ["It closed at $49 billion."]
    translated = ["它最终募集规模达490亿美元。"]
    quality_context = SubtitleTranslationQualityContext(
        source_context_text="MGX announced the final close of Fund I at $49 billion.",
        domain="finance/technology",
        facts=["The source describes a fund reaching final close/completing fundraising."],
        term_notes=["'final close' means 最终关账, not 关闭."],
    )

    decision = evaluate_subtitle_translation_candidate(
        source,
        translated,
        provider="UnitTest",
        final_provider=True,
        quality_context=quality_context,
    )
    event = decision.to_audit_event(final_provider=True)

    assert event["quality_context"]["domain"] == "finance/technology"
    assert "final close" in event["quality_context"]["term_notes"][0]


def test_quality_context_can_supply_missing_fact_signal_to_guard():
    source = ["It closed at $49 billion."]
    translated = ["它撤退了490亿美元。"]
    quality_context = SubtitleTranslationQualityContext(
        source_context_text="MGX announced the final close of Fund I at $49 billion.",
        domain="finance",
        facts=["The source describes a fund reaching final close/completing fundraising."],
    )

    decision = evaluate_subtitle_translation_candidate(
        source,
        translated,
        provider="UnitTest",
        final_provider=False,
        quality_context=quality_context,
    )

    assert decision.should_fallback
    assert decision.blocking_issues[0].code == "FINANCE_EVENT_DIRECTION_REVERSAL"

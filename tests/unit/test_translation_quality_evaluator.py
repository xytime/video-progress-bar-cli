# -*- coding: utf-8 -*-
"""Unit tests for translation_quality_evaluator.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖通用翻译质量 evaluator 的接受、降级、失败与审计输出 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_quality_evaluator import (  # noqa: E402
    TranslationQualityContext,
    evaluate_translation_candidate,
)


def test_evaluator_accepts_clean_candidate():
    decision = evaluate_translation_candidate(
        ["MGX announced the final close of Fund I at $49 billion."],
        ["MGX宣布一期基金最终募集规模达490亿美元。"],
        provider="UnitTest",
        final_provider=False,
    )

    assert decision.accepted
    assert decision.action == "accept"
    assert decision.to_audit_event()["provider"] == "UnitTest"


def test_evaluator_falls_back_before_final_provider():
    decision = evaluate_translation_candidate(
        ["MGX announced the final close of Fund I at $49 billion."],
        ["490亿主权基金撤退。"],
        provider="UnitTest",
        final_provider=False,
    )

    assert not decision.accepted
    assert decision.should_fallback
    assert decision.blocking_issues[0].code == "FINANCE_EVENT_DIRECTION_REVERSAL"


def test_evaluator_fails_at_final_provider():
    decision = evaluate_translation_candidate(
        ["MGX announced the final close of Fund I at $49 billion."],
        ["490亿主权基金撤退。"],
        provider="UnitTest",
        final_provider=True,
    )

    assert decision.should_fail
    assert "FINANCE_EVENT_DIRECTION_REVERSAL" in decision.blocking_summary()


def test_evaluator_merges_consistency_warnings_and_context():
    context = TranslationQualityContext(
        source_context_text="MGX announced the final close of Fund I at $49 billion.",
        domain="finance/technology",
        facts=["The source describes a fund reaching final close/completing fundraising."],
        term_notes=["'final close' means 最终关账, not 关闭."],
    )
    decision = evaluate_translation_candidate(
        [
            "MGX announced the final close of Fund I at $49 billion.",
            "MGX closed its fund after strong investor demand.",
        ],
        [
            "MGX宣布一期基金最终募集规模达490亿美元。",
            "MGX在强劲投资者需求后关闭了该基金。",
        ],
        provider="UnitTest",
        quality_context=context,
    )
    event = decision.to_audit_event(final_provider=True)

    assert event["quality_context"]["domain"] == "finance/technology"
    assert "TERM_CONSISTENCY_FUND_CLOSE_DRIFT" in {
        issue["code"] for issue in event["warning_issues"]
    }

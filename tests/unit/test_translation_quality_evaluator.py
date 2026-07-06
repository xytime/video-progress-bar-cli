# -*- coding: utf-8 -*-
"""Unit tests for translation_quality_evaluator.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖通用翻译质量 evaluator 的接受、降级、失败与审计输出 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖金额单位漂移 warning 进入通用 evaluator audit |
| 1.2.0   | 2026-07-06 | Codex  | 覆盖实体上下文进入审计并触发实体丢失 warning |
| 1.3.0   | 2026-07-06 | Codex  | 覆盖英语习语被逐词直译时进入自然度 warning |
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
        entities=["MGX"],
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
    assert event["quality_context"]["entities"] == ["MGX"]
    assert "TERM_CONSISTENCY_FUND_CLOSE_DRIFT" in {
        issue["code"] for issue in event["warning_issues"]
    }


def test_evaluator_includes_amount_unit_drift_warning():
    decision = evaluate_translation_candidate(
        [
            "MGX announced the final close of Fund I at $49 billion.",
            "The same $49 billion fund was backed by major investors.",
        ],
        [
            "MGX宣布一期基金最终募集规模达490亿美元。",
            "同一只49亿美元基金获得主要投资者支持。",
        ],
        provider="UnitTest",
        final_provider=True,
    )
    event = decision.to_audit_event()

    assert decision.accepted
    assert "AMOUNT_CONSISTENCY_UNIT_DRIFT" in {
        issue["code"] for issue in event["warning_issues"]
    }


def test_evaluator_uses_context_entities_for_missing_entity_warning():
    context = TranslationQualityContext(
        source_context_text="MGX announced the final close of Fund I.",
        domain="finance",
        entities=["MGX"],
    )
    decision = evaluate_translation_candidate(
        ["The fund exceeded its target."],
        ["该基金超过目标。"],
        provider="UnitTest",
        quality_context=context,
    )

    assert decision.accepted
    assert "ENTITY_CONSISTENCY_MISSING_PROTECTED_ENTITY" in {
        issue.code for issue in decision.warning_issues
    }


def test_evaluator_includes_fluency_warning_for_literal_calque():
    decision = evaluate_translation_candidate(
        ["Let's get into it now. This should be on your radar."],
        ["让我们现在进入它。这应该在你的雷达上。"],
        provider="UnitTest",
        final_provider=True,
    )

    assert decision.accepted
    assert {
        issue.code for issue in decision.warning_issues
    } >= {
        "FLUENCY_LITERAL_CALQUE_GET_INTO_IT",
        "FLUENCY_LITERAL_CALQUE_RADAR",
    }

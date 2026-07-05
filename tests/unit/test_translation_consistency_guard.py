# -*- coding: utf-8 -*-
"""Unit tests for translation_consistency_guard.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖整片基金 close 术语一致性检查 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖金额单位漂移 consistency warning |
| 1.2.0   | 2026-07-06 | Codex  | 覆盖受保护英文实体整片丢失 warning |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_consistency_guard import (  # noqa: E402
    evaluate_translation_consistency,
)


def test_consistency_guard_warns_when_fund_close_translation_drifts():
    source_texts = [
        "MGX announced the final close of Fund I at $49 billion.",
        "The fund was oversubscribed and exceeded its initial target.",
        "MGX closed its fund after strong investor demand.",
    ]
    translated_texts = [
        "MGX宣布一期基金最终募集规模达490亿美元。",
        "该基金超募，并超过最初目标。",
        "MGX在强劲投资者需求后关闭了该基金。",
    ]

    issues = evaluate_translation_consistency(source_texts, translated_texts)

    assert [issue.code for issue in issues] == ["TERM_CONSISTENCY_FUND_CLOSE_DRIFT"]
    assert issues[0].severity == "P1"


def test_consistency_guard_allows_consistent_fundraising_translation():
    source_texts = [
        "MGX announced the final close of Fund I at $49 billion.",
        "The fund was oversubscribed and exceeded its initial target.",
    ]
    translated_texts = [
        "MGX宣布一期基金最终募集规模达490亿美元。",
        "该基金超募，并超过最初目标。",
    ]

    assert evaluate_translation_consistency(source_texts, translated_texts) == []


def test_consistency_guard_does_not_trigger_without_source_signal():
    source_texts = ["The company closed the office yesterday."]
    translated_texts = ["该公司昨天关闭了办公室。"]

    assert evaluate_translation_consistency(source_texts, translated_texts) == []


def test_consistency_guard_warns_when_amount_unit_drifts_inside_candidate():
    source_texts = [
        "MGX announced the final close of Fund I at $49 billion.",
        "The same $49 billion fund was backed by major investors.",
    ]
    translated_texts = [
        "MGX宣布一期基金最终募集规模达490亿美元。",
        "同一只49亿美元基金获得主要投资者支持。",
    ]

    issues = evaluate_translation_consistency(source_texts, translated_texts)

    assert "AMOUNT_CONSISTENCY_UNIT_DRIFT" in {issue.code for issue in issues}


def test_consistency_guard_allows_consistent_amount_units():
    source_texts = [
        "MGX announced the final close of Fund I at $49 billion.",
        "The same $49 billion fund was backed by major investors.",
    ]
    translated_texts = [
        "MGX宣布一期基金最终募集规模达490亿美元。",
        "同一只490亿美元基金获得主要投资者支持。",
    ]

    assert evaluate_translation_consistency(source_texts, translated_texts) == []


def test_consistency_guard_warns_when_repeated_protected_entity_disappears():
    source_texts = [
        "MGX announced the final close of Fund I.",
        "MGX exceeded its initial target.",
    ]
    translated_texts = [
        "该基金宣布完成一期基金最终募集。",
        "该基金超过最初目标。",
    ]

    issues = evaluate_translation_consistency(source_texts, translated_texts)

    assert "ENTITY_CONSISTENCY_MISSING_PROTECTED_ENTITY" in {issue.code for issue in issues}


def test_consistency_guard_allows_preserved_protected_entity():
    source_texts = [
        "MGX announced the final close of Fund I.",
        "MGX exceeded its initial target.",
    ]
    translated_texts = [
        "MGX宣布完成一期基金最终募集。",
        "MGX超过最初目标。",
    ]

    assert evaluate_translation_consistency(source_texts, translated_texts) == []

# -*- coding: utf-8 -*-
"""Unit tests for translation_quality_guard.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖基金 close 方向反转、有效译文放行、金额数量级错误 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖上下文本句优先与批量阻断摘要 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_quality_guard import (  # noqa: E402
    evaluate_translation_batch,
    evaluate_translation_pair,
)


def test_fund_final_close_not_market_exit():
    source = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial $45 billion target."
    )
    translated = "490亿主权基金撤退，主权投资基金选择退出市场。"

    result = evaluate_translation_pair(source, translated)

    assert not result.passed
    assert result.max_severity == "P0"
    assert any(issue.code == "FINANCE_EVENT_DIRECTION_REVERSAL" for issue in result.issues)


def test_fund_final_close_valid_translation_passes():
    source = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial $45 billion target."
    )
    translated = "MGX一期基金最终募集规模达490亿美元，超过原定450亿美元目标。"

    result = evaluate_translation_pair(source, translated)

    assert result.passed
    assert result.max_severity == "PASS"


def test_fund_closed_as_closed_is_suspicious_but_not_same_as_exit():
    source = "MGX announced that it has closed its Fund I at $49 billion."
    translated = "MGX宣布第一期基金已以490亿美元关闭。"

    result = evaluate_translation_pair(source, translated)

    assert not result.passed
    assert result.max_severity == "P1"
    assert any(issue.code == "FINANCE_TERM_AMBIGUOUS_CLOSE" for issue in result.issues)


def test_billion_to_trillion_magnitude_block():
    source = (
        "The four largest platforms committed $650 billion "
        "in capital expenditure."
    )
    translated = "四大平台承诺了650万亿美元的资本支出。"

    result = evaluate_translation_pair(source, translated)

    assert not result.passed
    assert result.max_severity == "P0"
    assert any(issue.code == "NUMBER_MAGNITUDE_MISMATCH" for issue in result.issues)


def test_exit_when_source_exit_passes():
    source = "In this environment, early investors can finally find their exit."
    translated = "在这种环境下，早期投资者终于可以找到退出路径。"

    result = evaluate_translation_pair(source, translated)

    assert result.passed
    assert not result.issues


def test_local_exit_overrides_fundraising_context():
    context = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial target."
    )
    source = "In this environment, early investors can finally find their exit."
    translated = "在这种环境下，早期投资者终于可以找到退出路径。"

    result = evaluate_translation_pair(source, translated, context_text=context)

    assert result.passed
    assert not result.issues


def test_batch_summary_reports_blocking_issues_only_for_p0():
    sources = [
        "MGX announced that it has closed its Fund I at $49 billion.",
        "The platforms committed $650 billion in capital expenditure.",
    ]
    translated = [
        "MGX宣布第一期基金已以490亿美元关闭。",
        "这些平台承诺650万亿美元资本支出。",
    ]

    summary = evaluate_translation_batch(sources, translated)

    assert not summary.passed
    assert len(summary.warning_issues) == 1
    assert len(summary.blocking_issues) == 1
    assert summary.blocking_issues[0].code == "NUMBER_MAGNITUDE_MISMATCH"

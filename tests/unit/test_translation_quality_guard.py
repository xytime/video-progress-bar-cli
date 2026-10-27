# -*- coding: utf-8 -*-
"""Unit tests for translation_quality_guard.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖基金 close 方向反转、有效译文放行、金额数量级错误 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖上下文本句优先与批量阻断摘要 |
| 1.2.0   | 2026-07-05 | Codex  | 覆盖无 $ 金融金额抽取与非金融 million 误伤防护 |
| 1.3.0   | 2026-07-05 | Codex  | 覆盖 $49B/49B fund 等 B/M/T 金融金额缩写 |
| 1.4.0   | 2026-07-06 | Codex  | 覆盖 US$49bn/49bn fund 等 bn/mn/tn 金融金额缩写 |
| 1.5.0   | 2026-07-06 | Codex  | 覆盖金额 mismatch 审计信号不使用科学计数法 |
| 1.6.0   | 2026-10-27 | Codex  | 覆盖金额缩写词边界、普通美元译文、相邻字幕拆分单位与上下文金额隔离 |
"""

import sys
from pathlib import Path

import pytest

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_quality_guard import (  # noqa: E402
    evaluate_translation_batch,
    evaluate_translation_pair,
    extract_fact_signal,
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


def test_dollar_b_suffix_amount_is_checked():
    source = "The four largest platforms committed $650B in capital expenditure."
    translated = "四大平台承诺了650万亿美元的资本支出。"

    result = evaluate_translation_pair(source, translated)

    assert not result.passed
    assert result.max_severity == "P0"
    assert any(issue.code == "NUMBER_MAGNITUDE_MISMATCH" for issue in result.issues)


def test_us_dollar_bn_suffix_amount_is_checked():
    source = "MGX announced the final close of Fund I at US$49bn."
    translated = "MGX宣布一期基金最终募集规模达49亿美元。"

    result = evaluate_translation_pair(source, translated)

    assert not result.passed
    assert result.max_severity == "P1"
    assert any(issue.code == "NUMBER_MAGNITUDE_SUSPECT" for issue in result.issues)


def test_bare_billion_finance_amount_is_checked():
    source = "MGX closes 49 billion AI fund after exceeding its target."
    translated = "MGX完成49亿美元AI基金募集，超过目标。"

    result = evaluate_translation_pair(source, translated)

    assert not result.passed
    assert result.max_severity == "P1"
    assert any(issue.code == "NUMBER_MAGNITUDE_SUSPECT" for issue in result.issues)


def test_bare_b_suffix_finance_amount_is_checked():
    source = "MGX closes 49B AI fund after exceeding its target."
    translated = "MGX完成49亿美元AI基金募集，超过目标。"

    result = evaluate_translation_pair(source, translated)

    assert not result.passed
    assert result.max_severity == "P1"
    assert any(issue.code == "NUMBER_MAGNITUDE_SUSPECT" for issue in result.issues)


def test_bare_bn_suffix_finance_amount_is_checked():
    source = "MGX closes 49bn AI fund after exceeding its target."
    translated = "MGX完成49亿美元AI基金募集，超过目标。"

    result = evaluate_translation_pair(source, translated)

    assert not result.passed
    assert result.max_severity == "P1"
    assert any(issue.code == "NUMBER_MAGNITUDE_SUSPECT" for issue in result.issues)


def test_bare_million_users_is_not_treated_as_usd_amount():
    signal = extract_fact_signal("The product reached 5 million users in one week.", lang="en")

    assert signal.amounts_usd == []


def test_bare_m_suffix_users_is_not_treated_as_usd_amount():
    signal = extract_fact_signal("The product reached 5M users in one week.", lang="en")

    assert signal.amounts_usd == []


def test_bare_mn_suffix_users_is_not_treated_as_usd_amount():
    signal = extract_fact_signal("The product reached 5mn users in one week.", lang="en")

    assert signal.amounts_usd == []


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


def test_amount_mismatch_signal_uses_readable_usd_format():
    result = evaluate_translation_pair(
        "The investment was valued at $4200.",
        "这笔投资估值为42亿美元。",
    )

    issue = result.issues[0]

    assert issue.code == "NUMBER_MAGNITUDE_MISMATCH"
    assert issue.source_signal == "$4,200"
    assert "e+" not in issue.source_signal


@pytest.mark.parametrize(("source", "amounts"), [
    ("Brent surged through $115 bucks per barrel.", [115.0]),
    ("Brent surged through $115\nbucks per barrel.", [115.0]),
    ("Oil trades at $75 to $80 per barrel.", [75.0, 80.0]),
    ("The $50 market order executed.", [50.0]),
    ("The price is $20 today.", [20.0]),
    ("The $115 billionaires club.", [115.0]),
])
def test_dollar_amount_units_do_not_consume_word_prefixes(source, amounts):
    assert extract_fact_signal(source).amounts_usd == amounts


@pytest.mark.parametrize(("source", "amount"), [
    ("The fund raised $49B.", 49_000_000_000),
    ("The fund raised US$49bn.", 49_000_000_000),
    ("Credit balances exceeded $1.17 trillion.", 1_170_000_000_000),
    ("The 49B AI fund closed.", 49_000_000_000),
    ("The 49bn AI fund closed.", 49_000_000_000),
    ("The fund received $5mn.", 5_000_000),
])
def test_complete_finance_units_remain_supported(source, amount):
    assert extract_fact_signal(source).amounts_usd == [amount]


@pytest.mark.parametrize(("translated", "amount"), [
    ("每桶115美元。", 115),
    ("每桶115美金。", 115),
    ("共支付1,150美元。", 1150),
    ("共支付1.15万美元。", 11500),
    ("估值1,150亿美元。", 115_000_000_000),
])
def test_plain_chinese_dollar_amounts_are_checked(translated, amount):
    assert extract_fact_signal(translated).amounts_usd == [amount]


@pytest.mark.parametrize("translated", ["油价115美元。", "油价$115。"])
def test_context_cannot_promote_a_real_small_dollar_price(translated):
    result = evaluate_translation_pair(
        "Oil is at $115.", translated,
        context_text="Unrelated fund at $115 billion; oil is at $115.",
    )
    assert result.source_signal.amounts_usd == [115]
    assert not result.issues


@pytest.mark.parametrize("context", ["", "An unrelated fund raised $115 billion."])
def test_real_dollar_to_billion_translation_error_still_blocks(context):
    result = evaluate_translation_pair("Oil is at $115.", "油价1150亿美元。", context_text=context)
    assert result.max_severity == "P0"
    assert result.issues[0].code == "NUMBER_MAGNITUDE_MISMATCH"
    assert result.issues[0].source_signal == "$115"
    assert result.issues[0].translation_signal == "$115B"


@pytest.mark.parametrize(("next_source", "translated", "amount"), [
    ("billion in capital expenditure.", "投资6000亿美元。", 600_000_000_000),
    ("million in capital expenditure.", "投资6亿美元。", 600_000_000),
    ("bn in capital expenditure.", "投资6000亿美元。", 600_000_000_000),
])
def test_split_currency_unit_uses_only_the_actual_next_source(next_source, translated, amount):
    result = evaluate_translation_pair(
        "The platforms committed $600", translated, next_source_text=next_source,
    )
    assert result.source_signal.amounts_usd == [amount]
    assert not result.issues


@pytest.mark.parametrize("next_source", [
    "bucks per barrel.",
    "billionaires discussed it.",
    "Elsewhere, a fund raised $600 billion.",
    "to fund their purchases.",
    "market prices remained stable.",
    "",
])
def test_neighbor_or_context_without_a_split_unit_cannot_promote_amount(next_source):
    result = evaluate_translation_pair(
        "Oil costs $600", "油价600美元。", next_source_text=next_source,
        context_text="Other assets are valued at $600 billion.",
    )
    assert result.source_signal.amounts_usd == [600]
    assert not result.issues


def test_split_unit_requires_the_original_source_to_end_in_a_bare_amount():
    result = evaluate_translation_pair(
        "Oil costs $600 today.", "油价今天600美元。", next_source_text="billion in other investments.",
    )
    assert result.source_signal.amounts_usd == [600]
    assert not result.issues


def test_batch_preserves_real_split_amount_and_blocks_wrong_translation():
    source = ["The platforms committed $600", "billion in capital expenditure."]
    passed = evaluate_translation_batch(source, ["平台承诺6000亿美元", "资本支出。"])
    blocked = evaluate_translation_batch(source, ["平台承诺600美元", "资本支出。"])
    assert not passed.blocking_issues
    assert blocked.blocking_issues[0].code == "NUMBER_MAGNITUDE_MISMATCH"


def test_batch_boundary_can_receive_the_actual_next_source():
    result = evaluate_translation_batch(
        ["The platforms committed $600"], ["平台承诺6000亿美元"],
        next_source_text="billion in capital expenditure.",
    )
    assert result.results[0].source_signal.amounts_usd == [600_000_000_000]
    assert not result.blocking_issues

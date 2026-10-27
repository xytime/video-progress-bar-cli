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
| 1.6.0   | 2026-10-27 | Codex  | 金额边界与相邻拆句、自然中文单位、非金额锚点及全部金额精确覆盖回归 |
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


@pytest.mark.parametrize(("source", "translated", "signals"), [
    (
        "when oil crosses $115 and invoices surge? Well, let's break down the multi-assay transmission",
        "标普500企业利润率是第一个关键维度。",
        ["$115"],
    ),
    (
        "big time stretched. Revolving credit card balances sit at record levels above $1.17 trillion. You",
        "你现在大概已经知道，平均年利率被钉在21.5%以上。",
        ["$1.17T"],
    ),
    (
        "higher, closer to 30%. When working families are forced to pay an extra $50 or $75 per tank at the",
        "这笔钱不会凭空消失，而是直接从可选消费中转移出去。",
        ["$50", "$75"],
    ),
])
def test_required_amount_coverage_blocks_real_cross_segment_fact_shifts(source, translated, signals):
    result = evaluate_translation_pair(source, translated, require_amount_coverage=True)
    assert [issue.code for issue in result.issues] == ["NUMBER_AMOUNT_MISSING"] * len(signals)
    assert [issue.source_signal for issue in result.issues] == signals
    assert all(issue.translation_signal == "amount_not_in_segment" for issue in result.issues)
    assert result.max_severity == "P0"
    assert not evaluate_translation_pair(source, translated).issues


@pytest.mark.parametrize(("source", "translated", "next_source"), [
    ("Brent surged through $115", "布伦特原油突破每桶115", "bucks per barrel."),
    ("Brent is $115.", "布伦特原油115美元。", ""),
    ("The fund committed $600", "该基金承诺600", "billion in capital expenditure."),
    ("The fund committed $600", "该基金承诺6000亿美元", "billion in capital expenditure."),
    ("Credit balances exceeded $1.17 trillion.", "信用卡余额超过1.17万亿。", ""),
    ("Credit balances exceeded $1.17 trillion.", "信用卡余额超过1,170,000,000,000。", ""),
    ("The fund raised $1 million.", "该基金募集100万。", ""),
    ("The cost is $50,000.", "成本5万美金。", ""),
    ("The cost is $50,000.", "成本5万美元。", ""),
    ("The fee is $5,000.", "费用5千美元。", ""),
    ("The fee is $5,000.", "费用5千美金。", ""),
    ("The fee is $5,000.", "费用5千。", ""),
    ("The fee is $500.", "费用5百美元。", ""),
    ("The fee is $500.", "费用5百美金。", ""),
    ("The investment is $50 million.", "投资5千万美元。", ""),
    ("The investment is $50 million.", "投资$5千万。", ""),
    ("The investment is $5 million.", "投资5百万美元。", ""),
    ("The investment is $500,000.", "投资5十万美元。", ""),
    ("The investment is $5 billion.", "投资5十亿美元。", ""),
])
def test_required_amount_coverage_accepts_equivalent_or_genuinely_split_anchors(source, translated, next_source):
    result = evaluate_translation_pair(
        source, translated, next_source_text=next_source, require_amount_coverage=True,
    )
    assert not result.issues


@pytest.mark.parametrize("translated", [
    "利润率115%。", "收益率115个百分点。", "收益率115百分点。", "收益率115基点。", "收益率115个基点。",
    "收益率115 bps。", "收益率115 BPS。", "历史115年。", "历史115年份。",
    "持有115股。", "人口115人。", "人口115个人。", "库存115桶。", "估值115倍。",
    "人口115万人。", "库存115万桶。", "历史115万年。", "订单115个。",
])
def test_required_amount_coverage_does_not_accept_non_monetary_units_as_dollars(translated):
    result = evaluate_translation_pair("Oil is $115.", translated, require_amount_coverage=True)
    assert result.translation_signal.amounts_usd == []
    assert result.issues[0].code == "NUMBER_AMOUNT_MISSING"


@pytest.mark.parametrize(("source", "translated", "code"), [
    ("Oil is $115.", "油价1150亿美元。", "NUMBER_MAGNITUDE_MISMATCH"),
    ("Oil is $115.", "油价115万。", "NUMBER_MAGNITUDE_MISMATCH"),
    ("Oil is $115.", "油价115万美金。", "NUMBER_MAGNITUDE_MISMATCH"),
    ("Oil is $115.", "油价$115万。", "NUMBER_MAGNITUDE_MISMATCH"),
    ("Oil is $115.", "油价115千美元。", "NUMBER_MAGNITUDE_MISMATCH"),
    ("The fee is $1150.", "费用115美元。", "NUMBER_MAGNITUDE_SUSPECT"),
])
def test_required_amount_coverage_does_not_add_a_second_code_to_magnitude_errors(source, translated, code):
    result = evaluate_translation_pair(source, translated, require_amount_coverage=True)
    assert [issue.code for issue in result.issues] == [code]


def test_required_amount_coverage_is_local_to_usd_facts_and_respects_numeric_switch():
    result = evaluate_translation_pair(
        "Bond yields declined to 4.96%.", "国债收益率下降。",
        context_text="An unrelated investment was $115 billion.", require_amount_coverage=True,
    )
    assert not result.issues
    disabled = evaluate_translation_pair(
        "Oil is $115.", "利率下降。", require_amount_coverage=True, enable_numeric_checks=False,
    )
    assert not disabled.issues


def test_required_amount_coverage_cannot_borrow_an_anchor_from_the_next_translation():
    result = evaluate_translation_batch(
        ["Oil crosses $115.", "Consider corporate margins."],
        ["标普500企业利润率。", "原油突破115美元。"],
        require_amount_coverage=True,
    )
    assert result.results[0].issues[0].code == "NUMBER_AMOUNT_MISSING"
    assert result.results[0].issues[0].source_signal == "$115"
    assert not result.results[1].issues


@pytest.mark.parametrize("translated", ["家庭每箱多支付50。", "家庭每箱多支付50美元。"])
def test_required_amount_coverage_checks_each_amount_when_one_is_missing(translated):
    source = "Families pay an extra $50 or $75 per tank."
    result = evaluate_translation_pair(source, translated, require_amount_coverage=True)
    assert [(issue.code, issue.source_signal) for issue in result.issues] == [("NUMBER_AMOUNT_MISSING", "$75")]


@pytest.mark.parametrize("translated", [
    "家庭每箱多支付50或75。",
    "家庭每箱多支付50或75美元。",
    "家庭每箱多支付50美元或75美元。",
])
def test_required_amount_coverage_accepts_all_amounts_with_shared_or_explicit_currency(translated):
    result = evaluate_translation_pair(
        "Families pay an extra $50 or $75 per tank.", translated, require_amount_coverage=True,
    )
    assert not result.issues


def test_required_amount_coverage_preserves_close_but_distinct_prices():
    source = "Oil moved from $115 to $115.50."
    missing = evaluate_translation_pair(source, "油价115美元。", require_amount_coverage=True)
    assert missing.source_signal.amounts_usd == [115, 115.5]
    assert [(issue.code, issue.source_signal) for issue in missing.issues] == [("NUMBER_AMOUNT_MISSING", "$115.5")]
    complete = evaluate_translation_pair(source, "油价从115升至115.50美元。", require_amount_coverage=True)
    assert not complete.issues


def test_amount_extraction_dedupes_only_equal_values():
    signal = extract_fact_signal("The range is $115, $115.00, $115.50, and $116.")
    assert signal.amounts_usd == [115, 115.5, 116]


def test_percentage_points_are_not_parsed_as_hundreds_of_dollars():
    result = evaluate_translation_pair("The cost is $11,500.", "上升115百分点。", require_amount_coverage=True)
    assert not result.translation_signal.amounts_usd
    assert [(issue.code, issue.source_signal) for issue in result.issues] == [("NUMBER_AMOUNT_MISSING", "$11,500")]


def test_required_amount_coverage_does_not_reuse_a_scaled_amount_coefficient():
    source = "The costs are $100, $1 million and $500."
    missing = evaluate_translation_pair(source, "成本100万和500美元。", require_amount_coverage=True)
    assert [(issue.code, issue.source_signal) for issue in missing.issues] == [("NUMBER_AMOUNT_MISSING", "$100")]
    complete = evaluate_translation_pair(source, "成本100美元、100万和500美元。", require_amount_coverage=True)
    assert not complete.issues

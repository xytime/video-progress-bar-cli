# -*- coding: utf-8 -*-
"""Unit tests for translation_context.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖全片上下文、金融术语提示和长文本采样 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖无 $ 金融金额进入上下文金额提示 |
| 1.2.0   | 2026-07-05 | Codex  | 覆盖 B/M/T 金融金额缩写进入上下文金额提示 |
| 1.3.0   | 2026-07-06 | Codex  | 覆盖受保护英文实体进入翻译上下文 prompt |
| 1.4.0   | 2026-07-06 | Codex  | 覆盖长视频中段关键事实也会进入翻译上下文 |
| 1.5.0   | 2026-07-06 | Codex  | 覆盖 US$49bn/49bn 金融金额缩写进入上下文金额提示 |
| 1.6.0   | 2026-07-06 | Codex  | 覆盖小额美元事实提示不使用科学计数法 |
| 1.7.0   | 2026-10-27 | Codex  | 覆盖真实油价字幕在跨段 bucks 开头时不生成虚假十亿美元上下文 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_context import build_translation_context  # noqa: E402


def test_build_translation_context_detects_fund_final_close():
    texts = [
        "MGX announced the final close of Fund I at $49 billion.",
        "The fund exceeded its initial target.",
        "It reflects strong demand for AI infrastructure.",
    ]

    context = build_translation_context(texts)
    prompt_context = context.to_prompt_context()

    assert context.domain == "finance/technology"
    assert any("completing fundraising" in fact for fact in context.facts)
    assert context.entities == ["MGX"]
    assert "最终关账" in prompt_context
    assert "撤退" in prompt_context
    assert "MGX" in prompt_context


def test_translation_context_preserves_amount_magnitude_hint():
    context = build_translation_context([
        "The four platforms committed $650 billion in capital expenditure."
    ])

    prompt_context = context.to_prompt_context()

    assert "$650B" in prompt_context
    assert "capital expenditure" in prompt_context
    assert "billion/trillion" in prompt_context


def test_translation_context_preserves_bare_finance_amount_magnitude_hint():
    context = build_translation_context([
        "MGX closes 49 billion AI fund after exceeding its initial target."
    ])

    prompt_context = context.to_prompt_context()

    assert "$49B" in prompt_context


def test_translation_context_preserves_compact_finance_amount_hints():
    context = build_translation_context([
        "MGX closes 49B AI fund after exceeding its initial target.",
        "The four platforms committed $650B in capex.",
    ])

    prompt_context = context.to_prompt_context()

    assert "$49B" in prompt_context
    assert "$650B" in prompt_context


def test_translation_context_preserves_bn_finance_amount_hints():
    context = build_translation_context([
        "MGX announced the final close of Fund I at US$49bn.",
        "It had initially targeted 45bn in commitments.",
    ])

    prompt_context = context.to_prompt_context()

    assert "$49B" in prompt_context
    assert "$45B" in prompt_context


def test_translation_context_keeps_general_domain_for_plain_text():
    context = build_translation_context([
        "Today we are making a simple pasta sauce with tomatoes and basil."
    ])

    assert context.domain == "general"
    assert not context.facts


def test_translation_context_uses_full_video_not_only_head_tail_sample():
    texts = (
        [f"Opening general market commentary line {idx}." for idx in range(45)]
        + [
            (
                "MGX announced the final close of its AI infrastructure fund "
                "with $49 billion in capital commitments."
            )
        ]
        + [f"Closing general commentary line {idx}." for idx in range(25)]
    )

    context = build_translation_context(texts)
    prompt_context = context.to_prompt_context()

    assert context.domain == "finance/technology"
    assert context.entities == ["MGX"]
    assert "$49B" in prompt_context
    assert any("completing fundraising" in fact for fact in context.facts)


def test_translation_context_formats_small_usd_amounts_without_scientific_notation():
    context = build_translation_context([
        "The fund was valued at $4200 after a small follow-on investment."
    ])

    prompt_context = context.to_prompt_context()

    assert "$4,200" in prompt_context
    assert "$4.2e+03" not in prompt_context


def test_oil_price_video_context_does_not_invent_billion_dollar_barrels():
    # AkTXAcMgO3E 的真实字幕边界：第6段末尾 $115，第7段开头 bucks。
    context = build_translation_context([
        "Brent crude oil just surged through $115",
        "bucks per barrel. That's $115 a barrel on critical global oil benchmarks.",
        "Revolving credit card balances sit at record levels above $1.17 trillion.",
        "Families pay an extra $50 or $75 per tank.",
        "The Fed can't aggressively cut policy rates with oil at $115.",
        "Brent Crude hits $115 and factory selling prices exploded.",
    ])
    prompt_context = context.to_prompt_context()
    assert "$115B" not in prompt_context
    assert "$115" in prompt_context
    assert "$1.17T" in prompt_context
    assert "$50" in prompt_context
    assert "$75" in prompt_context


def test_context_keeps_a_genuinely_split_billion_dollar_fact():
    context = build_translation_context([
        "The platforms committed $600",
        "billion in capital expenditure.",
    ])
    assert "$600B" in context.to_prompt_context()

# -*- coding: utf-8 -*-
"""Unit tests for translation_context.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖全片上下文、金融术语提示和长文本采样 |
| 1.1.0   | 2026-07-05 | Codex  | 覆盖无 $ 金融金额进入上下文金额提示 |
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
    assert "最终关账" in prompt_context
    assert "撤退" in prompt_context


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


def test_translation_context_keeps_general_domain_for_plain_text():
    context = build_translation_context([
        "Today we are making a simple pasta sauce with tomatoes and basil."
    ])

    assert context.domain == "general"
    assert not context.facts

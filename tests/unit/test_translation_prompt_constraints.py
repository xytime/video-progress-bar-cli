# -*- coding: utf-8 -*-
"""Unit tests for translation_prompt_constraints.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：覆盖共享翻译生产硬约束渲染 |
| 1.1.0   | 2026-07-06 | Codex  | 覆盖非字幕调用可关闭字幕段落顺序约束 |
| 1.2.0   | 2026-10-27 | Codex  | 验证消歧背景模式不覆盖逐段原文权威，默认调用保持原约束 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_prompt_constraints import (  # noqa: E402
    render_translation_constraints,
)


def test_render_translation_constraints_contains_finance_rules_and_context():
    rendered = render_translation_constraints("Preserve USD amount magnitudes: $49B.")

    assert "hard constraints" in rendered
    assert "close/final close usually means 完成募集/最终关账" in rendered
    assert "billion/bn = 十亿美元" in rendered
    assert "Do not merge, split, omit, or reorder subtitle segments" in rendered
    assert "$49B" in rendered


def test_render_translation_constraints_without_context_has_no_context_header():
    rendered = render_translation_constraints()

    assert "Global context:" not in rendered
    assert "Preserve event direction" in rendered


def test_render_translation_constraints_can_skip_subtitle_segment_rule():
    rendered = render_translation_constraints(
        "Preserve entities.",
        include_subtitle_segment_rule=False,
    )

    assert "Preserve entities." in rendered
    assert "Do not merge, split, omit, or reorder subtitle segments" not in rendered


def test_context_can_be_advisory_without_overriding_each_source_fragment():
    rendered = render_translation_constraints("Preserve entities.", context_is_authoritative=False)
    assert "only to disambiguate words already present in each source segment" in rendered
    assert "Each segment's own source text is authoritative" in rendered
    assert "hard constraints" not in rendered and "more authoritative" not in rendered
    assert "Preserve entities." in rendered
    assert "Preserve USD magnitude exactly" in rendered
    assert "Each segment owns its original time slot" in rendered

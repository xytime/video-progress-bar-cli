# -*- coding: utf-8 -*-
"""Unit tests for translation_prompt_constraints.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：覆盖共享翻译生产硬约束渲染 |
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

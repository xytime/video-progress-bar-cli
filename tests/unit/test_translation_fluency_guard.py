# -*- coding: utf-8 -*-
"""Unit tests for translation_fluency_guard.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：覆盖财经/新闻常见直译腔告警与干净译文放行 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_fluency_guard import (  # noqa: E402
    evaluate_translation_fluency,
)


def test_fluency_guard_flags_common_literal_calques():
    issues = evaluate_translation_fluency(
        [
            "This should be on your radar.",
            "Let's get into it now.",
            "The market caught a bid after the data release.",
            "The single most important release came on Thursday.",
        ],
        [
            "这应该在你的雷达上。",
            "让我们现在进入它。",
            "数据发布后，市场受到了竞标。",
            "周四公布的是单身最重要的数据。",
        ],
    )

    assert {
        issue.code for issue in issues
    } == {
        "FLUENCY_LITERAL_CALQUE_RADAR",
        "FLUENCY_LITERAL_CALQUE_GET_INTO_IT",
        "FLUENCY_LITERAL_CALQUE_CAUGHT_A_BID",
        "FLUENCY_LITERAL_CALQUE_SINGLE_MOST",
    }


def test_fluency_guard_ignores_natural_translation():
    issues = evaluate_translation_fluency(
        ["Let's get into it now. This should be on your radar."],
        ["我们现在进入正题。这件事你需要重点关注。"],
    )

    assert issues == []

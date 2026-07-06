# -*- coding: utf-8 -*-
"""Unit tests for translation_ab_review.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：覆盖 ASS 双语文本拆分与报告摘要 |
"""

import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.translation_ab_review import (  # noqa: E402
    split_bilingual_ass_text,
    strip_ass_tags,
    summarize_event,
)


def test_split_bilingual_ass_text_uses_hidden_alpha_separator():
    raw = (
        r"{\fnGeorgia\fs45}Gold rallied toward $4,200 an ounce\N"
        r"{\fs24\alpha&HFF&} \N"
        r"{\fnHiragino Sans GB\fs54\alpha&H00&}金价上涨至每盎司4,200美元"
    )

    source, current = split_bilingual_ass_text(raw)

    assert source == "Gold rallied toward $4,200 an ounce"
    assert current == "金价上涨至每盎司4,200美元"


def test_strip_ass_tags_collapses_forced_line_breaks():
    assert strip_ass_tags(r"{\u1}Federal\NReserve{\u0}") == "Federal Reserve"


def test_summarize_event_counts_issue_codes():
    event = {
        "provider": "DeepSeek",
        "status": "passed",
        "action": "accept",
        "warning_issues": [
            {"code": "ENTITY_CONSISTENCY_MISSING_PROTECTED_ENTITY"},
            {"code": "ENTITY_CONSISTENCY_MISSING_PROTECTED_ENTITY"},
            {"code": "AMOUNT_CONSISTENCY_UNIT_DRIFT"},
        ],
        "blocking_issues": [],
    }

    summary = summarize_event(event)

    assert summary["warning_count"] == 3
    assert summary["warning_issue_counts"]["ENTITY_CONSISTENCY_MISSING_PROTECTED_ENTITY"] == 2
    assert summary["blocking_count"] == 0

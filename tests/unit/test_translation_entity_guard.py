# -*- coding: utf-8 -*-
"""Unit tests for translation_entity_guard.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-06 | Codex  | 初始创建：覆盖受保护实体抽取、丢失检测和别名放行 |
| 1.1.0   | 2026-07-06 | Codex  | 覆盖全大写标题普通词不进入受保护实体 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.translation_entity_guard import (  # noqa: E402
    extract_protected_entities,
    find_missing_protected_entities,
)


def test_extract_protected_entities_keeps_opaque_acronyms():
    entities = extract_protected_entities([
        "MGX announced the final close of Fund I.",
        "MGX said AI infrastructure demand was strong.",
    ])

    assert entities == ["MGX"]


def test_extract_protected_entities_ignores_common_abbreviations():
    entities = extract_protected_entities("AI capex reached USD 650B after the CEO update.")

    assert entities == []


def test_extract_protected_entities_ignores_uppercase_headline_words():
    entities = extract_protected_entities(
        "The Money Just SOUNDED Its FINAL ALARM! MGX announced Fund I."
    )

    assert entities == ["MGX"]


def test_missing_entity_detection_warns_when_entity_disappears():
    missing = find_missing_protected_entities(
        ["MGX announced Fund I.", "MGX exceeded its target."],
        ["该基金超过目标并完成募集。"],
    )

    assert missing == ["MGX"]


def test_missing_entity_detection_allows_exact_entity_in_translation():
    missing = find_missing_protected_entities(
        ["MGX announced Fund I.", "MGX exceeded its target."],
        ["MGX一期基金超过目标并完成募集。"],
    )

    assert missing == []


def test_missing_entity_detection_allows_known_chinese_alias():
    missing = find_missing_protected_entities(
        ["NVIDIA reported strong demand.", "NVIDIA increased orders."],
        ["英伟达报告需求强劲，并增加订单。"],
    )

    assert missing == []

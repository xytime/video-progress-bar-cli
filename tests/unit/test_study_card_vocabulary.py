"""新闻精读卡片生词选择规则测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 覆盖十级难度映射与 B1 起点。 |
| 1.1.0 | 2026-08-03 | Codex | 覆盖左侧正文微笔记最多十个的学习卡展示上限。 |
| 1.2.0 | 2026-08-04 | Codex | 覆盖段落保底选择，避免长正文后段缺少正文微笔记。 |
| 1.3.0 | 2026-08-04 | Codex | 覆盖长文微笔记池扩容与可靠短语的独立学习标记。 |
| 1.4.0 | 2026-08-04 | Codex | 覆盖每个阅读屏候选段的八项学习标记供给。 |
"""

from video_processing.study_cards import VocabularyItem, difficulty_level, select_vocabulary


def test_difficulty_level_maps_cefr_to_the_ten_level_learning_scale():
    assert difficulty_level("A2") == 2
    assert difficulty_level("B1") == 3
    assert difficulty_level("B2") == 5
    assert difficulty_level("C1") == 7
    assert difficulty_level("specialist") == 10
    assert difficulty_level("PET") == 3
    assert difficulty_level("CET-4") == 5
    assert difficulty_level("Master") == 9


def test_selection_starts_at_level_three_without_a_global_quantity_cap():
    text = "The analyst assessed volatile markets and persistent inflation while regulators monitored liquidity risks closely."
    candidates = (
        VocabularyItem("analyst", "分析师", level="3"),
        VocabularyItem("assessed", "评估", level="4"),
        VocabularyItem("volatile", "波动剧烈的", level="5"),
        VocabularyItem("persistent", "持续的", level="5"),
        VocabularyItem("inflation", "通胀", level="3"),
        VocabularyItem("regulators", "监管机构", level="4"),
        VocabularyItem("liquidity", "流动性", level="7"),
        VocabularyItem("closely", "密切地", level="2"),
    )

    selection = select_vocabulary(text, candidates)

    assert all(difficulty_level(item.level) >= 3 for item in selection.items)
    assert len(selection.items) == selection.maximum_items
    assert selection.items[0].word == "liquidity"


def test_selection_deduplicates_words_and_prefers_the_higher_confidence_level():
    text = "Markets are volatile and markets are volatile during uncertainty."
    selection = select_vocabulary(text, (
        VocabularyItem("markets", "市场", level="2"),
        VocabularyItem("Markets", "市场", level="5"),
        VocabularyItem("volatile", "波动剧烈的", level="5"),
    ))

    selected = {item.word.lower(): item for item in selection.items}
    assert set(selected) == {"markets", "volatile"}
    assert selected["markets"].level == "5"


def test_selection_rejects_a_candidate_not_in_the_article():
    selection = select_vocabulary(
        "The weather is severe.",
        (VocabularyItem("liquidity", "流动性", level="7"),),
    )

    assert selection.items == ()


def test_selection_rejects_low_confidence_or_dictionary_fallback_candidates():
    text = "The outbreak worried students at the grocery store."
    selection = select_vocabulary(text, (
        VocabularyItem("outbreak", "暴发", level="CET-6", source="unknown", confidence=0.2),
        VocabularyItem("students", "学生", level="CET-4", source="ecdict-fallback", confidence=0.55),
        VocabularyItem("grocery", "食品杂货店", level="CET-4", source="exam-wordlists", confidence=0.95),
    ))

    assert [item.word for item in selection.items] == ["grocery"]


def test_selection_keeps_every_eligible_body_note_for_visual_layer_screen_selection():
    words = [f"advanced{i}" for i in range(240)]
    candidates = tuple(VocabularyItem(word, "高阶词", level="CET-6") for word in words)

    selection = select_vocabulary(" ".join(words), candidates)

    assert len(selection.items) == len(words)


def test_selection_keeps_micro_notes_across_reading_paragraphs():
    paragraphs = [
        "analysts tracked liquidity pressure across markets today",
        "families found a standout restaurant near the highway",
        "students watched firefighters contain the wildfire overnight",
        "drivers stopped for carryout tacos after the report",
    ]
    text = " ".join(paragraphs)
    candidates = (
        VocabularyItem("liquidity", "流动性", level="Master"),
        VocabularyItem("pressure", "压力", level="CET-6"),
        VocabularyItem("markets", "市场", level="CET-6"),
        VocabularyItem("standout", "亮点", level="PET"),
        VocabularyItem("wildfire", "野火", level="PET"),
        VocabularyItem("carryout", "外带食品", level="PET"),
    )

    selection = select_vocabulary(text, candidates, coverage_texts=paragraphs)

    assert {item.word for item in selection.items} >= {"liquidity", "standout", "wildfire", "carryout"}


def test_reliable_phrase_can_be_marked_even_if_its_component_words_are_basic():
    text = "Families were in the grips of a difficult situation."
    selection = select_vocabulary(text, (
        VocabularyItem("in the grips of", "深陷于；受……控制", level="KET", source="manual-curated"),
        VocabularyItem("families", "家庭", level="KET", source="exam-wordlists", confidence=0.95),
    ))

    assert [item.word for item in selection.items] == ["in the grips of"]


def test_selection_reserves_multiple_items_for_each_reading_screen_candidate_section():
    sections = [
        "alpha beta gamma delta epsilon zeta eta theta",
        "iota kappa lambda mu nu xi omicron pi",
    ]
    candidates = tuple(
        VocabularyItem(word, "学习词", level="PET")
        for word in "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi".split()
    )

    selection = select_vocabulary(
        " ".join(sections), candidates, coverage_texts=sections,
        minimum_items_per_coverage=8,
    )

    assert len(selection.items) == 16

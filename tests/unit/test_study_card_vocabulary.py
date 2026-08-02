"""新闻精读卡片生词选择规则测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 覆盖十级难度映射、B1 起点及 25% 全文密度上限。 |
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


def test_selection_starts_at_level_three_and_never_exceeds_twenty_five_percent():
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
    assert selection.density <= 0.25
    assert len(selection.items) == selection.maximum_items
    assert selection.items[0].word == "liquidity"


def test_selection_deduplicates_words_and_prefers_the_higher_confidence_level():
    text = "Markets are volatile and markets are volatile during uncertainty."
    selection = select_vocabulary(text, (
        VocabularyItem("markets", "市场", level="2"),
        VocabularyItem("Markets", "市场", level="5"),
        VocabularyItem("volatile", "波动剧烈的", level="5"),
    ))

    assert [item.word.lower() for item in selection.items] == ["markets"]


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

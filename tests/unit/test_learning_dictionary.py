"""本机词典绑定回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-09-24 | Codex | 替换候选保留词元证据、排除重复坏词及未解析音标。 |
| 1.1.0 | 2026-09-17 | Antigravity | 验证带标点表面词在展示计划中不误触发词元音标依据校验。 |
| 1.0.0 | 2026-09-17 | Codex | 验证学习点表面词的末尾标点不改变词典证据绑定。 |
"""

from __future__ import annotations

from types import SimpleNamespace

from video_processing.study_cards import learning_dictionary
from video_processing.vocabulary import leveler


def test_attach_evidence_uses_normalized_dictionary_key_but_preserves_surface_word(tmp_path, monkeypatch):
    (tmp_path / "ecdict.csv").write_text(
        "word,phonetic,definition,translation,exchange\nfact,fækt,n.事实,n.事实,\n",
        encoding="utf-8",
    )

    class FakeLeveler:
        def __init__(self, directory):
            assert directory == tmp_path

        def analyze_word(self, word):
            assert word == "fact"
            return SimpleNamespace(recommended_level="KET", source="test")

    monkeypatch.setattr(leveler, "VocabularyLeveler", FakeLeveler)
    payload = {
        "words": [{"text": "fact,"}],
        "learning_points": [{"word": "fact,", "word_index": 0, "context_meaning_zh": "事实"}],
    }

    result = learning_dictionary.attach_evidence(payload, tmp_path)

    point = result["learning_points"][0]
    assert point["word"] == "fact,"
    assert point["phonetic_word"] == "fact"
    assert point["dictionary_senses"]["translation"] == "n.事实"


def test_reviewed_content_accepts_surface_word_with_punctuation():
    from video_processing.study_cards.display_plan import reviewed_content

    payload = {
        "headline_zh": "测试标题",
        "headline_en": "Test Headline",
        "english_text": "surface,",
        "translation_zh": "表面",
        "paragraphs": [{"english_text": "surface,", "translation_zh": "表面"}],
        "words": [{"text": "surface,", "start": 0.0, "end": 1.0}],
        "vocabulary_candidates": [],
        "learning_points": [{
            "word": "surface,",
            "word_index": 0,
            "context_meaning_zh": "表面",
            "pos": "n.",
            "phonetic": "'sә:fis",
            "phonetic_word": "surface",
            "dictionary_source": "ecdict.csv",
            "dictionary_senses": {
                "definition": "surface",
                "translation": "n. 表面",
                "exchange": "s:surfaces/p:surfaced",
            },
            "level": "中考",
        }],
    }
    content = reviewed_content(payload)
    assert len(content.vocabulary) == 1
    item = content.vocabulary[0]
    assert item.word == "surface,"
    assert item.phonetic == "'sә:fis"
    assert item.phonetic_word == "surface"


def test_revision_options_exclude_rejected_words_ambiguous_ipa_and_keep_proven_lemmas(tmp_path):
    (tmp_path / "ecdict.csv").write_text(
        "word,phonetic,definition,translation,exchange\n"
        "record,ri'kɒ:d,record,n.记录,\nvolatility,.vɒlə'tiliti,volatility,n.波动,\n"
        "note,nəut,note,n.笔记,\nnotes,,notes,n.笔记,0:note\n"
        "empty,...,empty,n.空,\n", encoding="utf-8")
    words = [{"text": w} for w in ["record", "Record,", "volatility,", "notes", "unknown", "empty"]]
    options = learning_dictionary.dictionary_word_options(words, tmp_path, excluded_words={"record"})
    assert [p["word_index"] for p in options] == [3]
    assert options[0]["phonetic_word"] == "note"
    assert options[0]["phonetic"] == "nəut"

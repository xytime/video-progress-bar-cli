# -*- coding: utf-8 -*-
"""vocab_helper 词汇口径单元测试。

# Modification History
| Version | Date       | Author          | Description                                              |
| ------- | ---------- | --------------- | -------------------------------------------------------- |
| 1.0.0   | 2026-06-28 | Claude_Opus_4.8 | 初始创建：覆盖 _filter_vocab 剔除周知专有名词/常识词（Wall Street 等），保留真生词 |
| 1.1.0   | 2026-07-13 | Codex | PET/B1 标准改为保留专有名词，删除历史黑名单断言 |
"""
from src.video_processing.utils.vocab_helper import _filter_vocab


class TestFilterVocab:
    def test_keeps_proper_nouns_and_learning_vocabulary(self):
        out = _filter_vocab({"Wall Street": "华尔街", "headline narrative": "头条叙事"})
        assert "Wall Street" in out
        assert "headline narrative" in out

    def test_keeps_entities_regardless_of_case_and_punctuation(self):
        out = _filter_vocab({"wall street.": "华尔街", "GOOGLE": "谷歌", "iPhone": "苹果手机"})
        assert len(out) == 3

    def test_keeps_genuinely_difficult_words(self):
        v = {"ubiquitous": "无处不在的", "paradigm": "范式", "leverage": "杠杆"}
        assert _filter_vocab(v) == v

    def test_non_dict_returns_empty_dict(self):
        assert _filter_vocab(None) == {}
        assert _filter_vocab("not a dict") == {}

    def test_empty_dict(self):
        assert _filter_vocab({}) == {}

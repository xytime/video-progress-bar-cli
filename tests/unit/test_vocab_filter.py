# -*- coding: utf-8 -*-
"""vocab_helper 词汇过滤单元测试（方案C）

# Modification History
| Version | Date       | Author          | Description                                              |
| ------- | ---------- | --------------- | -------------------------------------------------------- |
| 1.0.0   | 2026-06-28 | Claude_Opus_4.8 | 初始创建：覆盖 _filter_vocab 剔除周知专有名词/常识词（Wall Street 等），保留真生词 |
"""
from src.video_processing.utils.vocab_helper import _filter_vocab, _STOPWORDS


class TestFilterVocab:
    def test_removes_wall_street_keeps_real_vocab(self):
        out = _filter_vocab({"Wall Street": "华尔街", "headline narrative": "头条叙事"})
        assert "Wall Street" not in out
        assert "headline narrative" in out

    def test_case_and_punctuation_insensitive(self):
        # 大小写 + 尾随标点都应归一化后命中黑名单
        out = _filter_vocab({"wall street.": "华尔街", "GOOGLE": "谷歌", "iPhone": "苹果手机"})
        assert out == {}

    def test_keeps_genuinely_difficult_words(self):
        v = {"ubiquitous": "无处不在的", "paradigm": "范式", "leverage": "杠杆"}
        assert _filter_vocab(v) == v

    def test_non_dict_returns_empty_dict(self):
        assert _filter_vocab(None) == {}
        assert _filter_vocab("not a dict") == {}

    def test_empty_dict(self):
        assert _filter_vocab({}) == {}

    def test_stopwords_contains_expected_terms(self):
        for term in ("wall street", "google", "iphone", "new york", "ai", "ceo"):
            assert term in _STOPWORDS

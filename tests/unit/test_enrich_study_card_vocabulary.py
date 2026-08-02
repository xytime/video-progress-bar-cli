"""独立学习卡生词预处理命令测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 覆盖词汇服务结果到候选词契约的转换。 |
"""

from scripts.enrich_study_card_vocabulary import build_candidates


def test_build_candidates_preserves_model_difficulty(monkeypatch):
    monkeypatch.setattr(
        "scripts.enrich_study_card_vocabulary.extract_vocab_batch",
        lambda *_args, **_kwargs: [{
            "translation": "市场流动性承压。",
            "vocab": {"liquidity": "流动性", "pressured": "承压"},
            "vocab_levels": {"liquidity": 7, "pressured": 4},
            "vocab_phonetics": {"liquidity": "/lɪˈkwɪdəti/"},
        }],
    )
    payload = {
        "english_text": "Market liquidity is pressured.",
        "translation_zh": "市场流动性承压。",
    }

    assert build_candidates(payload) == [
        {"word": "liquidity", "meaning_zh": "流动性", "level": "7", "phonetic": "/lɪˈkwɪdəti/"},
        {"word": "pressured", "meaning_zh": "承压", "level": "4"},
    ]

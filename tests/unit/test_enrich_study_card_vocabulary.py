"""独立学习卡生词预处理命令测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.2.0 | 2026-08-27 | Codex | 覆盖无 IPA 候选在富化阶段被排除，避免空音标成片。 |
| 1.1.0 | 2026-08-20 | Codex | 对齐离线词表实现，覆盖时间线已审核词汇的难度字段保留。 |
| 1.0.0 | 2026-08-02 | Codex | 覆盖词汇服务结果到候选词契约的转换。 |
"""

from scripts.enrich_study_card_vocabulary import build_candidates


def test_build_candidates_preserves_model_difficulty(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.enrich_study_card_vocabulary.extract_article_vocabulary",
        lambda *_args, **_kwargs: [],
    )
    payload = {
        "english_text": "Market liquidity is pressured.",
        "translation_zh": "市场流动性承压。",
        "vocabulary_candidates": [
            {"word": "liquidity", "meaning_zh": "流动性", "level": "7", "phonetic": "/lɪˈkwɪdəti/"},
            {"word": "pressured", "meaning_zh": "承压", "level": "4"},
        ],
    }

    assert build_candidates(payload, tmp_path, []) == [
        {"word": "liquidity", "meaning_zh": "流动性", "level": "7", "phonetic": "/lɪˈkwɪdəti/"},
    ]

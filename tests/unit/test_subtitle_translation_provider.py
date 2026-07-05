# -*- coding: utf-8 -*-
"""Unit tests for subtitle_translation_provider.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-05 | Codex  | 初始创建：覆盖 provider-neutral 字幕翻译候选结果应用 |
"""

import sys
from pathlib import Path

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from video_processing.utils.subtitle_translation_provider import (  # noqa: E402
    SubtitleTranslationCandidate,
    apply_translation_candidate,
)


def test_candidate_with_vocab_applies_translation_and_vocab():
    segments = [{"text": "Hello"}, {"text": "World"}]
    candidate = SubtitleTranslationCandidate(
        provider="Gemini",
        translations=["你好", "世界"],
        vocabs=[{"Hello": "你好"}, {"World": "世界"}],
        supports_vocab=True,
    )

    apply_translation_candidate(segments, candidate)

    assert segments[0]["zh_text"] == "你好"
    assert segments[0]["vocab"] == {"Hello": "你好"}
    assert segments[1]["zh_text"] == "世界"
    assert segments[1]["vocab"] == {"World": "世界"}


def test_candidate_without_vocab_clears_existing_vocab():
    segments = [{"text": "Hello", "vocab": {"old": "旧"}}]
    candidate = SubtitleTranslationCandidate(
        provider="Aliyun",
        translations=["你好"],
    )

    apply_translation_candidate(segments, candidate)

    assert segments[0]["zh_text"] == "你好"
    assert segments[0]["vocab"] == {}


def test_candidate_usability_requires_enough_translations():
    candidate = SubtitleTranslationCandidate(provider="DeepSeek", translations=["一"])

    assert candidate.is_usable_for(1)
    assert not candidate.is_usable_for(2)

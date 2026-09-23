"""真实 Chromium 验证英语封面不裁切已审校引语。

依赖：tests → cover.engine → cover.renderer；仅本地合成文案，无平台或网络。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-23 | Codex | 覆盖完整双语段落截图及不可读超长封面拒绝。 |
"""
import pytest
from cover.engine import CoverEngine


def test_complete_paragraph_renders_and_overflow_is_refused(tmp_path):
    payload = {"content_type": "ENGLISH_WORLD_SHORT", "title": "公司收购跨过障碍",
               "quote_en": "The company cleared a key hurdle in its proposed takeover after reaching a settlement with several U.S. states over antitrust concerns about the deal.",
               "quote_zh": "这家公司拟议的收购跨过了一道关键障碍。此前，公司已与美国几个州就这笔交易的反垄断问题达成和解。",
               "difficulty_tag": "A2–B1 家庭精读", "date_str": "2026.09.23", "audio_source": "测试原声",
               "vocab_items": [], "highlight_words": []}
    engine = CoverEngine()
    output = tmp_path / "complete-paragraph.jpg"
    engine.generate(payload, str(output))
    assert output.is_file()
    payload["quote_en"] *= 30
    with pytest.raises(ValueError, match="禁止裁切"):
        engine.generate(payload, str(tmp_path / "overflow.jpg"))
    assert not (tmp_path / "overflow.jpg").exists()

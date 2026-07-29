"""内容贴合封面策划的单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 覆盖财经冲击、科技与输入质量门的稳定策划输出 |
"""

from cover.creative_brief import build_cover_creative_brief, validate_cover_brief_input


def test_market_crash_takes_precedence_over_chip_topic():
    brief = build_cover_creative_brief(
        {
            "title": "466% IPO 引发全球芯片股暴跌",
            "content_hints": ["ipo", "chip", "market"],
        }
    )

    assert brief.style_id == "market_shock"
    assert brief.badge == "市场警报"
    assert brief.accent_color == "#E5484D"
    assert "ipo" in brief.visual_keywords


def test_tech_topic_uses_cool_editorial_style():
    brief = build_cover_creative_brief(
        {"title": "新一代 AI 芯片如何改变推理成本", "content_hints": ["ai", "chip"]}
    )

    assert brief.style_id == "tech_frontier"
    assert brief.badge == "前沿科技"
    assert brief.frame_tint_opacity > 0


def test_brief_input_validation_keeps_long_title_as_non_blocking_warning():
    validation = validate_cover_brief_input(
        {"title": "这是一条足够长、需要缩小标题字号但仍然允许正常生成封面的测试标题，并且不会因此阻断例行发布流程"}
    )

    assert validation.ok is True
    assert "long_title_requires_small_font" in validation.warnings
    assert "no_content_hints_used_title_fallback" in validation.warnings


def test_brief_input_validation_rejects_missing_title():
    validation = validate_cover_brief_input({"content_hints": ["market"]})

    assert validation.ok is False
    assert validation.warnings == ("missing_title",)

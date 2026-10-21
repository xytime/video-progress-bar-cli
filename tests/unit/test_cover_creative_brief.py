"""内容贴合封面策划的单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-21 | Antigravity | 验证真实摄影美学预设轮换、多候选错位及去除固定插画同质化描述 |
| 1.0.0 | 2026-07-29 | Codex | 覆盖财经冲击、科技与输入质量门的稳定策划输出 |
"""

from cover.creative_brief import (
    PHOTOGRAPHIC_STYLE_PRESETS,
    build_cover_creative_brief,
    resolve_photographic_style,
    select_photographic_style,
    validate_cover_brief_input,
)


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
    assert "真实摄影" in brief.visual_direction
    assert "Photographic style (" not in brief.visual_direction
    assert any(k in {p.preset_id for p in PHOTOGRAPHIC_STYLE_PRESETS} for k in brief.visual_keywords)


def test_resolve_style_follows_brief_and_rotates_on_retry():
    brief = build_cover_creative_brief({"title": "芯片出口管制", "content_hints": ["chip"]})
    base = resolve_photographic_style(brief.visual_keywords, "x", variant_offset=0)
    retry = resolve_photographic_style(brief.visual_keywords, "x", variant_offset=1)
    assert base.preset_id in brief.visual_keywords
    assert retry.preset_id != base.preset_id
    assert resolve_photographic_style((), "seed").preset_id == select_photographic_style("seed").preset_id


def test_photographic_style_rotates_across_topics_and_variants():
    variants = {select_photographic_style("加拿大零售地产2027展望", variant_offset=i).preset_id for i in range(3)}
    assert len(variants) == 3
    all_ids = {p.preset_id for p in PHOTOGRAPHIC_STYLE_PRESETS}
    assert variants.issubset(all_ids)


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

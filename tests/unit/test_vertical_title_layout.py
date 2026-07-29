# -*- coding: utf-8 -*-
"""竖版视频头部标题排版单测

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-29 | Codex  | 覆盖标题动态两行、强调色与 drawtext expansion 防护 |
"""

from video_processing.processors.vertical_processor import (
    TITLE_ACCENT_COLOR,
    _build_title_drawtext_filters,
    _layout_title_lines,
)


def test_layout_title_lines_keeps_percent_title_visible():
    lines, font_size, is_semantic = _layout_title_lines("466%暴涨引爆全球芯片抛售潮")

    assert lines == ["466%暴涨引爆", "全球芯片抛售潮"]
    assert font_size == 82
    assert is_semantic is False


def test_layout_title_lines_splits_semantic_title():
    lines, font_size, is_semantic = _layout_title_lines("消费信心不及预期：就业数据藏玄机")

    assert lines == ["消费信心不及预期：", "就业数据藏玄机"]
    assert font_size == 82
    assert is_semantic is True


def test_layout_title_lines_avoids_common_term_breaks():
    lines, font_size, is_semantic = _layout_title_lines("隐藏的大型科技现金流裂缝！")

    assert lines == ["隐藏的大型科技", "现金流裂缝！"]
    assert font_size == 82
    assert is_semantic is False


def test_layout_title_lines_does_not_truncate_line_that_fits():
    lines, font_size, is_semantic = _layout_title_lines("华尔街正在悄悄抛售什么！")

    assert lines == ["华尔街正在悄悄抛售什么！"]
    assert font_size == 82
    assert is_semantic is False


def test_build_title_drawtext_filters_disable_percent_expansion_and_accent_second_line():
    filters, output_label = _build_title_drawtext_filters(
        "merged",
        "466%暴涨引爆全球芯片抛售潮",
        "/missing/font.ttf",
    )

    joined = ";".join(filters)
    assert output_label == "titled"
    assert "expansion=none" in joined
    assert "466%" in joined
    assert TITLE_ACCENT_COLOR in joined

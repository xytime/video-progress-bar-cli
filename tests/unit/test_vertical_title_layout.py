# -*- coding: utf-8 -*-
"""竖版视频头部标题排版单测

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-29 | Codex  | 覆盖标题动态两行、强调色与 drawtext expansion 防护 |
| 1.0.1   | 2026-07-29 | Codex  | 覆盖竖版渲染的单线程 H.264 输入解码保护 |
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from video_processing.processors.vertical_processor import (
    TITLE_ACCENT_COLOR,
    VerticalCaptionProcessor,
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


@patch("video_processing.core.base.VideoProcessorBase._validate_input")
@patch("video_processing.processors.vertical_processor.subprocess.run")
@patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg")
def test_vertical_render_uses_single_thread_input_decode(_ffmpeg, mock_run, _validate, tmp_path):
    mock_run.side_effect = [
        MagicMock(stdout="1280x720"),
        MagicMock(stdout=""),
        MagicMock(),
    ]
    processor = VerticalCaptionProcessor(
        Path("source.mp4"), output_path=tmp_path / "output.mp4", title="466%暴涨引爆全球芯片抛售潮",
    )

    processor._burn_subtitles(tmp_path / "source.ass")

    render_command = mock_run.call_args_list[-1].args[0]
    assert render_command[:5] == ["ffmpeg", "-y", "-threads", "1", "-i"]

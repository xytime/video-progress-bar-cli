"""TDD test cases for precision video slicing engine.

# Modification History
| Version | Date       | Author                    | Description                                     |
|---------|------------|---------------------------|-------------------------------------------------|
| 1.0.0   | 2026-05-27 | Gemini_3.5_Flash_planning | Initial TDD test creation for VideoSlicer       |
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# [Gemini_3.5_Flash_planning] 校验 FFmpeg 命令行裁剪的构建逻辑是否正确

def test_slicer_build_ffmpeg_cmd():
    """验证 VideoSlicer 构建的 ffmpeg 裁剪命令格式正确"""
    from video_processing.processors.slicer import VideoSlicer
    slicer = VideoSlicer(
        input_path=Path("input.mp4"),
        output_dir=Path("output_dir")
    )
    
    # 验证生成的命令行参数
    cmd = slicer.build_trim_command(
        start_time=10.0,
        end_time=30.0,
        output_path=Path("output_dir/slice.mp4")
    )
    
    # [Gemini_3.5_Flash_planning] 断言：必须包含 -ss, -to, -c copy 等无损裁剪关键参数
    assert "-ss" in cmd
    assert "10.000" in cmd
    assert "-to" in cmd
    assert "30.000" in cmd
    assert "-c" in cmd
    assert "copy" in cmd or "copy" in cmd[cmd.index("-c")+1]

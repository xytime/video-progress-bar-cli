"""
工具函数模块
包含文件操作、视频元数据等通用工具
"""

from .file_utils import (
    ensure_directory,
    get_file_size,
    format_file_size,
    find_video_files,
    safe_remove,
)
from .time_utils import (
    time_string_to_seconds,
    seconds_to_time_string,
)
from .progress_parser import FFmpegProgressParser

__all__ = [
    "ensure_directory",
    "get_file_size",
    "format_file_size",
    "find_video_files",
    "safe_remove",
    "get_video_info",
    "get_video_resolution",
    "get_video_duration",
    "get_video_duration_ffprobe",
    "time_string_to_seconds",
    "seconds_to_time_string",
    "FFmpegProgressParser",
    "build_subprocess_env",
]


def __getattr__(name: str):
    if name in {
        "get_video_info",
        "get_video_resolution",
        "get_video_duration",
        "get_video_duration_ffprobe",
    }:
        from . import video_metadata

        return getattr(video_metadata, name)
    if name == "build_subprocess_env":
        from .subprocess_env import build_subprocess_env

        return build_subprocess_env
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


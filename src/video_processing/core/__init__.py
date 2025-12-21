"""
核心处理逻辑模块
包含基础视频处理抽象类和通用处理流程
"""

from .base import VideoProcessorBase, VideoProcessorError, VideoValidationError, VideoProcessingError

__all__ = [
    "VideoProcessorBase",
    "VideoProcessorError",
    "VideoValidationError",
    "VideoProcessingError",
]


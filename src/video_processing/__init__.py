"""
视频处理核心模块
提供视频处理的基础功能和工具
"""

__version__ = "0.1.0"


# 所有项目入口使用同一个 FFmpeg 创建守卫；第三方下载器由 venv 启动钩子覆盖。
from .core.ffmpeg_slot import install as _install_ffmpeg_slot
_install_ffmpeg_slot()

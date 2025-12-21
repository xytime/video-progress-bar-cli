"""配置管理模块"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Settings:
    """应用配置类"""
    
    # 项目根目录
    PROJECT_ROOT: Path = Path(__file__).parent.parent.parent
    
    # 默认输出目录
    DEFAULT_OUTPUT_DIR: Path = PROJECT_ROOT / "output"
    
    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: Path = PROJECT_ROOT / "logs"
    
    # 视频处理配置
    DEFAULT_VIDEO_FORMAT: str = "mp4"
    DEFAULT_VIDEO_CODEC: str = "libx264"
    DEFAULT_AUDIO_CODEC: str = "aac"
    
    # FFmpeg配置
    FFMPEG_PATH: Optional[str] = os.getenv("FFMPEG_PATH")
    
    # 默认字体路径（用于视频文字渲染）
    # macOS 常用字体: /Library/Fonts/Arial Unicode.ttf, /Library/Fonts/PingFang.ttc
    # DEFAULT_FONT_PATH: str = "/Library/Fonts/Arial Unicode.ttf"
    DEFAULT_FONT_PATH: str = "/Library/Fonts/TianYingZhang.ttf"
    
    # 进度条默认字体大小配置
    DEFAULT_BAR_FONT_SIZE: int = 28      # 底部进度条上的章节标题字号
    DEFAULT_TITLE_FONT_SIZE: int = 72    # 左上角大标题字号
    DEFAULT_BAR_HEIGHT: int = 80         # 进度条高度（像素）
    
    @classmethod
    def ensure_directories(cls) -> None:
        """确保必要的目录存在"""
        cls.DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)


# 全局配置实例
settings = Settings()


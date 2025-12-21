"""基础视频处理抽象类"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class VideoProcessorBase(ABC):
    """视频处理器基类"""
    
    def __init__(self, input_path: Path, output_path: Optional[Path] = None):
        """
        初始化视频处理器
        
        Args:
            input_path: 输入视频文件路径
            output_path: 输出视频文件路径（可选）
        """
        self.input_path = Path(input_path)
        self.output_path = Path(output_path) if output_path else None
        self._validate_input()
    
    def _validate_input(self) -> None:
        """验证输入文件"""
        if not self.input_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {self.input_path}")
        if not self.input_path.is_file():
            raise ValueError(f"输入路径不是文件: {self.input_path}")
    
    @abstractmethod
    def process(self, **kwargs) -> Path:
        """
        处理视频
        
        Args:
            **kwargs: 处理参数
            
        Returns:
            输出文件路径
        """
        pass
    
    def _ensure_output_dir(self) -> None:
        """确保输出目录存在"""
        if self.output_path:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)


class VideoProcessorError(Exception):
    """视频处理错误基类"""
    pass


class VideoValidationError(VideoProcessorError):
    """视频验证错误"""
    pass


class VideoProcessingError(VideoProcessorError):
    """视频处理错误"""
    pass


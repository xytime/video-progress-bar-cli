"""输入验证模块"""
from pathlib import Path
from typing import List, Optional
from ..core.base import VideoValidationError


# 支持的视频格式
SUPPORTED_VIDEO_FORMATS = [
    '.mp4', '.avi', '.mov', '.mkv', '.flv', 
    '.wmv', '.webm', '.m4v', '.3gp', '.ts'
]


def validate_video_file(file_path: Path) -> None:
    """
    验证视频文件
    
    Args:
        file_path: 视频文件路径
        
    Raises:
        VideoValidationError: 如果验证失败
    """
    if not file_path.exists():
        raise VideoValidationError(f"文件不存在: {file_path}")
    
    if not file_path.is_file():
        raise VideoValidationError(f"路径不是文件: {file_path}")
    
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_VIDEO_FORMATS:
        raise VideoValidationError(
            f"不支持的视频格式: {suffix}。支持的格式: {', '.join(SUPPORTED_VIDEO_FORMATS)}"
        )


def validate_output_path(output_path: Path, overwrite: bool = False) -> None:
    """
    验证输出路径
    
    Args:
        output_path: 输出文件路径
        overwrite: 是否允许覆盖已存在的文件
        
    Raises:
        VideoValidationError: 如果验证失败
    """
    if output_path.exists() and not overwrite:
        raise VideoValidationError(
            f"输出文件已存在: {output_path}。使用 overwrite=True 允许覆盖"
        )
    
    # 确保输出目录可以创建
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise VideoValidationError(f"无法创建输出目录: {e}")


def validate_resolution(width: int, height: int) -> None:
    """
    验证分辨率参数
    
    Args:
        width: 宽度
        height: 高度
        
    Raises:
        VideoValidationError: 如果验证失败
    """
    if width <= 0 or height <= 0:
        raise VideoValidationError(f"分辨率必须大于0: {width}x{height}")
    
    if width > 7680 or height > 4320:  # 8K限制
        raise VideoValidationError(f"分辨率过大: {width}x{height}")


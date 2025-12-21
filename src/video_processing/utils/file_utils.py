"""文件操作工具"""
from pathlib import Path
from typing import List, Optional
import shutil


def ensure_directory(path: Path) -> Path:
    """
    确保目录存在，如果不存在则创建
    
    Args:
        path: 目录路径
        
    Returns:
        目录路径
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_file_size(path: Path) -> int:
    """
    获取文件大小（字节）
    
    Args:
        path: 文件路径
        
    Returns:
        文件大小（字节）
    """
    return path.stat().st_size


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小
    
    Args:
        size_bytes: 文件大小（字节）
        
    Returns:
        格式化后的文件大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def find_video_files(directory: Path, extensions: Optional[List[str]] = None) -> List[Path]:
    """
    查找目录中的视频文件
    
    Args:
        directory: 目录路径
        extensions: 文件扩展名列表，默认为常见视频格式
        
    Returns:
        视频文件路径列表
    """
    if extensions is None:
        extensions = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm']
    
    video_files = []
    for ext in extensions:
        video_files.extend(directory.glob(f"*{ext}"))
        video_files.extend(directory.glob(f"*{ext.upper()}"))
    
    return sorted(video_files)


def safe_remove(path: Path) -> bool:
    """
    安全删除文件或目录
    
    Args:
        path: 要删除的路径
        
    Returns:
        是否成功删除
    """
    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        return True
    except Exception:
        return False


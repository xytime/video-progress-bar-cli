"""视频元数据工具"""
from pathlib import Path
from typing import Dict, Optional, Tuple
import subprocess
import cv2


def get_video_info(video_path: Path) -> Dict[str, any]:
    """
    获取视频基本信息
    
    Args:
        video_path: 视频文件路径
        
    Returns:
        包含视频信息的字典
    """
    cap = cv2.VideoCapture(str(video_path))
    
    if not cap.isOpened():
        raise ValueError(f"无法打开视频文件: {video_path}")
    
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0
        codec = int(cap.get(cv2.CAP_PROP_FOURCC))
        codec_str = "".join([chr((codec >> 8 * i) & 0xFF) for i in range(4)])
        
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "frame_count": frame_count,
            "duration": duration,
            "codec": codec_str,
            "file_size": video_path.stat().st_size,
        }
    finally:
        cap.release()


def get_video_resolution(video_path: Path) -> Tuple[int, int]:
    """
    获取视频分辨率
    
    Args:
        video_path: 视频文件路径
        
    Returns:
        (宽度, 高度) 元组
    """
    info = get_video_info(video_path)
    return (info["width"], info["height"])


def get_video_duration(video_path: Path) -> float:
    """
    获取视频时长（秒）
    使用 OpenCV 方法
    
    Args:
        video_path: 视频文件路径
        
    Returns:
        视频时长（秒）
    """
    info = get_video_info(video_path)
    return info["duration"]


def get_video_resolution_ffprobe(video_path: Path, ffprobe_path: Optional[str] = None) -> Tuple[int, int]:
    """
    使用 ffprobe 获取视频分辨率
    此方法比 OpenCV 更可靠，无需解码视频
    
    Args:
        video_path: 视频文件路径
        ffprobe_path: ffprobe 可执行文件路径（可选）
        
    Returns:
        (宽度, 高度) 元组
        
    Raises:
        ValueError: 如果无法获取视频分辨率
    """
    ffprobe_cmd = ffprobe_path or "ffprobe"
    
    cmd = [
        ffprobe_cmd,
        '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height',
        '-of', 'csv=p=0',
        str(video_path)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        output = result.stdout.strip()
        if not output:
            raise ValueError(f"ffprobe 未返回分辨率信息: {video_path}")
        parts = output.split(',')
        if len(parts) != 2:
            raise ValueError(f"无法解析分辨率: {output}")
        return (int(parts[0]), int(parts[1]))
    except subprocess.CalledProcessError as e:
        raise ValueError(f"ffprobe 执行失败: {e.stderr}")
    except FileNotFoundError:
        raise FileNotFoundError("未找到 ffprobe")


def get_video_duration_ffprobe(video_path: Path, ffprobe_path: Optional[str] = None) -> float:
    """
    使用 ffprobe 获取视频总时长（秒）
    此方法比 OpenCV 更准确，特别是对于某些视频格式
    
    Args:
        video_path: 视频文件路径
        ffprobe_path: ffprobe 可执行文件路径（可选，默认使用系统 PATH 中的 ffprobe）
        
    Returns:
        视频时长（秒）
        
    Raises:
        ValueError: 如果无法获取视频时长
        FileNotFoundError: 如果 ffprobe 未找到
    """
    ffprobe_cmd = ffprobe_path or "ffprobe"
    
    cmd = [
        ffprobe_cmd,
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        duration_str = result.stdout.strip()
        if not duration_str:
            raise ValueError(f"ffprobe 未返回时长信息: {video_path}")
        return float(duration_str)
    except subprocess.CalledProcessError as e:
        raise ValueError(f"ffprobe 执行失败: {e.stderr}")
    except ValueError as e:
        if "could not convert" in str(e).lower():
            raise ValueError(f"无法解析视频时长，请检查文件路径或 FFmpeg 安装: {video_path}")
        raise
    except FileNotFoundError:
        raise FileNotFoundError(
            "未找到 ffprobe。请确保 FFmpeg 已安装并在系统 PATH 中，"
            "或通过 ffprobe_path 参数指定路径"
        )


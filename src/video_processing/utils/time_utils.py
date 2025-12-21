"""时间工具函数"""
from typing import Union


def time_string_to_seconds(time_str: str) -> float:
    """
    将时间字符串转换为秒数
    
    支持格式：
    - "MM:SS" (例如 "01:30" = 90秒)
    - "HH:MM:SS" (例如 "01:05:30" = 3930秒)
    - 纯数字字符串 (例如 "90" = 90秒)
    
    Args:
        time_str: 时间字符串
        
    Returns:
        秒数（浮点数）
        
    Raises:
        ValueError: 如果时间格式无效
    """
    time_str = time_str.strip()
    
    # 如果是纯数字，直接返回
    try:
        return float(time_str)
    except ValueError:
        pass
    
    # 解析 MM:SS 或 HH:MM:SS 格式
    parts = time_str.split(':')
    
    if len(parts) == 2:
        # MM:SS 格式
        minutes, seconds = parts
        try:
            return float(minutes) * 60 + float(seconds)
        except ValueError:
            raise ValueError(f"无效的时间格式: {time_str}")
    
    elif len(parts) == 3:
        # HH:MM:SS 格式
        hours, minutes, seconds = parts
        try:
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        except ValueError:
            raise ValueError(f"无效的时间格式: {time_str}")
    
    else:
        raise ValueError(f"无效的时间格式: {time_str}，支持格式: MM:SS 或 HH:MM:SS")


def seconds_to_time_string(seconds: float, include_hours: bool = False) -> str:
    """
    将秒数转换为时间字符串
    
    Args:
        seconds: 秒数
        include_hours: 是否包含小时（True: HH:MM:SS，False: MM:SS）
        
    Returns:
        时间字符串 (MM:SS 或 HH:MM:SS)
    """
    total_seconds = int(seconds)
    
    if include_hours:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes:02d}:{secs:02d}"


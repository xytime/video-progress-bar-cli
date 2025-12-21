"""FFmpeg 进度解析工具"""
import re
from typing import Optional, Callable
from datetime import datetime, timedelta


class FFmpegProgressParser:
    """解析 FFmpeg stderr 输出中的进度信息"""
    
    # FFmpeg 进度信息格式：time=HH:MM:SS.ms 或 time=SS.ms
    TIME_PATTERN = re.compile(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})')
    TIME_PATTERN_SHORT = re.compile(r'time=(\d+)\.(\d{2})')
    
    # 帧数信息：frame=12345
    FRAME_PATTERN = re.compile(r'frame=\s*(\d+)')
    
    # 比特率信息：bitrate=1234.5kbits/s
    BITRATE_PATTERN = re.compile(r'bitrate=\s*([\d.]+)\s*(kbits/s|Mbits/s)')
    
    # 速度信息：speed=1.23x
    SPEED_PATTERN = re.compile(r'speed=\s*([\d.]+)x')
    
    def __init__(self, total_duration: float):
        """
        初始化进度解析器
        
        Args:
            total_duration: 视频总时长（秒）
        """
        self.total_duration = total_duration
        self.last_progress = 0.0
        self.last_time = 0.0
        self.start_time = datetime.now()
        self.last_update_time = datetime.now()
        self.current_speed = 1.0
        self.processed_frames = 0
    
    def parse_line(self, line: str) -> Optional[float]:
        """
        解析一行 FFmpeg 输出，提取进度信息
        
        Args:
            line: FFmpeg stderr 输出的一行
            
        Returns:
            进度百分比（0.0-1.0），如果无法解析则返回 None
        """
        # 尝试解析时间信息
        time_seconds = self._parse_time(line)
        
        if time_seconds is not None:
            # 计算进度百分比
            progress = min(time_seconds / self.total_duration, 1.0)
            
            # 更新速度信息
            self._update_speed(time_seconds, progress)
            
            # 解析其他信息
            self._parse_other_info(line)
            
            self.last_progress = progress
            self.last_time = time_seconds
            
            return progress
        
        return None
    
    def _parse_time(self, line: str) -> Optional[float]:
        """解析时间信息"""
        # 尝试匹配 HH:MM:SS.ms 格式
        match = self.TIME_PATTERN.search(line)
        if match:
            hours, minutes, seconds, centiseconds = map(int, match.groups())
            total_seconds = hours * 3600 + minutes * 60 + seconds + centiseconds / 100.0
            return total_seconds
        
        # 尝试匹配 SS.ms 格式（短格式）
        match = self.TIME_PATTERN_SHORT.search(line)
        if match:
            seconds, centiseconds = map(int, match.groups())
            total_seconds = seconds + centiseconds / 100.0
            return total_seconds
        
        return None
    
    def _parse_other_info(self, line: str) -> None:
        """解析其他信息（帧数、速度等）"""
        # 解析帧数
        frame_match = self.FRAME_PATTERN.search(line)
        if frame_match:
            self.processed_frames = int(frame_match.group(1))
        
        # 解析速度
        speed_match = self.SPEED_PATTERN.search(line)
        if speed_match:
            self.current_speed = float(speed_match.group(1))
    
    def _update_speed(self, current_time: float, progress: float) -> None:
        """更新处理速度"""
        now = datetime.now()
        time_delta = (now - self.last_update_time).total_seconds()
        
        if time_delta > 0.5:  # 每0.5秒更新一次速度
            time_progress = current_time - self.last_time
            if time_progress > 0:
                # 计算实际处理速度（基于时间进度）
                actual_speed = time_progress / time_delta
                # 平滑处理速度
                self.current_speed = 0.7 * self.current_speed + 0.3 * actual_speed
                self.last_update_time = now
    
    def get_eta(self) -> Optional[timedelta]:
        """
        获取预计剩余时间
        
        Returns:
            预计剩余时间，如果无法计算则返回 None
        """
        if self.current_speed <= 0 or self.last_progress <= 0:
            return None
        
        remaining_progress = 1.0 - self.last_progress
        if remaining_progress <= 0:
            return timedelta(0)
        
        # 基于当前速度计算剩余时间
        remaining_time_seconds = (self.total_duration - self.last_time) / self.current_speed
        
        return timedelta(seconds=max(0, remaining_time_seconds))
    
    def get_elapsed_time(self) -> timedelta:
        """获取已用时间"""
        return datetime.now() - self.start_time
    
    def get_speed(self) -> float:
        """获取当前处理速度（倍数，1.0 = 实时）"""
        return self.current_speed


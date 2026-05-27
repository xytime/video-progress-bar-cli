"""高精度无损视频切片处理器 (Video Slicer)

利用 FFmpeg 的 Stream Copy 机制，实现毫秒级响应的视频分段裁剪。

# Modification History
| Version | Date       | Author                    | Description                                     |
|---------|------------|---------------------------|-------------------------------------------------|
| 1.0.0   | 2026-05-27 | Gemini_3.5_Flash_planning | Initial video slicer implementation            |
"""

import logging
import subprocess
from pathlib import Path
from typing import List
import imageio_ffmpeg

logger = logging.getLogger(__name__)

class VideoSlicer:
    """负责执行无损/重编码高精度裁剪 FFmpeg 编排"""

    def __init__(self, input_path: Path, output_dir: Path):
        self.input_path = input_path
        self.output_dir = output_dir
        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    def build_trim_command(self, start_time: float, end_time: float, output_path: Path) -> List[str]:
        """构建 FFmpeg 流复制（Stream Copy）裁剪命令行。
        
        [Gemini_3.5_Flash_planning] 注意：为了实现超快流复制，我们使用 -c copy 选项。
        为了解决 keyframe 寻址画面卡顿或黑屏，采用 -ss 放在 -i 前置快速寻址方案。
        """
        cmd = [
            self.ffmpeg_exe, "-y",
            "-ss", f"{start_time:.3f}",
            "-to", f"{end_time:.3f}",
            "-i", str(self.input_path),
            "-c", "copy",
            str(output_path)
        ]
        return cmd

    def slice_video(self, start_time: float, end_time: float, output_path: Path) -> bool:
        """执行无损裁剪操作"""
        cmd = self.build_trim_command(start_time, end_time, output_path)
        logger.info(f"Running video slice: {' '.join(cmd)}")
        
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"Slicing complete: {output_path.name}")
            return True
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr if e.stderr else "Unknown ffmpeg error"
            logger.error(f"Ffmpeg slicing failed for {self.input_path.name}: {err_msg}")
            return False

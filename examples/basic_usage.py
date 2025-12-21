"""
基础使用示例
展示如何使用视频处理库的基本功能
"""

from pathlib import Path
from video_processing.utils import get_video_info, format_file_size
from video_processing.validators import validate_video_file


def example_get_video_info(video_path: str):
    """获取视频信息示例"""
    video_file = Path(video_path)
    
    # 验证视频文件
    try:
        validate_video_file(video_file)
        print(f"✓ 视频文件验证通过: {video_file}")
    except Exception as e:
        print(f"✗ 验证失败: {e}")
        return
    
    # 获取视频信息
    try:
        info = get_video_info(video_file)
        print(f"\n视频信息:")
        print(f"  分辨率: {info['width']}x{info['height']}")
        print(f"  帧率: {info['fps']:.2f} fps")
        print(f"  时长: {info['duration']:.2f} 秒")
        print(f"  总帧数: {info['frame_count']}")
        print(f"  编码: {info['codec']}")
        print(f"  文件大小: {format_file_size(info['file_size'])}")
    except Exception as e:
        print(f"✗ 获取视频信息失败: {e}")


if __name__ == "__main__":
    # 示例：获取视频信息
    # 请替换为实际的视频文件路径
    example_video = "path/to/your/video.mp4"
    
    if Path(example_video).exists():
        example_get_video_info(example_video)
    else:
        print("请修改 example_video 变量为实际的视频文件路径")


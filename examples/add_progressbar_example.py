"""
添加进度条功能使用示例
展示如何使用 ProgressBarProcessor 为视频添加进度条和章节分割线
"""

from pathlib import Path
from video_processing.processors.progress_bar import ProgressBarProcessor


def example_simple_progressbar():
    """简单模式：只添加时间点分割线"""
    
    input_video = Path("path/to/your/input.mp4")
    output_video = Path("path/to/your/output_with_bar.mp4")
    
    # 章节时间点（秒）
    chapters = [30, 75, 120]
    
    processor = ProgressBarProcessor(
        input_path=input_video,
        output_path=output_video,
        chapters=chapters,
        bar_height=15,
        bar_color="red",
        bg_color="black@0.5",
    )
    
    try:
        result_path = processor.process()
        print(f"✓ 处理完成！输出文件: {result_path}")
    except Exception as e:
        print(f"✗ 处理失败: {e}")


def example_advanced_progressbar():
    """高级模式：添加章节标题（支持中文）"""
    
    input_video = Path("path/to/your/input.mp4")
    output_video = Path("path/to/your/output_with_advanced_bar.mp4")
    
    # 章节数据（包含时间点和标题）
    chapters = [
        {"time": "00:00", "title": "教程介绍"},
        {"time": "00:30", "title": "绘制进度条"},
        {"time": "01:15", "title": "制作进度条动画"},
        {"time": "02:45", "title": "添加刻度和文字"},
        {"time": "03:50", "title": "透明度动画"},
        {"time": "04:30", "title": "教程预告及结尾"}
    ]
    
    # 使用默认字体（/Library/Fonts/Arial Unicode.ttf）
    # 或指定自定义字体路径
    # font_path = "/System/Library/Fonts/PingFang.ttc"
    
    processor = ProgressBarProcessor(
        input_path=input_video,
        output_path=output_video,
        chapters=chapters,
        bar_height=80,              # 高度要足够容纳文字
        bar_color="#00AAAA@0.5",     # 进度条填充色（半透明青色）
        bg_color="#003366@0.6",      # 背景色（半透明深蓝色）
        divider_width=2,
        divider_color="white@0.8",
        # font_path 不指定时使用默认字体: /Library/Fonts/Arial Unicode.ttf
        font_size=24,
        text_color="white",
    )
    
    try:
        result_path = processor.process()
        print(f"✓ 处理完成！输出文件: {result_path}")
    except Exception as e:
        print(f"✗ 处理失败: {e}")


def example_custom_style():
    """自定义样式示例"""
    
    input_video = Path("path/to/your/input.mp4")
    
    chapters = [
        {"time": "00:00", "title": "开始"},
        {"time": "01:00", "title": "中间"},
        {"time": "02:00", "title": "结束"}
    ]
    
    processor = ProgressBarProcessor(
        input_path=input_video,
        chapters=chapters,
        bar_height=100,
        bar_color="#FF0000@0.5",      # 红色半透明
        bg_color="#000000@0.6",       # 黑色半透明
        # 使用默认字体，或指定自定义字体
        # font_path="/System/Library/Fonts/PingFang.ttc",
        font_size=30,
        text_color="yellow",
    )
    
    # 带进度显示的处理
    def progress_callback(progress: float):
        percent = int(progress * 100)
        print(f"\r处理进度: {percent}%", end='', flush=True)
    
    result_path = processor.process(progress_callback=progress_callback)
    print()  # 换行
    print(f"✓ 处理完成！输出文件: {result_path}")


if __name__ == "__main__":
    print("请修改示例中的视频文件路径和字体路径后运行")
    # example_simple_progressbar()
    # example_advanced_progressbar()
    # example_custom_style()

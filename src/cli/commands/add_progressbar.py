"""添加进度条命令"""
import click
from pathlib import Path
from typing import Optional, List, Dict
import sys

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = None

from video_processing.processors.progress_bar import ProgressBarProcessor
from video_processing.validators import validate_video_file
from video_processing.utils.time_utils import time_string_to_seconds


@click.command(name="add-progressbar")
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o", "--output",
    type=click.Path(path_type=Path),
    help="输出视频文件路径（默认：输入文件同目录，文件名添加 '_with_bar' 后缀）"
)
@click.option(
    "-c", "--chapter-time",
    multiple=True,
    type=str,
    help="章节时间点，支持格式：秒数（如 30）或时间字符串（如 00:30 或 01:05:30）。"
         "可多次使用，例如：-c 00:00 -c 00:30 -c 01:20"
)
@click.option(
    "-t", "--chapter-title",
    multiple=True,
    type=str,
    help="章节标题（与 -c 配对使用）。例如：-c 00:00 -t '教程介绍' -c 00:30 -t '章节一'"
)
@click.option(
    "--bar-height",
    type=int,
    default=80,
    show_default=True,
    help="进度条高度（像素），建议 80 以上以容纳文字"
)
@click.option(
    "--color-scheme",
    type=click.Choice(["default", "cinema_gold", "tech_dark", "sport_red", "minimal_ink","neon_cyber","forest_zen","industrial_alert","nordic_frost","retro_vapor"], case_sensitive=False),
    help="内置配色方案（选择后将覆盖 --bar-color、--bg-color 和 --text-color）:\n"
         "  - default: 经典商务蓝（适合教程/企业，推荐）\n"
         "  - cinema_gold: 电影质感金（高端，适合纪录片/Vlog）\n"
         "  - tech_dark: 科技深青（Solarized 风格，不刺眼）\n"
         "  - sport_red: 活力橙红（醒目，适合运动/快节奏）\n"
         "  - minimal_ink: 极简墨黑（高对比，适合艺术风格）"
         "  - neon_cyber: 赛博霓虹（适合游戏/电竞/夜景）\n"
         "  - forest_zen: 森林禅意（适合风景/露营/Vlog）\n"
         "  - industrial_alert: 工业警示（适合硬核科技/开箱/评测）\n"
         "  - nordic_frost: 北欧冰蓝（适合极简/家居/雪景）\n"
         "  - retro_vapor: 复古蒸汽（适合复古风/音乐/胶片感）\n"
)
@click.option(
    "--bar-color",
    type=str,
    help="进度条填充颜色（FFmpeg 颜色格式，支持透明度。如果指定了 --color-scheme 则会被覆盖）"
)
@click.option(
    "--bg-color",
    type=str,
    help="背景条颜色（支持透明度。如果指定了 --color-scheme 则会被覆盖）"
)
@click.option(
    "--divider-width",
    type=int,
    default=2,
    show_default=True,
    help="章节分割线宽度（像素）"
)
@click.option(
    "--divider-color",
    type=str,
    help="分割线颜色（支持透明度。如果指定了 --color-scheme 则会被覆盖）"
)
@click.option(
    "--font-path",
    type=click.Path(path_type=Path),
    default="/Library/Fonts/Arial Unicode.ttf",
    show_default=True,
    help="字体文件路径（用于显示中文标题）。"
         "默认: /Library/Fonts/Arial Unicode.ttf"
)
@click.option(
    "--font-size",
    type=int,
    default=28,
    show_default=True,
    help="字体大小"
)
@click.option(
    "--text-color",
    type=str,
    default=None,
    help="文字颜色（章节标题）。如果使用配色方案，将自动使用方案中的建议颜色；否则默认为 white"
)
@click.option(
    "--show-time/--no-show-time",
    default=False,
    show_default=True,
    help="是否在进度条上显示当前播放时间（默认禁用，转义问题待修复）"
)
@click.option(
    "--time-font-size",
    type=int,
    help="时间文字大小（默认比章节标题小 4）"
)
@click.option(
    "--time-color",
    type=str,
    help="时间文字颜色（默认与章节标题颜色相同）"
)
@click.option(
    "--title-position",
    type=click.Choice(["top_left", "top_right", "bottom_left", "bottom_right"], case_sensitive=False),
    default="top_left",
    show_default=True,
    help="标题位置（top_left/top_right/bottom_left/bottom_right）"
)
@click.option(
    "--title-x-offset",
    type=int,
    default=30,
    show_default=True,
    help="标题 X 偏移（像素）"
)
@click.option(
    "--title-y-offset",
    type=int,
    default=30,
    show_default=True,
    help="标题 Y 偏移（像素）"
)
@click.option(
    "--title-font-size",
    type=int,
    help="标题字体大小（默认至少 48，或比底部标题大 20，取较大值）"
)
@click.option(
    "--title-color",
    type=str,
    help="标题文字颜色（默认 white）"
)
@click.option(
    "--title-bg-color",
    type=str,
    default="black@0.6",
    show_default=True,
    help="标题背景框颜色（支持透明度，如 'black@0.6'）"
)
@click.option(
    "--title-bg-border",
    type=int,
    default=4,
    show_default=True,
    help="标题背景框边框宽度（像素）"
)
@click.option(
    "--title-fade-duration",
    type=float,
    default=0.5,
    show_default=True,
    help="标题淡入淡出持续时间（秒）"
)
@click.option(
    "--ffmpeg-path",
    type=str,
    help="ffmpeg 可执行文件路径（默认使用系统 PATH 中的 ffmpeg）"
)
@click.option(
    "--ffprobe-path",
    type=str,
    help="ffprobe 可执行文件路径（默认使用系统 PATH 中的 ffprobe）"
)
@click.option(
    "--threads",
    type=int,
    help="FFmpeg 线程数（默认自动选择，建议不超过 CPU 核心数）"
)
@click.option(
    "--preset",
    type=click.Choice(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"], case_sensitive=False),
    default="medium",
    show_default=True,
    help="编码预设（fast=快速，medium=平衡，slow=高质量）"
)
@click.option(
    "--enable-hwaccel",
    is_flag=True,
    help="启用硬件加速（如果系统支持）"
)
@click.option(
    "--no-progress",
    is_flag=True,
    help="禁用进度条显示"
)
def add_progressbar(
    input_file: Path,
    output: Optional[Path],
    chapter_time: tuple,
    chapter_title: tuple,
    bar_height: int,
    color_scheme: Optional[str],
    bar_color: Optional[str],
    bg_color: Optional[str],
    divider_width: int,
    divider_color: Optional[str],
    font_path: Optional[Path],
    font_size: int,
    text_color: str,
    show_time: bool,
    time_font_size: Optional[int],
    time_color: Optional[str],
    title_position: str,
    title_x_offset: int,
    title_y_offset: int,
    title_font_size: Optional[int],
    title_color: Optional[str],
    title_bg_color: str,
    title_bg_border: int,
    title_fade_duration: float,
    ffmpeg_path: Optional[str],
    ffprobe_path: Optional[str],
    threads: Optional[int],
    preset: str,
    enable_hwaccel: bool,
    no_progress: bool,
):
    """
    为视频添加进度条和章节分割线（支持章节标题和中文显示）
    
    \b
    示例:
        # 简单模式：只添加时间点分割线
        video-process add-progressbar input.mp4 -c 30 -c 75 -c 120
        
        # 高级模式：添加章节标题（使用默认字体）
        video-process add-progressbar input.mp4 \\
            -c 00:00 -t "教程介绍" \\
            -c 00:30 -t "章节一" \\
            -c 01:20 -t "章节二"
        
        # 使用自定义字体
        video-process add-progressbar input.mp4 \\
            -c 00:00 -t "教程介绍" \\
            -c 00:30 -t "章节一" \\
            --font-path /System/Library/Fonts/PingFang.ttc
        
        # 自定义样式
        video-process add-progressbar input.mp4 \\
            -c 00:00 -t "开始" -c 01:00 -t "结束" \\
            --font-path /System/Library/Fonts/PingFang.ttc \\
            --bar-color "#FF0000@0.5" --bg-color "#000000@0.6" \\
            --bar-height 100 --font-size 30
    """
    try:
        # 验证输入文件
        validate_video_file(input_file)
        
        # 处理章节数据
        chapters = _build_chapters_list(chapter_time, chapter_title)
        
        # 验证配色方案参数
        if color_scheme:
            valid_schemes = ["default", "cinema_gold", "tech_dark", "sport_red", "minimal_ink","neon_cyber","forest_zen","industrial_alert","nordic_frost","retro_vapor"]
            if color_scheme.lower() not in [s.lower() for s in valid_schemes]:
                raise click.BadParameter(
                    f"无效的配色方案: {color_scheme}。"
                    f"可选值: {', '.join(valid_schemes)}",
                    param_hint="--color-scheme"
                )
            # 标准化配色方案名称（转换为小写，然后匹配）
            color_scheme = next(s for s in valid_schemes if s.lower() == color_scheme.lower())
            click.echo(
                click.style(
                    f"使用配色方案: {color_scheme}",
                    fg="cyan"
                )
            )
        
        # 检查字体文件是否存在
        has_titles = any(chap.get("title") for chap in chapters)
        if font_path and not font_path.exists():
            click.echo(
                click.style(
                    f"警告: 字体文件不存在: {font_path}。"
                    "如果使用标题功能，请确保字体文件路径正确。",
                    fg="yellow"
                ),
                err=True
            )
        
        # 创建处理器
        processor = ProgressBarProcessor(
            input_path=input_file,
            output_path=output,
            chapters=chapters,
            bar_height=bar_height,
            color_scheme=color_scheme,
            bar_color=bar_color,
            bg_color=bg_color,
            divider_width=divider_width,
            divider_color=divider_color,
            font_path=str(font_path) if font_path else None,
            font_size=font_size,
            text_color=text_color,
            show_time=show_time,
            time_font_size=time_font_size,
            time_color=time_color,
            title_position=title_position,
            title_x_offset=title_x_offset,
            title_y_offset=title_y_offset,
            title_font_size=title_font_size,
            title_color=title_color,
            title_bg_color=title_bg_color,
            title_bg_border=title_bg_border,
            title_fade_duration=title_fade_duration,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            threads=threads,
            preset=preset,
            enable_hwaccel=enable_hwaccel,
        )
        
        # 处理视频（带进度显示）
        click.echo(f"正在处理视频: {input_file}")
        if has_titles and font_path:
            click.echo("正在渲染视频，这需要一些时间（因为要处理文字和透明度）...")
        
        # 设置进度回调
        if not no_progress and HAS_TQDM:
            # 使用 tqdm 显示进度条
            with tqdm(total=100, unit='%', desc='处理进度', ncols=80, file=sys.stderr) as pbar:
                def progress_callback(progress: float):
                    pbar.update(int(progress * 100) - pbar.n)
                
                output_path = processor.process(progress_callback=progress_callback)
        elif not no_progress:
            # 使用简单的文本进度显示
            def progress_callback(progress: float):
                percent = int(progress * 100)
                click.echo(f"\r进度: {percent}%", nl=False, err=True)
            
            output_path = processor.process(progress_callback=progress_callback)
            click.echo()  # 换行
        else:
            # 不使用进度条
            output_path = processor.process()
        
        click.echo(click.style(f"✓ 完成！文件已保存为: {output_path}", fg="green"))
        
    except Exception as e:
        click.echo(click.style(f"✗ 错误: {str(e)}", fg="red"), err=True)
        raise click.Abort()


def _build_chapters_list(
    chapter_times: tuple,
    chapter_titles: tuple
) -> List[Dict[str, Optional[str]]]:
    """
    构建章节数据列表
    
    Args:
        chapter_times: 章节时间点元组
        chapter_titles: 章节标题元组
        
    Returns:
        章节数据列表，格式：[{"time": float, "title": Optional[str]}]
    """
    chapters = []
    
    # 如果只有时间点，没有标题
    if chapter_times and not chapter_titles:
        for time_str in chapter_times:
            try:
                time_seconds = time_string_to_seconds(time_str)
                chapters.append({"time": time_seconds, "title": None})
            except ValueError as e:
                raise click.BadParameter(f"无效的时间格式: {time_str} ({e})")
    
    # 如果有时间点和标题（需要配对）
    elif chapter_times and chapter_titles:
        if len(chapter_times) != len(chapter_titles):
            raise click.BadParameter(
                f"章节时间点数量 ({len(chapter_times)}) 与标题数量 ({len(chapter_titles)}) 不匹配。"
                "请确保每个时间点都有对应的标题，或都不提供标题。"
            )
        
        for time_str, title in zip(chapter_times, chapter_titles):
            try:
                time_seconds = time_string_to_seconds(time_str)
                chapters.append({"time": time_seconds, "title": title})
            except ValueError as e:
                raise click.BadParameter(f"无效的时间格式: {time_str} ({e})")
    
    # 按时间排序
    chapters.sort(key=lambda x: x["time"])
    
    return chapters

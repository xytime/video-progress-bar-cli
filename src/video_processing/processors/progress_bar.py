"""进度条处理器 - 为视频添加进度条和章节分割线"""
from pathlib import Path
from typing import List, Optional, Union, Dict, Callable
import subprocess
import logging
import os
import sys

from ..core.base import VideoProcessorBase, VideoProcessingError
from ..validators import validate_video_file, validate_output_path
from ..utils.video_metadata import get_video_duration_ffprobe, get_video_resolution_ffprobe
from ..utils.time_utils import time_string_to_seconds, seconds_to_time_string
from ..utils.progress_parser import FFmpegProgressParser

logger = logging.getLogger(__name__)


def convert_color_to_ffmpeg_format(color_str: str) -> str:
    """
    将颜色格式转换为 FFmpeg 支持的格式
    
    FFmpeg 支持多种颜色格式：
    - 命名颜色：black, white, red 等
    - 十六进制：0xRRGGBB 或 #RRGGBB
    - 带透明度：0xRRGGBBAA 或 #RRGGBB@alpha
    
    此函数确保颜色格式正确，特别是处理透明度格式。
    
    Args:
        color_str: 颜色字符串，支持格式：
            - 命名颜色：black, white, red
            - 十六进制：0xRRGGBB, #RRGGBB
            - 带透明度：0xRRGGBBAA, #RRGGBB@alpha, white@0.6, black@0.5
    
    Returns:
        FFmpeg 支持的颜色格式字符串
    """
    if not color_str:
        return "black"
    
    # 处理带透明度的命名颜色（如 white@0.6, black@0.5）
    if "@" in color_str:
        parts = color_str.split("@")
        if len(parts) == 2:
            base_color = parts[0].strip()  # white, black, #RRGGBB 等
            alpha = float(parts[1])  # 0.0-1.0
            
            # 如果是命名颜色，需要转换为 RGB 值
            named_colors = {
                "black": (0, 0, 0),
                "white": (255, 255, 255),
                "red": (255, 0, 0),
                "green": (0, 255, 0),
                "blue": (0, 0, 255),
                "yellow": (255, 255, 0),
                "cyan": (0, 255, 255),
                "magenta": (255, 0, 255),
            }
            
            if base_color in named_colors:
                # 命名颜色带透明度，转换为 0xRRGGBBAA
                r, g, b = named_colors[base_color]
                alpha_hex = int(alpha * 255)
                return f"0x{r:02X}{g:02X}{b:02X}{alpha_hex:02X}"
            elif base_color.startswith("#"):
                # #RRGGBB@alpha 格式
                hex_color = base_color
                alpha_hex = int(alpha * 255)
                rgb = hex_color[1:]  # RRGGBB
                return f"0x{rgb}{alpha_hex:02X}"
    
    # 如果已经是命名颜色（无透明度），直接返回
    if color_str in ["black", "white", "red", "green", "blue", "yellow", "cyan", "magenta"]:
        return color_str
    
    # 如果已经是 0x 格式，直接返回
    if color_str.startswith("0x"):
        return color_str
    
    # 如果是 #RRGGBB 格式（无透明度），转换为 0x 格式
    if color_str.startswith("#") and "@" not in color_str:
        return f"0x{color_str[1:]}"
    
    # 其他情况直接返回（可能是其他 FFmpeg 支持的格式）
    return color_str

# 内置配色方案 (优化版：确保文字在底座和进度条上均有良好对比度)
COLOR_SCHEMES = {
    # 1. 经典商务蓝 (最稳妥，适合教程/企业)
    # 底座：半透明黑 | 进度：深天蓝 | 文字：白
    "default": {
        "bg_color": "black@0.6",
        "bar_color": "#007AFF@0.9",  # iOS 风格蓝，对比度好
        "divider_color": "white@0.6",
        "text_color": "white",
    },
    
    # 2. 电影质感金 (高端，适合纪录片/Vlog)
    # 底座：深灰 | 进度：暗金色 | 文字：白 (金色不能太亮，否则吃字)
    "cinema_gold": {
        "bg_color": "#1A1A1A@0.7",
        "bar_color": "#D4AF37@0.9",  # 香槟金/暗金
        "divider_color": "white@0.4",
        "text_color": "white",
    },
    
    # 3. 科技深青 (改进版，不刺眼)
    # 底座：深青黑 | 进度：柔和青色 | 文字：白
    "tech_dark": {
        "bg_color": "#002B36@0.8",   # Solarized Dark 风格背景
        "bar_color": "#2AA198@0.9",  # 柔和青色
        "divider_color": "#93A1A1@0.5",
        "text_color": "white",
    },
    
    # 4. 活力橙红 (醒目，适合运动/快节奏)
    # 底座：黑 | 进度：朱砂红 | 文字：白
    "sport_red": {
        "bg_color": "black@0.6",
        "bar_color": "#E53935@0.9",  # 稍微压暗的红，非刺眼纯红
        "divider_color": "white@0.7",
        "text_color": "white",
    },
    
    # 5. 极简墨黑 (高对比，适合艺术风格)
    # 底座：浅灰 | 进度：纯黑 | 文字：白 (配合文字描边使用)
    "minimal_ink": {
        "bg_color": "white@0.3",     # 浅色底座
        "bar_color": "black@0.8",    # 黑色进度条
        "divider_color": "black@0.5",
        "text_color": "white",       # 配合描边使用
    },
    # 6. 赛博霓虹 (适合游戏/电竞/夜景)
    # 底座：深紫黑 | 进度：激光粉 | 文字：白
    "neon_cyber": {
        "bg_color": "#18002E@0.8",   # 深邃的紫色背景
        "bar_color": "#FF00FF@0.9",  # 强烈的洋红色/激光粉
        "divider_color": "#00FFFF@0.6", # 青色分割线，形成红蓝对撞
        "text_color": "white",
    },

    # 7. 森林禅意 (适合风景/露营/Vlog)
    # 底座：深墨绿 | 进度：嫩叶绿 | 文字：白
    "forest_zen": {
        "bg_color": "#1B261B@0.7",   # 接近黑色的深绿
        "bar_color": "#66BB6A@0.9",  # 清新的草绿色
        "divider_color": "white@0.4",
        "text_color": "white",
    },

    # 8. 工业警示 (适合硬核科技/开箱/评测)
    # 底座：纯黑 | 进度：警示黄 | 文字：白 (阴影必须重)
    "industrial_alert": {
        "bg_color": "black@0.7",
        "bar_color": "#FFD700@1.0",  # 纯正的黄金色/黄色
        "divider_color": "black@0.5", # 黑色分割线，模拟斑马线效果
        "text_color": "white",
    },

    # 9. 北欧冰蓝 (适合极简/家居/雪景)
    # 底座：岩石灰 | 进度：冰川蓝 | 文字：白
    "nordic_frost": {
        "bg_color": "#2E3440@0.8",   # 诺德配色中的深灰
        "bar_color": "#88C0D0@0.9",  # 柔和的冰蓝色
        "divider_color": "white@0.5",
        "text_color": "white",
    },

    # 10. 复古蒸汽 (适合复古风/音乐/胶片感)
    # 底座：深靛蓝 | 进度：日落紫 | 文字：白
    "retro_vapor": {
        "bg_color": "#240046@0.8",   # 靛青色
        "bar_color": "#9D4EDD@0.9",  # 亮紫色
        "divider_color": "#E0AAFF@0.6", # 浅紫分割线
        "text_color": "white",
    }
}


class ProgressBarProcessor(VideoProcessorBase):
    """为视频添加进度条和章节分割线的处理器（支持章节标题和中文显示）"""
    
    def __init__(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        chapters: Optional[Union[List[float], List[Dict[str, Union[str, float]]]]] = None,
        bar_height: int = 80,
        bar_color: Optional[str] = None,  # 进度颜色（如果为 None，将使用 color_scheme 或默认值）
        bg_color: Optional[str] = None,   # 底座颜色（如果为 None，将使用 color_scheme 或默认值）
        divider_width: int = 2,
        divider_color: Optional[str] = None,  # 分割线颜色（如果为 None，将使用 color_scheme 或默认值）
        color_scheme: Optional[str] = None,  # 配色方案（tech_glow/teal_orange/minimal_white/default）
        font_path: Optional[str] = None,  # None 时使用默认字体
        font_size: int = 28,
        text_color: Optional[str] = None,  # 文字颜色（如果为 None，将使用 color_scheme 或默认值 white）
        show_time: bool = False,  # 是否显示当前时间（暂时禁用，转义问题待修复）
        time_font_size: Optional[int] = None,  # 时间文字大小（默认比章节标题小）
        time_color: Optional[str] = None,  # 时间文字颜色（默认与 text_color 相同）
        title_position: str = "top_left",  # 标题位置（top_left/top_right/bottom_left/bottom_right）
        title_x_offset: int = 30,  # 标题 X 偏移（像素）
        title_y_offset: int = 30,  # 标题 Y 偏移（像素）
        title_font_size: Optional[int] = None,  # 标题字体大小（默认比章节标题大，例如 32）
        title_color: Optional[str] = None,  # 标题文字颜色（默认 white）
        title_bg_color: str = "black@0.6",  # 标题背景框颜色
        title_bg_border: int = 4,  # 标题背景框边框宽度
        title_fade_duration: float = 0.5,  # 淡入淡出持续时间（秒）
        ffmpeg_path: Optional[str] = None,
        ffprobe_path: Optional[str] = None,
        threads: Optional[int] = None,
        preset: str = "medium",
        enable_hwaccel: bool = False,
    ):
        """
        初始化进度条处理器
        
        Args:
            input_path: 输入视频文件路径
            output_path: 输出视频文件路径（可选，默认在输入文件同目录）
            chapters: 章节数据，支持两种格式：
                - 简单格式：时间点列表（秒），例如 [30, 75, 120]
                - 高级格式：章节字典列表，例如 [
                    {"time": "00:00", "title": "教程介绍"},
                    {"time": "00:30", "title": "章节一"}
                  ]
            bar_height: 进度条高度（像素），建议 80 以上以容纳文字
            bar_color: 进度条填充颜色（支持透明度，默认 '#00CCFF@0.9'，不透明度 0.9 更清晰）
            bg_color: 背景条颜色（支持透明度，如果为 None 将使用 color_scheme 或默认值）
            divider_width: 章节分割线宽度（像素）
            divider_color: 分割线颜色（支持透明度，如果为 None 将使用 color_scheme 或默认值）
            color_scheme: 配色方案（可选：'tech_glow'/'teal_orange'/'minimal_white'/'default'）
                - tech_glow: 科技荧光风（同色系高亮，推荐）
                - teal_orange: 电影撞色风（对比色，醒目）
                - minimal_white: 极简纯白（干净高级）
                - default: 默认配色（black@0.5 / #00CCFF@0.9）
            font_path: 字体文件路径（用于显示中文，默认: /Library/Fonts/TianYingZhang.ttf）
            font_size: 字体大小（章节标题）
            text_color: 文字颜色（章节标题）
            show_time: 是否在进度条上显示当前播放时间（默认 False，暂时禁用）
            time_font_size: 时间文字大小（默认比 font_size 小 4）
            time_color: 时间文字颜色（默认与 text_color 相同）
            title_position: 标题位置（top_left/top_right/bottom_left/bottom_right，默认 top_left）
            title_x_offset: 标题 X 偏移（像素，默认 30）
            title_y_offset: 标题 Y 偏移（像素，默认 30）
            title_font_size: 标题字体大小（默认至少 48，或 font_size + 20，取较大值）
            title_color: 标题文字颜色（默认 white）
            title_bg_color: 标题背景框颜色（默认 black@0.6）
            title_bg_border: 标题背景框边框宽度（像素，默认 4）
            title_fade_duration: 淡入淡出持续时间（秒，默认 0.5）
            ffmpeg_path: ffmpeg 可执行文件路径（可选）
            ffprobe_path: ffprobe 可执行文件路径（可选）
            threads: FFmpeg 线程数（可选，默认自动）
            preset: 编码预设（fast/medium/slow，默认 medium）
            enable_hwaccel: 是否启用硬件加速（默认 False）
        """
        super().__init__(input_path, output_path)
        
        # 如果没有指定输出路径，在输入文件同目录生成
        if self.output_path is None:
            self.output_path = self.input_path.parent / f"{self.input_path.stem}_with_bar{self.input_path.suffix}"
        
        # 处理章节数据
        self.chapters_data = self._normalize_chapters(chapters)
        
        # 处理配色方案
        # 添加调试日志
        logger.debug(f"配色方案参数: color_scheme={color_scheme}, bar_color={bar_color}, bg_color={bg_color}, divider_color={divider_color}")
        
        # 如果指定了 color_scheme，使用方案中的颜色（除非用户明确指定了颜色）
        if color_scheme:
            # 用户明确指定了配色方案
            logger.info(f"使用配色方案: {color_scheme}")
            if color_scheme not in COLOR_SCHEMES:
                logger.warning(f"未知的配色方案: {color_scheme}，使用默认方案")
                scheme = "default"
            else:
                scheme = color_scheme
            
            scheme_colors = COLOR_SCHEMES[scheme]
            logger.debug(f"配色方案 '{scheme}' 的颜色: bg={scheme_colors['bg_color']}, bar={scheme_colors['bar_color']}, divider={scheme_colors['divider_color']}, text={scheme_colors.get('text_color', 'white')}")
            
            # 应用配色方案（如果用户没有明确指定颜色）
            self.bg_color = bg_color if bg_color is not None else scheme_colors["bg_color"]
            self.bar_color = bar_color if bar_color is not None else scheme_colors["bar_color"]
            self.divider_color = divider_color if divider_color is not None else scheme_colors["divider_color"]
            # 从方案中获取文字颜色
            scheme_text_color = scheme_colors.get("text_color", "white")
            
            # 记录最终使用的颜色
            if bg_color is not None:
                logger.debug(f"使用自定义背景颜色: {bg_color} (覆盖配色方案)")
            if bar_color is not None:
                logger.debug(f"使用自定义进度颜色: {bar_color} (覆盖配色方案)")
            if divider_color is not None:
                logger.debug(f"使用自定义分割线颜色: {divider_color} (覆盖配色方案)")
        else:
            # 没有指定配色方案，使用用户指定的颜色或默认值
            logger.debug("未指定配色方案，使用默认配色或用户自定义颜色")
            self.bg_color = bg_color if bg_color is not None else COLOR_SCHEMES["default"]["bg_color"]
            self.bar_color = bar_color if bar_color is not None else COLOR_SCHEMES["default"]["bar_color"]
            self.divider_color = divider_color if divider_color is not None else COLOR_SCHEMES["default"]["divider_color"]
            scheme_text_color = COLOR_SCHEMES["default"].get("text_color", "white")
        
        # 记录最终使用的颜色值
        logger.info(f"最终颜色配置: 背景={self.bg_color}, 进度={self.bar_color}, 分割线={self.divider_color}")
        
        # 处理文字颜色：用户显式指定优先，否则使用配色方案的建议值
        if text_color is not None:
            self.text_color = text_color
            logger.debug(f"使用用户指定的文字颜色: {text_color}")
        else:
            self.text_color = scheme_text_color
            logger.debug(f"使用配色方案的文字颜色: {scheme_text_color}")
        
        self.bar_height = bar_height
        self.divider_width = divider_width
        self.font_size = font_size
        # self.text_color 已在上面的配色方案处理中设置
        self.show_time = show_time
        self.time_font_size = time_font_size if time_font_size is not None else max(16, font_size - 4)
        self.time_color = time_color if time_color is not None else text_color
        
        # 左上角标题相关参数
        self.title_position = title_position
        self.title_x_offset = title_x_offset
        self.title_y_offset = title_y_offset
        # 左上角标题默认字号：配置文件中设置，或者 max(48, font_size + 20)
        # 注意：title_font_size 会在配置加载后重新计算（如果用户未指定）
        self._user_title_font_size = title_font_size  # 保存用户指定的值
        self.title_color = title_color if title_color is not None else "white"
        self.title_bg_color = title_bg_color
        self.title_bg_border = title_bg_border
        self.title_fade_duration = title_fade_duration
        
        # 尝试从 config 获取配置，如果导入失败则使用默认值
        try:
            from config.settings import settings as config_settings
            default_ffmpeg = config_settings.FFMPEG_PATH
            default_font = config_settings.DEFAULT_FONT_PATH
            default_title_font_size = getattr(config_settings, 'DEFAULT_TITLE_FONT_SIZE', 48)
        except ImportError:
            default_ffmpeg = None
            default_font = "/Library/Fonts/Arial Unicode.ttf"
            default_title_font_size = 48
        
        self.ffmpeg_path = ffmpeg_path or default_ffmpeg or "ffmpeg"
        self.ffprobe_path = ffprobe_path or "ffprobe"
        self.threads = threads
        self.preset = preset
        self.enable_hwaccel = enable_hwaccel
        
        # 如果没有指定字体路径，使用默认值
        if font_path is None:
            font_path = default_font
        self.font_path = font_path
        
        # 计算左上角标题字号（在配置加载后）
        if self._user_title_font_size is not None:
            self.title_font_size = self._user_title_font_size
        else:
            self.title_font_size = max(default_title_font_size, font_size + 20)
        
        # 验证输出路径
        validate_output_path(self.output_path, overwrite=True)
        
        # 如果有章节标题，验证字体文件（如果指定了字体路径）
        if self._has_titles() and self.font_path:
            if not os.path.exists(self.font_path):
                import warnings
                warnings.warn(
                    f"字体文件不存在: {self.font_path}。"
                    "标题可能无法正常显示。请确保字体文件路径正确。",
                    UserWarning
                )
    
    def _normalize_chapters(
        self, 
        chapters: Optional[Union[List[float], List[Dict[str, Union[str, float]]]]]
    ) -> List[Dict[str, Union[str, float]]]:
        """
        标准化章节数据格式
        
        Args:
            chapters: 章节数据（简单格式或高级格式）
            
        Returns:
            标准化的章节数据列表，格式：[{"time": float, "title": Optional[str]}]
        """
        if not chapters:
            return []
        
        normalized = []
        
        for item in chapters:
            if isinstance(item, (int, float)):
                # 简单格式：只有时间点
                normalized.append({"time": float(item), "title": None})
            elif isinstance(item, dict):
                # 高级格式：包含时间和标题
                time_val = item.get("time")
                title = item.get("title")
                
                # 转换时间字符串为秒数
                if isinstance(time_val, str):
                    time_seconds = time_string_to_seconds(time_val)
                else:
                    time_seconds = float(time_val)
                
                normalized.append({"time": time_seconds, "title": title})
            else:
                raise ValueError(f"无效的章节数据格式: {item}")
        
        # 按时间排序
        normalized.sort(key=lambda x: x["time"])
        
        return normalized
    
    def _has_titles(self) -> bool:
        """检查是否有章节标题"""
        return any(chap.get("title") for chap in self.chapters_data)
    
    def _truncate_text_by_width(self, text: str, max_width_px: float, font_size: int) -> str:
        """
        根据可用宽度截断文本（直接截断，不添加省略号）
        
        Args:
            text: 原始文本
            max_width_px: 最大可用宽度（像素）
            font_size: 字体大小
            
        Returns:
            截断后的文本（如果超出宽度，直接截断）
        """
        if not text:
            return text
        
        # 估算字符宽度：
        # - 中文字符：通常接近 font_size（方形字符）
        # - 英文字符：约为 font_size * 0.5（窄字符）
        # 为了安全，我们使用更保守的估算：中文字符 = font_size，英文 = font_size * 0.5
        
        # 如果可用宽度太小，直接返回空字符串
        if max_width_px < font_size * 0.5:
            return ""
        
        # 估算文本宽度
        estimated_width = 0
        truncated_text = ""
        
        for char in text:
            # 判断是否为中文字符（包括中文标点）
            if '\u4e00' <= char <= '\u9fff' or '\u3000' <= char <= '\u303f' or '\uff00' <= char <= '\uffef':
                char_width = font_size  # 中文字符宽度
            else:
                char_width = font_size * 0.5  # 英文字符宽度
            
            if estimated_width + char_width <= max_width_px:
                truncated_text += char
                estimated_width += char_width
            else:
                # 超出宽度，直接截断并返回
                return truncated_text
        
        # 如果文本完全在可用宽度内，直接返回
        return text
    
    def process(self, progress_callback: Optional[Callable[[float], None]] = None, **kwargs) -> Path:
        """
        处理视频，添加进度条和章节分割线
        
        Args:
            progress_callback: 进度回调函数，参数为 0.0-1.0 的进度值
            **kwargs: 额外参数（未使用）
            
        Returns:
            输出文件路径
            
        Raises:
            VideoProcessingError: 如果处理失败
        """
        try:
            # 获取视频时长
            logger.info(f"获取视频时长: {self.input_path}")
            duration = get_video_duration_ffprobe(self.input_path, self.ffprobe_path)
            logger.info(f"视频时长: {duration:.2f} 秒")
            
            # 获取视频分辨率（用于生成进度条 overlay）
            logger.info(f"获取视频分辨率: {self.input_path}")
            video_width, video_height = get_video_resolution_ffprobe(self.input_path, self.ffprobe_path)
            logger.info(f"视频分辨率: {video_width}x{video_height}")
            
            # 构建 FFmpeg filter_complex 字符串（使用滑入法实现动态进度条）
            filter_str = self._build_filter_complex(duration, video_width, video_height)
            
            # 构建 FFmpeg 命令
            cmd = self._build_ffmpeg_command(filter_str, video_width, video_height, duration)
            
            # 执行处理（支持进度反馈）
            logger.info("开始处理视频...")
            logger.info(f"使用的颜色: 背景={self.bg_color} (FFmpeg格式: {convert_color_to_ffmpeg_format(self.bg_color)}), 进度={self.bar_color} (FFmpeg格式: {convert_color_to_ffmpeg_format(self.bar_color)})")
            logger.debug(f"执行命令: {' '.join(cmd)}")
            logger.debug(f"滤镜字符串: {filter_str[:200]}...")
            
            # 使用 Popen 实时读取输出以获取进度
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                bufsize=1,  # 行缓冲
                universal_newlines=True
            )
            
            # 创建进度解析器
            progress_parser = FFmpegProgressParser(duration)
            stderr_lines = []
            
            # 实时读取 stderr 输出
            try:
                while True:
                    line = process.stderr.readline()
                    if not line:
                        break
                    
                    stderr_lines.append(line)
                    
                    # 解析进度信息
                    progress = progress_parser.parse_line(line)
                    if progress is not None and progress_callback:
                        try:
                            progress_callback(progress)
                        except Exception as e:
                            logger.warning(f"进度回调函数执行失败: {e}")
                
                # 等待进程完成
                return_code = process.wait()
                
                if return_code != 0:
                    stderr_output = ''.join(stderr_lines)
                    raise VideoProcessingError(
                        f"FFmpeg 处理失败 (返回码: {return_code}):\n{stderr_output}"
                    )
                
            except Exception as e:
                # 如果出错，尝试终止进程
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    try:
                        process.kill()
                    except:
                        pass
                raise
            
            logger.info(f"处理完成！文件已保存为: {self.output_path}")
            return self.output_path
            
        except Exception as e:
            if isinstance(e, VideoProcessingError):
                raise
            raise VideoProcessingError(f"处理视频时发生错误: {str(e)}") from e
    
    def _build_filter_complex(self, duration: float, video_width: int, video_height: int) -> str:
        """
        构建 FFmpeg filter_complex 字符串（使用"滑入法"实现动态进度条）
        
        滑入法原理：
        1. 生成一个与屏幕等宽的实心颜色条作为进度条
        2. 初始状态下，将其放在屏幕最左侧之外（x = -width）
        3. 随着时间推移，让它向右滑动到 x = 0
        4. 因为是纯色条，"向右滑动"在视觉上看起来和"向右生长"是一模一样的
        
        Args:
            duration: 视频时长（秒）
            video_width: 视频宽度
            video_height: 视频高度
            
        Returns:
            filter_complex 字符串
        """
        # 转换颜色格式为 FFmpeg 兼容格式
        bg_color_ffmpeg = convert_color_to_ffmpeg_format(self.bg_color)
        bar_color_ffmpeg = convert_color_to_ffmpeg_format(self.bar_color)
        divider_color_ffmpeg = convert_color_to_ffmpeg_format(self.divider_color)
        
        # 记录实际使用的颜色值（用于调试）
        logger.debug(f"颜色格式转换: bg={self.bg_color} -> {bg_color_ffmpeg}, bar={self.bar_color} -> {bar_color_ffmpeg}, divider={self.divider_color} -> {divider_color_ffmpeg}")
        
        # ====================================================
        # 构建 filter_complex 图
        # ====================================================
        # 输入:
        #   [0:v] - 原始视频
        #   [1:v] - 进度条颜色源（纯色矩形，与屏幕等宽）
        # 
        # 处理流程:
        #   1. 在原始视频上绘制背景底座 -> [bg]
        #   2. 使用 overlay 将进度条颜色源以滑入方式叠加 -> [progress]
        #   3. 在 [progress] 上绘制分割线、章节标题等
        # ====================================================
        
        filter_parts = []
        
        # 1. 在原始视频上绘制背景条（底座）
        filter_parts.append(
            f"[0:v]drawbox=y=ih-{self.bar_height}:color={bg_color_ffmpeg}:"
            f"width=iw:height={self.bar_height}:thickness=fill[bg]"
        )
        
        # 2. 使用"滑入法"叠加动态进度条
        # overlay 的 x 参数支持动态表达式！
        # x = (t/duration - 1) * video_width
        #   当 t=0 时，x = -video_width（完全在左侧外，不可见）
        #   当 t=duration 时，x = 0（完全显示）
        # y = H - bar_height（放在底部）
        slide_x_expr = f"(t/{duration}-1)*{video_width}"
        filter_parts.append(
            f"[bg][1:v]overlay=x='{slide_x_expr}':y=H-{self.bar_height}:shortest=1[progress]"
        )
        
        # 后续滤镜都在 [progress] 上操作
        current_label = "progress"
        filter_index = 0
        
        # 收集需要应用在 [progress] 输出上的后续滤镜（链式连接）
        post_filters = []
        
        # 3. 绘制章节分割线
        for i, chapter in enumerate(self.chapters_data):
            start_time = chapter["time"]
            
            # 安全检查：防止时间超出视频长度
            if start_time >= duration:
                continue
                
            # 计算关键百分比位置
            start_pct = round(start_time / duration, 6)
            
            # 绘制分割线（跳过第一个0秒的）
            if start_time > 0.5:
                post_filters.append(
                    f"drawbox=x=iw*{start_pct}:y=ih-{self.bar_height}:"
                    f"w={self.divider_width}:h={self.bar_height}:color={divider_color_ffmpeg}:thickness=fill"
                )
        
        # 4. 在底部进度条上绘制章节标题（自动截断以避免重叠）
        for i, chapter in enumerate(self.chapters_data):
            start_time = chapter["time"]
            title = chapter.get("title")
            
            if not title or not self.font_path:
                continue
            
            # 确定当前章节的结束时间
            if i + 1 < len(self.chapters_data):
                end_time = self.chapters_data[i + 1]["time"]
            else:
                end_time = duration
            
            # 安全检查
            if start_time >= duration:
                continue
            end_time = min(end_time, duration)
            
            # 计算关键百分比位置
            start_pct = round(start_time / duration, 6)
            end_pct = round(end_time / duration, 6)
            center_pct = round((start_pct + end_pct) / 2, 6)
            
            # 计算章节段落的可用宽度（像素）
            # 段落宽度 = (end_pct - start_pct) * video_width
            # 留出 10% 的边距，避免文字贴边
            segment_width_px = (end_pct - start_pct) * video_width * 0.9
            
            # 根据可用宽度截断标题
            truncated_title = self._truncate_text_by_width(title, segment_width_px, self.font_size)
            
            # 如果截断后为空，跳过绘制
            if not truncated_title:
                continue
            
            # 转义标题中的特殊字符
            escaped_title = truncated_title.replace(":", "\\:").replace("'", "'\\''").replace("[", "\\[").replace("]", "\\]")
            escaped_font_path = str(self.font_path).replace("\\", "/").replace(":", "\\:")
            
            # 格式化百分比字符串
            center_pct_str = f"{center_pct:.6f}".rstrip('0').rstrip('.')
            if center_pct_str.startswith('.'):
                center_pct_str = '0' + center_pct_str
            if not center_pct_str:
                center_pct_str = '0'
            
            # 计算文字位置
            text_x_expr = f"(w*{center_pct_str})-(tw/2)"
            text_y_expr = f"h-({self.bar_height}/2)-(th/3)"
            
            # 底部章节标题（带描边提升可读性）
            post_filters.append(
                f"drawtext=fontfile='{escaped_font_path}':"
                f"text='{escaped_title}':"
                f"fontcolor={self.text_color}:fontsize={self.font_size}:"
                f"x='{text_x_expr}':y='{text_y_expr}':"
                f"shadowcolor=black@0.7:shadowx=2:shadowy=2"
            )
        
        # 5. 在左上角显示当前章节标题（带淡入淡出效果）
        if self.font_path and self._has_titles():
            escaped_font_path = str(self.font_path).replace("\\", "/").replace(":", "\\:")
            
            # 计算标题位置（支持四个角落）
            if self.title_position == "top_left":
                title_x_expr = str(self.title_x_offset)
                title_y_expr = str(self.title_y_offset)
            elif self.title_position == "top_right":
                title_x_expr = f"w-tw-{self.title_x_offset}"
                title_y_expr = str(self.title_y_offset)
            elif self.title_position == "bottom_left":
                title_x_expr = str(self.title_x_offset)
                # 底部位置：确保标题在进度条底座上方
                # 底座上沿位置 = h - bar_height
                # 标题底部位置 = h - bar_height - title_y_offset
                # drawtext 的 y 是基线位置，需要减去文字高度 th
                title_y_expr = f"h-{self.bar_height}-{self.title_y_offset}-th"
            elif self.title_position == "bottom_right":
                title_x_expr = f"w-tw-{self.title_x_offset}"
                title_y_expr = f"h-{self.bar_height}-{self.title_y_offset}-th"
            else:
                # 向后兼容：默认使用 top_left
                title_x_expr = str(self.title_x_offset)
                title_y_expr = str(self.title_y_offset)
            
            for i, chapter in enumerate(self.chapters_data):
                start_time = chapter["time"]
                title = chapter.get("title")
                
                if not title:
                    continue
                
                # 确定结束时间
                if i + 1 < len(self.chapters_data):
                    end_time = self.chapters_data[i + 1]["time"]
                else:
                    end_time = duration
                
                if start_time >= duration:
                    continue
                end_time = min(end_time, duration)
                
                # 淡入淡出区间
                fade_half = self.title_fade_duration / 2
                fade_start = max(0, start_time - fade_half)
                fade_end = min(duration, end_time + fade_half)
                
                escaped_title = title.replace(":", "\\:").replace("'", "'\\''").replace("[", "\\[").replace("]", "\\]")
                
                enable_expr = f"between(t,{fade_start:.3f},{fade_end:.3f})"
                
                # 构建 alpha 表达式
                fade_in_duration = start_time - fade_start if fade_start < start_time else 0
                fade_out_duration = fade_end - end_time if end_time < fade_end else 0
                
                alpha_expr = "0"
                if fade_out_duration > 0:
                    fade_out_expr = f"1-(t-{end_time:.3f})/{fade_out_duration:.3f}"
                    alpha_expr = f"if(between(t,{end_time:.3f},{fade_end:.3f}),{fade_out_expr},{alpha_expr})"
                alpha_expr = f"if(between(t,{start_time:.3f},{end_time:.3f}),1,{alpha_expr})"
                if fade_in_duration > 0:
                    fade_in_expr = f"(t-{fade_start:.3f})/{fade_in_duration:.3f}"
                    alpha_expr = f"if(between(t,{fade_start:.3f},{start_time:.3f}),{fade_in_expr},{alpha_expr})"
                
                # 为 x 和 y 表达式添加引号（如果包含运算符）
                x_expr_quoted = f"'{title_x_expr}'" if any(op in title_x_expr for op in ['-', '+', '*', '/', '(', ')']) else title_x_expr
                y_expr_quoted = f"'{title_y_expr}'" if any(op in title_y_expr for op in ['-', '+', '*', '/', '(', ')']) else title_y_expr
                
                post_filters.append(
                    f"drawtext=fontfile='{escaped_font_path}':"
                    f"text='{escaped_title}':"
                    f"fontcolor={self.title_color}:fontsize={self.title_font_size}:"
                    f"x={x_expr_quoted}:y={y_expr_quoted}:"
                    f"box=1:boxcolor={self.title_bg_color}:boxborderw={self.title_bg_border}:"
                    f"enable='{enable_expr}':alpha='{alpha_expr}'"
                )
        
        # 构建完整的 filter_complex 字符串
        # 将后续滤镜链接到 [progress] 输出上
        if post_filters:
            # 将后续滤镜链式连接：[progress]filter1,filter2,...[out]
            post_chain = ",".join(post_filters)
            filter_parts.append(f"[progress]{post_chain}[out]")
        else:
            # 没有后续滤镜时，直接将 [progress] 重命名为 [out]
            # 修改最后一个 filter，把输出标签改为 [out]
            filter_parts[-1] = filter_parts[-1].replace("[progress]", "[out]")
        
        return ";".join(filter_parts)
    
    def _build_ffmpeg_command(self, filter_complex_str: str, video_width: int, video_height: int, duration: float) -> List[str]:
        """
        构建 FFmpeg 命令（使用 filter_complex 和多输入实现动态进度条）
        
        Args:
            filter_complex_str: filter_complex 字符串
            video_width: 视频宽度
            video_height: 视频高度
            duration: 视频时长
            
        Returns:
            FFmpeg 命令列表
        """
        # 转换进度条颜色格式（用于 color 滤镜）
        # color 滤镜需要使用 #RRGGBB 格式（不带 alpha）
        # alpha 通过 format=rgba 和后续滤镜处理
        bar_color_for_color_filter = self.bar_color
        if "@" in bar_color_for_color_filter:
            # 移除 alpha 部分，只保留颜色
            bar_color_for_color_filter = bar_color_for_color_filter.split("@")[0]
        
        # 确保颜色格式正确
        if bar_color_for_color_filter.startswith("0x"):
            # 转换 0xRRGGBB 为 #RRGGBB
            bar_color_for_color_filter = "#" + bar_color_for_color_filter[2:]
        elif not bar_color_for_color_filter.startswith("#"):
            # 如果是命名颜色，保持原样
            pass
        
        # 获取帧率（默认 30）
        fps = 30
        
        cmd = [
            self.ffmpeg_path,
            '-v', 'info',
            '-stats',
        ]
        
        # 硬件加速
        if self.enable_hwaccel:
            cmd.extend(['-hwaccel', 'auto'])
        
        # 输入 0: 原始视频
        cmd.extend(['-i', str(self.input_path)])
        
        # 输入 1: 进度条颜色源（纯色矩形，与视频等宽）
        # 使用 color 滤镜生成一个与视频等宽、高度为 bar_height 的纯色矩形
        # 注意：color 滤镜的 c 参数使用 #RRGGBB 格式（不带 alpha）
        # format=rgba 确保支持透明度
        color_input = f"color=c={bar_color_for_color_filter}:s={video_width}x{self.bar_height}:d={duration}:r={fps},format=rgba"
        cmd.extend(['-f', 'lavfi', '-i', color_input])
        
        # 使用 filter_complex（而非 -vf）
        cmd.extend(['-filter_complex', filter_complex_str])
        
        # 映射输出
        cmd.extend(['-map', '[out]'])
        
        # 映射音频（如果存在）
        cmd.extend(['-map', '0:a?'])
        
        # 编码设置
        cmd.extend([
            '-c:a', 'copy',
            '-c:v', 'libx264',
            '-preset', self.preset,
        ])
        
        # 线程数控制
        if self.threads:
            cmd.extend(['-threads', str(self.threads)])
        else:
            import multiprocessing
            cpu_count = multiprocessing.cpu_count()
            optimal_threads = min(cpu_count, 8)
            cmd.extend(['-threads', str(optimal_threads)])
        
        # 优化输出
        cmd.extend([
            '-movflags', '+faststart',
            '-y',
            str(self.output_path)
        ])
        
        return cmd

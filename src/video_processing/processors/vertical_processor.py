# -*- coding: utf-8 -*-
"""竖屏视频处理器 (9:16) — 提供三段式布局、字幕与配音生成

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking | 初始创建，支持三段式与边缘配音/本地配音 |
| 1.6.0   | 2026-07-17 | Codex | 移除 CosyVoice；高品质 TTS 改由本地 IndexTTS，并迁移历史 cosyvoice 任务 |
| 1.1.1   | 2026-05-28 | Gemini_3.5_Flash_planning | 新增 mute_original 参数支持，允许将原视频静音只保留 TTS 音轨，标注 # [Gemini_3.5_Flash_planning] |
| 1.2.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 新增 tts_volume 和 tts_speech_rate 支持，并在分段混合前引入 atempo 自动加速防重叠安全阀机制，标注 # [Gemini_3.5_Flash_planning] |
| 1.3.0   | 2026-05-28 | Gemini_2.5_Pro_planning  | TTSEngine 默认 fallback voice 改为 "auto"，自动从精选播音音色池随机选取，标注 # [Gemini_2.5_Pro_planning] |
| 1.4.0   | 2026-05-28 | Gemini_3.5_Flash_planning | [已废弃] 非中文视频自动开启 TTS 配音逻辑（不符合默认行为需求，已在 1.5.0 移除） |
| 1.5.0   | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 移除"非中文视频自动开启 TTS"行为：TTS 默认关闭，只有用户通过 --tts-cosy / --tts-real 参数，或 Telegram /tts 命令明确指定时才启用 |
| 1.6.0   | 2026-06-07 | Gemini_3.5_Flash_planning | Handle audio-less videos gracefully during vertical subtitle burn-in. |
| 1.7.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 竖屏视频输入时将字幕起始 y 坐标调整为 1400，防止遮挡画面中心内容，标注 # [Gemini_3.5_Flash_planning] |
| 1.8.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 双语字幕中英文顺序互换，英文设为金色（Gold），字号与中文接近一致（0.82倍），标注 # [Gemini_3.5_Flash_planning] |
| 1.9.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 优化竖屏字幕样式，支持半透明黑色背景底框，增强复杂背景下的对比度与可读性，标注 # [Gemini_3.5_Flash_planning] |
| 1.10.0  | 2026-06-07 | Gemini_3.5_Flash_planning | 修复英文单词中插入折行标签的bug，引入标签敏感的折行函数 tag_aware_wrap，标注 # [Gemini_3.5_Flash_planning] |
| 1.11.0  | 2026-06-07 | Gemini_3.5_Flash_planning | 采用 Option 5（贴地固定脚栏）独立双样式双卡排版，将单词注释区与字幕区剥离，标注 # [Gemini_3.5_Flash_planning] |
| 1.12.0  | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | Code review 修复：将 textwrap 移至顶层 import；删除重复的 config 读取；移除未使用的 cyan_c 变量；修复 vocab_wrap 宽度因子 |
| 1.13.0  | 2026-06-07 | Gemini_3.5_Flash_High_planning | 整合词汇释义区至字幕下方并加分割线，支持英文默认金色与单词多色高亮和下划线，标注 # [Gemini_3.5_Flash_High_planning] |
| 1.14.0  | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | 将释义区分离为独立灰色背景 GlossaryCard 事件，紧随字幕卡片正下方；字体改为楷体 (Kaiti SC)，标注 # [Claude_Sonnet_4.6_Thinking_planning] |
| 1.15.0  | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | 字幕字体升级为 PingFang SC（Apple 官方 Pan-CJK 字体，行业最佳实践）；修复 GlossaryCard 灰色蒙版为可辨识度更高的中灰，标注 # [Claude_Sonnet_4.6_Thinking_planning] |
| 1.16.0  | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | 修复乱码：字幕字体改为 Hiragino Sans GB（冬青黑体简体中文，fc-list 可发现），注释卡片字体改为 Songti SC（宋体-简，表感辷线字体，同样 fc-list 可发现），标注 # [Claude_Sonnet_4.6_Thinking_planning] |
| 1.17.0  | 2026-06-08 | Gemini_3.5_Flash_planning | 彻底解决英文溢出，美化英文字体为 Georgia 衬线体并缩小字号，修复释义灰色卡片不显示及黑边问题，高亮色统一为青绿并加下划线，标注 # [Gemini_3.5_Flash_planning] |
| 1.18.0  | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 实现双语字幕动态字体缩放：每段字幕均在固定可用高度内自适应缩小字号，消除任意行数溢出风险 |
| 2.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | [架构解耦] 将字幕样式/ASS标签/字号缩放/高亮/折行完全委托给 SubtitleStylist，_generate_ass_file 仅负责时间轴与文件写入 |
| 2.1.0   | 2026-06-08 | Gemini_3.5_Flash_planning | 横屏输入视频使用动态计算的字幕起始 Y 坐标，修复 SyntaxError 并优化排版，标注 # [Gemini_3.5_Flash_planning] |
| 2.2.0   | 2026-06-08 | Gemini_3.5_Flash_planning | 将释义区字号比例下调至 0.42 倍以显主次，并标注 # [Gemini_3.5_Flash_planning] |
| 2.3.0   | 2026-06-08 | Claude_Sonnet_4.6_planning | 竖屏模式下释义区最下沿上移半字高度 (≈17px)，同步缩减主字幕最大高度防重叠 |
| 2.4.0   | 2026-06-08 | Gemini_3.5_Flash_planning | 自动从 .info.json 加载视频标题，标注 # [Gemini_3.5_Flash_planning] |
| 2.5.0   | 2026-06-25 | Claude_Opus_4.8 | 新增 source_date 参数：字幕烧录后叠加左上角「源视频发布日期」毛玻璃戳(date_stamp 模块)，覆盖源水印；遮罩/边框输入索引按音轨情况动态计算，渲染后清理临时资源 |
| 2.6.0   | 2026-07-29 | Codex | 优化竖版头部标题：Noto/思源系字体优先、动态两行排版、强调色与 drawtext expansion 防护 |
| 2.6.1   | 2026-07-29 | Codex | 竖版渲染固定单线程 H.264 输入解码，避免部分 60fps 源在多线程解码时偶发丢宏块 |
| 2.6.2   | 2026-08-27 | Codex | 透传字幕阶段心跳回调至通用字幕处理器 |
"""
import logging
import subprocess
import textwrap
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import pysubs2

from .caption_processor import AutoCaptionProcessor, CAPTION_STYLES, VideoProcessingError
from ..utils.layout import VerticalLayout
from ..core.tts_engine import TTSEngine, TTSProvider
from ..core.audio_mixer import AudioMixer

import re

from ..utils.subtitle_stylist import SubtitleStylist, SubtitleLayout

def strip_trailing_punctuation(text: str) -> str:
    """[Gemini_3.5_Flash_planning] 去除段落末尾的半角/全角标点符号，防止折行时标点符号单独占一行"""
    if not text:
        return text
    return re.sub(r'[\.,\?!\;:\"\'。，？！；：”、\s]+$', '', text)

# [Claude_Sonnet_4.6_Thinking_planning] 竖屏模式字幕区最大允许高度（像素）
# subtitle_top_y=1000，GlossaryCard 顶部≈1532，留 32px 安全边，可用高度 = 1532-32-1000 = 500px
SUBTITLE_ZONE_MAX_HEIGHT = 500
# 动态缩放时字号最小值（防止字幕过小无法阅读）
SUBTITLE_MIN_EN_SIZE = 28
SUBTITLE_MIN_ZH_SIZE = 32

# [Gemini_3.5_Flash_planning] 统一使用单一强调青绿色 (BGR 格式，对应 HTML 中的 --en-accent #6FD3C7)，且在样式上更显 premium
VOCAB_COLORS = ["&HC7D36F&"]

TITLE_FONT_CANDIDATES = (
    "~/Library/Fonts/NotoSerifSC-Bold.otf",
    "~/Library/Fonts/NotoSerifSC-Bold.ttf",
    "/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)
TITLE_BASE_FONT_SIZE = 82
TITLE_MIN_FONT_SIZE = 66
TITLE_MAX_WIDTH = 940
TITLE_ZONE_HEIGHT = 350
TITLE_LINE_GAP = 8
TITLE_PRIMARY_COLOR = "#FFFFFF"
TITLE_ACCENT_COLOR = "#FFE36E"
TITLE_PROTECTED_TERMS = (
    "AI",
    "IPO",
    "人工智能",
    "华尔街",
    "现金流",
    "科技",
    "芯片",
    "消费",
    "信心",
    "就业",
    "数据",
    "老师",
    "关键",
    "影子",
    "全球",
    "抛售",
    "悄悄",
)


def apply_word_highlights(text: str, word_colors: Dict[str, str]) -> str:
    """# [Gemini_3.5_Flash_High_planning] 在英文句子中高亮重点难词，使用对应的颜色，并加上下划线"""
    if not word_colors or not text:
        return text
    
    # 按长度降序排序，优先匹配长词/短语，防止短词部分匹配
    sorted_words = sorted(word_colors.keys(), key=len, reverse=True)
    
    for word in sorted_words:
        word_clean = word.strip()
        if not word_clean:
            continue
        color = word_colors[word]
        word_escaped = re.escape(word_clean)
        pattern = re.compile(rf'\b({word_escaped})\b', re.IGNORECASE)
        # 将匹配的单词替换为：开启下划线 \u1，颜色 \cColor，单词本身，关闭下划线 \u0，重置颜色 \c
        text = pattern.sub(rf'{{\\u1\\c{color}}}\1{{\\u0\\c}}', text)
    return text

def tag_aware_wrap(text: str, max_width: int) -> str:
    """[Gemini_3.5_Flash_planning] 标签敏感的折行函数，忽略 ASS 样式标签 (如 {\\c&H...}) 的视觉长度并防止其内部断词"""
    if not text:
        return text
    
    # 匹配含可能被 ASS 标签包裹的单词，或者纯 ASS 标签，或者空白字符
    token_pattern = re.compile(r'((?:\{[^\}]*\})*[^\s{]+(?:\{[^\}]*\})*|\{[^\}]*\}|\s+)')
    tokens = token_pattern.findall(text)
    
    lines = []
    current_line = []
    current_visual_len = 0
    
    def get_visual_length(s: str) -> int:
        return len(re.sub(r'\{[^\}]*\}', '', s))
        
    for token in tokens:
        if not token:
            continue
            
        if token.isspace():
            if current_line:
                current_line.append(token)
            continue
            
        token_visual_len = get_visual_length(token)
        
        if current_visual_len + token_visual_len > max_width:
            if not current_line:
                current_line.append(token)
                current_visual_len = token_visual_len
            else:
                line_str = "".join(current_line).rstrip()
                lines.append(line_str)
                current_line = [token]
                current_visual_len = token_visual_len
        else:
            current_line.append(token)
            current_visual_len += token_visual_len
            
    if current_line:
        lines.append("".join(current_line).rstrip())
        
    return "\\N".join(lines)


def _title_char_em_width(char: str) -> float:
    """估算标题字符视觉宽度，用于无渲染依赖的分行与字号选择。"""
    if char.isspace():
        return 0.35
    if char in '.,，。:：;；!?！？|/\\-—()（）[]【】“”"\'':
        return 0.45
    if ord(char) <= 127:
        return 0.56
    return 1.0


def _title_text_em_width(text: str) -> float:
    return sum(_title_char_em_width(char) for char in text)


def _split_semantic_title(title: str) -> Tuple[Optional[List[str]], bool]:
    """优先按两段式标题分隔符切开，便于第二段做视觉强调。"""
    for separator in ("：", ":", "？", "?", "！", "!", "——", " - ", "|"):
        index = title.find(separator)
        if 2 < index < len(title) - 3:
            left = title[: index + len(separator)].strip()
            right = title[index + len(separator) :].strip()
            if len(left) >= 4 and len(right) >= 3:
                return [left, right], True
    return None, False


def _best_balanced_title_break(title: str) -> int:
    target = _title_text_em_width(title) / 2
    best_index = max(1, len(title) // 2)
    best_score: Optional[float] = None
    for index in range(3, max(3, len(title) - 2)):
        left = title[:index].rstrip()
        right = title[index:].lstrip()
        if not left or not right:
            continue
        score = abs(_title_text_em_width(left) - target)
        if left[-1] in "的之和与及在":
            score += 3
        if left[-1] == right[0]:
            score += 4
        if _break_splits_protected_term(title, index):
            score += 6
        if best_score is None or score < best_score:
            best_score = score
            best_index = index
    return best_index


def _break_splits_protected_term(title: str, break_index: int) -> bool:
    for term in TITLE_PROTECTED_TERMS:
        start = title.find(term)
        while start >= 0:
            if start < break_index < start + len(term):
                return True
            start = title.find(term, start + 1)
    return False


def _truncate_title_line(line: str, max_em: float) -> str:
    if _title_text_em_width(line) <= max_em:
        return line
    current = 0.0
    output = ""
    ellipsis_em = _title_text_em_width("...")
    for char in line:
        char_width = _title_char_em_width(char)
        if current + char_width + ellipsis_em > max_em:
            return output.rstrip() + "..."
        current += char_width
        output += char
    return output


def _layout_title_lines(title: str) -> Tuple[List[str], int, bool]:
    """将头部标题排成最多两行，并返回适配后的字号。"""
    title = (title or "").strip()
    if not title:
        return [], TITLE_BASE_FONT_SIZE, False

    max_em_at_base = TITLE_MAX_WIDTH / TITLE_BASE_FONT_SIZE
    lines, is_semantic = _split_semantic_title(title)
    if lines is None:
        if _title_text_em_width(title) <= max_em_at_base:
            lines = [title]
        else:
            index = _best_balanced_title_break(title)
            lines = [title[:index].rstrip(), title[index:].lstrip()]

    max_line_em = max(_title_text_em_width(line) for line in lines)
    font_size = TITLE_BASE_FONT_SIZE
    if max_line_em * font_size > TITLE_MAX_WIDTH:
        font_size = max(TITLE_MIN_FONT_SIZE, int(TITLE_MAX_WIDTH / max_line_em))

    max_em_at_size = TITLE_MAX_WIDTH / font_size
    fitted_lines = [_truncate_title_line(line, max_em_at_size) for line in lines[:2]]
    return fitted_lines, font_size, is_semantic


def _escape_drawtext_text(text: str) -> str:
    """FFmpeg filtergraph 文本转义；配合 expansion=none 保留 466% 这类标题。"""
    return (
        text.replace("\\", "\\\\")
        .replace("'", "'\\\\''")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", " ")
    )


def _resolve_title_font_path(preferred_font: str) -> str:
    preferred_path = Path(preferred_font).expanduser() if preferred_font else None
    if preferred_path and preferred_path.exists() and preferred_path.name != "Arial Unicode.ttf":
        return str(preferred_path)
    for candidate in TITLE_FONT_CANDIDATES:
        candidate_path = Path(candidate).expanduser()
        if candidate_path.exists():
            return str(candidate_path)
    return str(preferred_path) if preferred_path else ""


def _build_title_drawtext_filters(input_label: str, title: str, preferred_font: str) -> Tuple[List[str], str]:
    lines, font_size, is_semantic = _layout_title_lines(title)
    if not lines:
        return [], input_label

    title_font = _resolve_title_font_path(preferred_font)
    font_cmd = f":fontfile='{title_font}'" if title_font else ""
    line_height = int(font_size * 1.12)
    block_height = len(lines) * line_height + max(0, len(lines) - 1) * TITLE_LINE_GAP
    start_y = max(58, int((TITLE_ZONE_HEIGHT - block_height) / 2))

    filters = []
    current_label = input_label
    for index, line in enumerate(lines):
        color = TITLE_PRIMARY_COLOR
        if len(lines) > 1 and index == len(lines) - 1:
            color = TITLE_ACCENT_COLOR if is_semantic or index == 1 else TITLE_PRIMARY_COLOR
        output_label = "titled" if index == len(lines) - 1 else f"title_{index}"
        y = start_y + index * (line_height + TITLE_LINE_GAP)
        filters.append(
            f"[{current_label}]drawtext=expansion=none:text='{_escape_drawtext_text(line)}':"
            f"fontcolor={color}:fontsize={font_size}:x=(w-text_w)/2:y={y}{font_cmd}:"
            "borderw=3:bordercolor=black@0.78:shadowx=0:shadowy=2:shadowcolor=black@0.55"
            f"[{output_label}]"
        )
        current_label = output_label
    return filters, current_label

logger = logging.getLogger(__name__)

class VerticalCaptionProcessor(AutoCaptionProcessor):
    """
    Vertical Video Processor (9:16)
    
    Features:
    - 3-Section Layout (Title, Video, Subtitles)
    - Auto-scaling to 1080x1920
    - Title rendering
    - External subtitle placement (in black bar)
    """

    def __init__(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        model_size: str = "small",
        src_lang: str = "en",
        target_lang: str = "zh-CN",
        device: str = "cpu",
        style: str = "default",
        title: str = "",
        bg_blur: bool = False,
        font_path: str = "/Library/Fonts/Arial Unicode.ttf",
        font_size: int = 84,
        bilingual: bool = False,
        tts_provider: Optional[str] = None,
        tts_voice: Optional[str] = None,  # [Gemini_3.5_Flash_planning]
        mute_original: bool = True,  # [Gemini_3.5_Flash_planning]
        tts_volume: int = 90,  # [Gemini_3.5_Flash_planning]
        tts_speech_rate: float = 1.0,  # [Gemini_3.5_Flash_planning]
        source_date: Optional[str] = None,  # [Claude_Opus_4.8] 源视频发布日期(YYYY-MM-DD)，毛玻璃戳
        progress_reporter=None,
    ):
        super().__init__(
            input_path, output_path, model_size, src_lang, target_lang, device, style,
            progress_reporter=progress_reporter,
        )
        # [Gemini_3.5_Flash_planning] Try to load title from .info.json if it exists
        detected_title = title
        if not detected_title:
            info_json_path = input_path.with_suffix('.info.json')
            if info_json_path.exists():
                try:
                    import json
                    with open(info_json_path, 'r', encoding='utf-8') as f:
                        info_data = json.load(f)
                        detected_title = info_data.get('title', '')
                        logger.info(f"Loaded title from info.json: {detected_title}")
                except Exception as e:
                    logger.warning(f"Failed to load title from {info_json_path}: {e}")

        self.title = detected_title or input_path.stem  # Default to filename if empty
        self.bg_blur = bg_blur
        self.font_path = font_path
        self.font_size = font_size
        self.bilingual = bilingual
        self.tts_provider = tts_provider
        self.tts_voice = tts_voice  # [Gemini_3.5_Flash_planning]
        self.mute_original = mute_original  # [Gemini_3.5_Flash_planning]
        self.tts_volume = tts_volume  # [Gemini_3.5_Flash_planning]
        self.tts_speech_rate = tts_speech_rate  # [Gemini_3.5_Flash_planning]
        self.source_date = source_date  # [Claude_Opus_4.8] 源视频发布日期(YYYY-MM-DD)；None/"" 则不渲染日期戳
        self.segments = [] # Store for TTS usage

    def _get_audio_duration(self, path: Path) -> float:
        """[Gemini_3.5_Flash_planning] 获取音频文件的精确时长，优先使用 ffprobe 避免读取到流式 WAV 头中的超大占位符"""
        import subprocess
        try:
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except Exception:
            # 备用方案：使用 wave 读取（仅作最后兜底）
            try:
                import wave
                with wave.open(str(path), 'rb') as w:
                    nframes = w.getnframes()
                    # 如果 nframes 异常大（例如超过 1 小时，对于短视频片段显然不合理），则根据文件大小估算
                    if nframes > 10000000:
                        # 16kHz 16bit mono = 32000 bytes/sec
                        return path.stat().st_size / 32000.0
                    return nframes / float(w.getframerate())
            except Exception:
                return 0.0

    def _adjust_audio_speed(self, input_path: Path, factor: float):
        """[Gemini_3.5_Flash_planning] 使用 ffmpeg atempo 滤镜调整音频速度并覆盖原文件"""
        temp_path = input_path.with_name(f"temp_{input_path.name}")
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        factor = min(2.0, max(0.5, factor))
        
        cmd = [
            ffmpeg_exe, "-y",
            "-i", str(input_path),
            "-filter:a", f"atempo={factor:.3f}",
            str(temp_path)
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if temp_path.exists():
                temp_path.replace(input_path)
        except Exception as e:
            logger.error(f"Failed to adjust audio speed for {input_path}: {e}")

    def _generate_ass_file(self, segments: List[Dict[str, Any]]) -> Path:
        """Override to adjust subtitle vertical position (MarginV) and font size"""
        # Store segments for TTS generation later
        self.segments = segments
        
        # Initialize ASS file
        subs = pysubs2.SSAFile()
        subs.info['PlayResX'] = VerticalLayout.CANVAS_WIDTH
        subs.info['PlayResY'] = VerticalLayout.CANVAS_HEIGHT

        font_size = self.font_size
        
        # [Gemini_3.5_Flash_planning] 英文实际渲染字号缩水至 0.71，中文设为 0.81 以获得最佳比例
        en_size = int(font_size * 0.71)
        zh_size = int(font_size * 0.81)
        
        # Calculate dynamic wrap width
        safe_width = int(VerticalLayout.CANVAS_WIDTH * 0.96)
        
        # [Gemini_3.5_Flash_planning] 计算折行限制：中文等宽，英文 Georgia 比例字体宽度因子设为 0.54 以防溢出
        wrap_width_zh = max(10, int(safe_width / zh_size))
        wrap_width_en = max(20, int(safe_width / (en_size * 0.54)))
        
        # Get base config
        config = CAPTION_STYLES.get(self.style, CAPTION_STYLES["default"])
        
        # Determine dynamic MarginV to prevent overlapping on different video types
        # [Gemini_3.5_Flash_planning] Fetch video resolution to calculate layout dynamically
        try:
            video_w, video_h = self._get_video_resolution()
        except Exception as e:
            logger.warning(f"Could not probe video size for subtitle margin, fallback to landscape layout: {e}")
            video_w, video_h = 1920, 1080

        is_vertical_input = video_w < video_h
        layout_params = VerticalLayout.calculate(video_w, video_h)

        # Parse background color and alpha
        bg_hex = config.get("bg_color", "&H000000")
        bg_alpha = config.get("bg_alpha", 180)  # Default to semi-transparent black
        
        clean_bg = bg_hex.replace('&H', '').replace('&', '').strip()
        if len(clean_bg) == 8:
            clean_bg = clean_bg[2:]
        if len(clean_bg) == 6:
            b_val = int(clean_bg[0:2], 16)
            g_val = int(clean_bg[2:4], 16)
            r_val = int(clean_bg[4:6], 16)
        else:
            r_val, g_val, b_val = 0, 0, 0
            
        bg_color = pysubs2.Color(r_val, g_val, b_val, bg_alpha)
        
        border_style = config.get("border_style", 3)
        outline = config.get("outline", 12)
        
        if border_style == 3:
            outline = max(outline, 10)
            
        shadow = config.get("shadow", 0)

        # [Claude_Sonnet_4.6_Thinking_planning] 字幕区顶部位置和最大可用高度（在 outline 确定后计算）：
        # 竖屏输入：Y=1200，GlossaryCard 顶部约 Y=1532，留 32px 安全边 → max_height=300px
        # 横屏输入：使用 layout_params 计算得到的动态 margin_v (video_bottom_y + 90px)，GlossaryCard 紧跟字幕下方
        #            → max_height = font_size*3.5 + outline*2 - 20 ≈ 294px
        # 两种模式下单行文本（≈203px）均不触发缩放，多行才缩放。
        subtitle_top_y = layout_params.subtitle_margin_v
        if is_vertical_input:
            # [Claude_Sonnet_4.6_planning] 释义区字号 = font_size * 0.42；半字高 ≈ gloss_size / 2
            _gloss_size = int(font_size * 0.42)  # 默认 84*0.42=35pt
            _gloss_half_height = int(_gloss_size / 2.0)  # ≈17px
            # GlossaryCard 顶部的预期位置（随底部 marginv 上移而相应上移）
            GLOSSARY_EXPECTED_TOP = int(VerticalLayout.CANVAS_HEIGHT * 0.90) - 196 - _gloss_half_height  # ≈1515
            subtitle_max_height = max(200, GLOSSARY_EXPECTED_TOP - 32 - subtitle_top_y)
        else:
            subtitle_max_height = max(200, int(font_size * 3.5) + outline * 2 - 20)  # [Gemini_3.5_Flash_planning] Fixed syntax error by adding closing parenthesis
        layout = SubtitleLayout(
            en_size=en_size,
            zh_size=zh_size,
            safe_width=safe_width,
            max_height=subtitle_max_height,
            outline=outline,
        )
        stylist = SubtitleStylist(layout)

        # [Gemini_3.5_Flash_planning] Re-add Default and GlossaryCard styles to subs.styles
        style = pysubs2.SSAStyle(
            fontsize=font_size,
            primarycolor=pysubs2.Color(255, 210, 63),
            backcolor=bg_color,
            outlinecolor=bg_color,
            borderstyle=border_style,
            outline=outline,
            shadow=shadow,
            alignment=8,  # Top Center
            marginv=subtitle_top_y,
            fontname="Hiragino Sans GB"
        )
        subs.styles["Default"] = style

        # Determine glossary alignment and marginv
        if is_vertical_input:
            glossary_alignment = 2  # Bottom Center, grows upwards
            # [Claude_Sonnet_4.6_planning] 底部边距加上半字高，使释义区最下沿上移 ~17px
            _gloss_size = int(font_size * 0.42)
            _gloss_half_height = int(_gloss_size / 2.0)
            glossary_marginv = int(VerticalLayout.CANVAS_HEIGHT * 0.10) + _gloss_half_height  # ≈209px
        else:
            glossary_alignment = 8  # Top Center
            glossary_marginv = subtitle_top_y + int(font_size * 3.5) + outline * 2 + 10

        glossary_bg_color = pysubs2.Color(105, 105, 105, 40)
        style_glossary = pysubs2.SSAStyle(
            fontsize=int(font_size * 0.42), # [Gemini_3.5_Flash_planning] 将字号调为 0.42 倍 (约 35pt)，使其小于英文字幕 (59pt)，符合次要辅助排版原则
            primarycolor=pysubs2.Color(255, 210, 63),
            backcolor=glossary_bg_color,
            outlinecolor=glossary_bg_color,
            borderstyle=border_style,
            outline=outline,
            shadow=shadow,
            alignment=glossary_alignment,
            marginv=glossary_marginv,
            fontname="Songti SC"
        )
        subs.styles["GlossaryCard"] = style_glossary

        for seg in segments:
            start_ms = int(seg['start'] * 1000)
            end_ms = int(seg['end'] * 1000)
            en_text = seg.get('text', '').strip().replace('\n', ' ')
            zh_text = seg.get('zh_text', '').strip().replace('\n', ' ')
            vocab_items = seg.get('vocab', {})

            # 委托字幕样式和折行给 SubtitleStylist
            rendered = stylist.render(
                en_text=en_text,
                zh_text=zh_text,
                vocab_items=vocab_items or {},
                bilingual=self.bilingual,
            )

            evt = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=rendered.ass_text)
            subs.events.append(evt)

            # GlossaryCard 词汇释义区
            if vocab_items and self.bilingual:
                # [Claude_Opus_4.6_Thinking_planning] 传入 default_gloss_size 和 en_size，
                # build_glossary_text 内部取 min() 确保释义字号始终 ≤ 样式默认值 ≤ 英文字幕字号
                _default_gloss_size = int(self.font_size * 0.42)
                glossary_text = stylist.build_glossary_text(
                    vocab_items,
                    en_size=rendered.en_size,
                    default_gloss_size=_default_gloss_size,
                )
                evt_glossary = pysubs2.SSAEvent(start=start_ms, end=end_ms, style="GlossaryCard", text=glossary_text)
                subs.events.append(evt_glossary)

        ass_path = self.input_path.with_suffix('.ass')
        subs.save(str(ass_path))
        return ass_path

    def _burn_subtitles(self, ass_path: Path) -> Path:
        """Compose 3-section layout using FFmpeg filter_complex"""
        
        output_path = self.output_path or self.input_path.parent / f"{self.input_path.stem}_vertical{self.input_path.suffix}"
        self.output_path = output_path
        
        # [Claude_Sonnet_4.6_Thinking_planning] v1.5.0: TTS 默认关闭。
        # 只有用户通过 --tts / --tts-real 参数，或 Telegram /tts 命令
        # 明确指定 tts_provider 后，才启用语音合成。非中文视频不再自动激活 TTS。
        if self.tts_provider:
            logger.info(f"[TTS] Provider explicitly set: {self.tts_provider}")


        generated_audio_track = None
        audio_segments = []  # [Gemini_3.5_Flash_planning] 声明为外部作用域变量，以供后面的 Ducking 计算使用
        if self.tts_provider and self.segments:
            logger.info(f"Generating TTS audio using provider: {self.tts_provider}")
            try:
                # Initialize Engine
                if self.tts_provider in {"indextts", "cosyvoice"}:
                    provider = TTSProvider.INDEXTTS
                else:
                    provider = TTSProvider.EDGE
                if self.tts_provider == "cosyvoice":
                    logger.info("[TTS] Migrating legacy cosyvoice task to local IndexTTS.")
                tts_engine = TTSEngine(provider=provider)
                
                # Prepare items
                tts_items = []
                audio_dir = output_path.parent / f"{output_path.stem}_audio_gen"
                audio_dir.mkdir(exist_ok=True)
                
                audio_segments = []
                
                for i, seg in enumerate(self.segments):
                    zh_text = seg.get('zh_text', '').strip().replace('\\N', ' ')
                    if not zh_text: 
                        continue
                        
                    filename = f"line_{i:04d}.wav"
                    tts_items.append({'text': zh_text, 'filename': filename})
                    
                    audio_segments.append({
                        'start': seg['start'],
                        'path': audio_dir / filename
                    })
                
                if tts_items:
                    # Batch Generate
                    tts_engine.batch_generate(tts_items, audio_dir, voice_prompt="test_audio.wav" if provider == TTSProvider.INDEXTTS else "zh-CN-XiaoxiaoNeural")
                    
                    # [Gemini_3.5_Flash_planning] 防重叠后处理：对超出当前字幕槽或间隔时间段上限的音频段，动态使用 atempo 滤镜进行无损加速
                    for idx, seg_audio in enumerate(audio_segments):
                        path = seg_audio['path']
                        if not path.exists():
                            continue
                        duration = self._get_audio_duration(path)
                        if duration <= 0:
                            continue
                        
                        limit_duration = 9999.0
                        if idx + 1 < len(audio_segments):
                            limit_duration = audio_segments[idx+1]['start'] - seg_audio['start']
                        else:
                            try:
                                video_duration = self._get_audio_duration(self.input_path)
                                if video_duration > 0:
                                    limit_duration = video_duration - seg_audio['start']
                            except Exception:
                                pass
                        
                        safe_limit = max(0.5, limit_duration - 0.1)
                        if duration > safe_limit:
                            factor = duration / safe_limit
                            logger.info(f"[Ducking Optimization] Segment {idx} duration {duration:.2f}s exceeds limit {safe_limit:.2f}s. Auto speeding up by {factor:.2f}x")
                            self._adjust_audio_speed(path, factor)
                    
                    # Mix Audio
                    generated_audio_track = audio_dir / "mixed_narration.wav"
                    # We need total duration. Prob video duration? 
                    # We can use probing later or just let ffmpeg handle it by input 0 map.
                    # AudioMixer might fail if no duration. 
                    # Let's rely on ffmpeg merging in main command if mixer is complex.
                    # Actually AudioMixer.create_mixed_audio_track was implemented to use filter_complex `adelay`.
                    # We can use that.
                    AudioMixer.create_mixed_audio_track(audio_segments, 0, generated_audio_track)
                
            except Exception as e:
                logger.error(f"TTS Generation failed: {e}")
                generated_audio_track = None

        # 1. Probe input video dimensions
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", 
                 "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", 
                 str(self.input_path)],
                capture_output=True, text=True, check=True
            )
            w, h = map(int, probe.stdout.strip().split('x'))
        except Exception:
            # Fallback or error
            w, h = 1920, 1080 # Assume 1080p landscape if probe fails?
            logger.warning("Could not probe video size, assuming 1920x1080")

        # 2. Calculate Layout
        layout = VerticalLayout.calculate(w, h)
        
        # 3. Build Filter Complex
        # Escapes
        escaped_ass = str(ass_path).replace("'", "'\\''").replace(":", "\\:")
        
        filters = []
        
        if self.bg_blur:
            # Background: Scale input to Fill 1080x1920, Blur
            filters.append(f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg]")
            # Foreground: Scale to new_h
            filters.append(f"[0:v]scale=1080:{layout.new_height}[fg]")
            # Overlay
            filters.append(f"[bg][fg]overlay=0:{layout.video_y}[merged]")
        else:
            # Solid Black Background
            # Scale input to 1080:new_h
            filters.append(f"[0:v]scale=1080:{layout.new_height}[fg]")
            # Pad to 1080x1920 at correct y position
            # pad=width:height:x:y:color
            filters.append(f"[fg]pad=1080:1920:0:{layout.video_y}:black[merged]")

        title_filters, title_label = _build_title_drawtext_filters("merged", self.title, self.font_path)
        filters.extend(title_filters)
        
        # Burn Subtitles
        # [Claude_Opus_4.8] 若启用「源视频发布日期戳」，字幕烧录输出改为中间标签 [ds_subbed]，
        # 之后再叠加毛玻璃日期戳产出 [out]；未启用则字幕直接产出 [out]（行为完全不变）。
        _stamp_value = (self.source_date or "").strip()
        _stamp_enabled = bool(_stamp_value)
        if _stamp_enabled:
            filters.append(f"[{title_label}]ass='{escaped_ass}'[ds_subbed]")
        else:
            filters.append(f"[{title_label}]ass='{escaped_ass}'[out]")

        filter_str = ";".join(filters)
        
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        cmd = [
            ffmpeg_exe, "-y",
            # 部分 60fps H.264 输入在当前 FFmpeg 构建的帧级多线程解码下会偶发丢失宏块；
            # 丢失会被后续缩放/字幕烧录永久写进成片，故在统一渲染入口保守固定为单线程。
            "-threads", "1",
            "-i", str(self.input_path),
        ]
        
        # [Gemini_3.5_Flash_planning] 检测输入视频是否含有音频流
        has_audio = True
        try:
            cmd_probe = [
                "ffprobe", "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=index", "-of", "csv=p=0",
                str(self.input_path)
            ]
            result = subprocess.run(cmd_probe, capture_output=True, text=True, check=True)
            has_audio = bool(result.stdout.strip())
        except Exception:
            pass
            
        # Audio Mapping Logic
        if has_audio:
            audio_inputs = ["-map", "0:a"] # Default: Original Audio
            
            if generated_audio_track and generated_audio_track.exists():
                # Add new audio as input 1
                cmd += ["-i", str(generated_audio_track)]
                
                # [Gemini_3.5_Flash_planning] 根据 mute_original 决定是完全静音还是动态音量闪避
                if self.mute_original:
                    volume_filter = "volume=0.0"
                else:
                    intervals = []
                    for seg in audio_segments:
                        start = seg['start']
                        path = seg['path']
                        duration = self._get_audio_duration(path)
                        if duration > 0:
                            intervals.append((start, start + duration))
                    
                    if intervals:
                        # 使用 between 串联各个发音区间，如果当前时间 t 处于任意发音区间，则背景音设为 10% (0.1)，否则保持 100% (1.0)
                        conds = " + ".join([f"between(t,{s:.3f},{e:.3f})" for s, e in intervals])
                        volume_filter = f"volume='if({conds},0.1,1.0)':eval=frame"
                    else:
                        volume_filter = "volume=0.1"
                    
                audio_filter = f"[0:a]{volume_filter}[bg];[1:a]volume=1.5[fg];[bg][fg]amix=inputs=2:duration=first[aout]"
                filter_str += f";{audio_filter}"
                
                audio_inputs = ["-map", "[aout]"]
        else:
            # Input video has no audio
            if generated_audio_track and generated_audio_track.exists():
                # Add new audio as input 1
                cmd += ["-i", str(generated_audio_track)]
                # Just map the generated audio track directly (no mixing needed)
                audio_inputs = ["-map", "1:a"]
            else:
                audio_inputs = [] # No audio mapping needed
        
        # [Claude_Opus_4.8] 源视频发布日期毛玻璃戳：在字幕之上叠加圆角毛玻璃日期戳。
        # 局部高斯模糊 + 半透明深色着色 + 圆角遮罩 + 白字，覆盖源左上角频道水印。
        # 遮罩/边框作为图片输入**追加在视频(0)与可选配音轨之后**，避免与音频 [1:a] 索引冲突。
        _stamp_tmpdir = None
        if _stamp_enabled:
            import tempfile
            from config.settings import settings as _settings
            from . import date_stamp as _ds
            _geom = _ds.compute_geometry(
                _stamp_value,
                label=_settings.source_date_stamp_label,
                font_path=self.font_path,
                canvas_w=VerticalLayout.CANVAS_WIDTH,
                frame_top_y=layout.video_y,
            )
            _stamp_tmpdir = Path(tempfile.mkdtemp(prefix="datestamp_"))
            _mask_path, _border_path = _ds.generate_assets(_geom, _stamp_tmpdir)
            # 是否已追加独立配音输入(input 1) → 决定遮罩/边框的输入索引基址
            _has_audio_in = bool(generated_audio_track and generated_audio_track.exists())
            _stamp_base = 1 + (1 if _has_audio_in else 0)
            filter_str += ";" + _ds.build_filter_chain(
                _geom, in_label="ds_subbed", out_label="out",
                mask_idx=_stamp_base, border_idx=_stamp_base + 1,
            )
            cmd += ["-i", str(_mask_path), "-i", str(_border_path)]
            logger.info(
                f"[DateStamp] 叠加源发布日期戳 text={_geom.text!r} "
                f"@({_geom.px},{_geom.py}) {_geom.pw}x{_geom.ph} inputs=({_stamp_base},{_stamp_base + 1})"
            )

        cmd += [
            "-filter_complex", filter_str,
            "-map", "[out]",
            *audio_inputs,
            "-c:v", "libx264",
        ]
        if audio_inputs:
            cmd += ["-c:a", "aac"]
        cmd.append(str(output_path))
        
        logger.info(f"Rendering Vertical Video: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        finally:
            if _stamp_tmpdir is not None:
                import shutil
                shutil.rmtree(_stamp_tmpdir, ignore_errors=True)

        return output_path

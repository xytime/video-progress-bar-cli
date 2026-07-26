"""智能字幕处理器 - 提供语音转文字、翻译及ASS字幕生成功能

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-05-21 | Gemini_3.1_Pro_High_planning | 修复未导入 os 引发异常，修复硬编码 ffmpeg 导致无 libass 问题 |
| 1.1.1 | 2026-05-21 | Gemini_3.1_Pro_High_planning | 修复深层翻译API风控导致将500报错信息输出为中文字幕的重大缺陷 |
| 1.2.0 | 2026-05-22 | Gemini_3.1_Pro_High_planning | [红蓝博弈] 引入正则彻底熔断 HTML 注入，修正 default 金色描边样式 |
| 1.3.0 | 2026-05-28 | Gemini_3.5_Flash_planning | 集成 Gemini API 高质量批翻译功能，自动 fallback 到谷歌翻译，标注 # [Gemini_3.5_Flash_planning] |
| 1.4.0 | 2026-05-28 | Gemini_3.5_Flash_planning | ASR 转录时保存 self.detected_lang 属性，标注 # [Gemini_3.5_Flash_planning] |
| 1.5.0 | 2026-06-07 | Gemini_3.5_Flash_planning | Handle audio-less videos gracefully by skipping audio extraction/transcription and omitting -c:a copy during burn-in. |
| 1.6.0 | 2026-06-07 | Gemini_3.5_Flash_planning | 修复 src.config.settings 导入路径错误，并升级 Gemini 批翻译提示词以同时提取重点难词和释义，标注 # [Gemini_3.5_Flash_planning] |
| 1.7.0 | 2026-06-07 | Gemini_3.5_Flash_planning | 将 Gemini 模型从 gemini-2.5-flash 切换为 gemini-1.5-flash 以免遭遇 20 RPD 的 Free Tier 每日限流，标注 # [Gemini_3.5_Flash_planning] |
| 1.8.0 | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | 迁移至 google.genai SDK（v2.6.0），废弃已停止维护的 google.generativeai，标注 # [Claude_Sonnet_4.6_Thinking_planning] |
| 1.9.0 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 新增阿里云机器翻译通用版作为二级 fallback：Gemini(429) → Aliyun MT → Google Translate |
| 1.9.1 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 将阿里云 MT 逐条串行请求改为批量拼接方案（SEP 分隔符 + 切割回填），100+ 次 API 调用压缩到 4-5 次，延迟降低约 20x |
| 1.10.0 | 2026-06-08 | Gemini_3.5_Flash_planning | 智能提取 2-3 个单词释义（不多于3个以免内容过多），并为 Gemini API 引入 429 限流重试与多模型(3.5/1.5)回退机制，标注 # [Gemini_3.5_Flash_planning] |
| 1.10.1 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | [ReviewFix] P0: 提示词更新为 3-5 个词汇; P1: sleep 压缩至 2-8s; P2: import 移顶层; P3: 非429错误立即 raise |
| 1.10.2 | 2026-06-08 | Gemini_3.5_Flash_planning | 根据用户要求将词组提取上限严格控制在 3 个以内 (2-3个)，并将 Fallback 模型修正为可用且不超限的 gemini-2.5-flash，标注 # [Gemini_3.5_Flash_planning] |
| 1.10.3 | 2026-06-08 | Gemini_3.5_Flash_planning | 优先使用阿里云 MT 进行主字幕翻译，并将 Gemini 作为翻译 fallback 与难词提取器，标注 # [Gemini_3.5_Flash_planning] |
| 1.10.4 | 2026-06-08 | Gemini_3.5_Flash_planning | 优化错误分类：连接断开与 5xx 服务端错误不作为立即 raise 的致命错误，允许 fallback 到备用模型，标注 # [Gemini_3.5_Flash_planning] |
| 1.10.5 | 2026-06-08 | Gemini_3.5_Flash_planning | _translate_segments 增加 try-except 容灾保护，使 Gemini 异常对调用链安全，标注 # [Gemini_3.5_Flash_planning] |
| 1.10.6 | 2026-06-08 | Gemini_3.5_Flash_planning | 提示词升级：强制让 vocab 中的中文词汇与翻译句子中的子串完全对齐，以便于前端画下划线，标注 # [Gemini_3.5_Flash_planning] |
| 1.11.0 | 2026-06-08 | Claude_Sonnet_4.6_planning | 将 _translate_segments_aliyun 迁移至 translation_helper 模块，实现高内聘低耦合的统一翻译接口 |
| 1.12.0 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 移除 _translate_segments_gemini，委托至 vocab_helper.extract_vocab_batch；将阿里云翻译结果传入以实现中文字幕下划线 100% 精确对齐 |
| 1.13.0 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 翻转翻译优先级：Gemini 主译（习语/语境准确 + vocab 天然对齐）→ Aliyun 降级 → Google 终级 Fallback |
| 1.14.0 | 2026-06-09 | Claude_Opus_4.6_Thinking_planning   | Aliyun/Google 翻译成功后二次尝试 Gemini 对齐模式提取 vocab，解决 Gemini 429 时生词丢失问题 |
| 1.15.0 | 2026-07-05 | Codex | 接入 translation_quality_guard：翻译后统一做事实保真审计，P0 阻断，P1 告警 |
| 1.16.0 | 2026-07-05 | Codex | Gemini 翻译接入全片 TranslationContext，减少逐句翻译丢失语境 |
| 1.18.0 | 2026-07-17 | Codex | 移除阿里云 MT；质量守门改为 Gemini→DeepSeek→Google |
| 1.18.0 | 2026-07-05 | Codex | 翻译质量审计落盘为 *.translation_quality.json，记录供应商、告警、阻断与降级动作 |
| 1.19.0 | 2026-07-05 | Codex | 引入 provider-neutral SubtitleTranslationCandidate，统一字幕候选结果回填 |
| 1.20.0 | 2026-07-05 | Codex | 字幕翻译供应商顺序改由 settings 配置，主流程按 provider candidate 循环编排 |
| 1.21.0 | 2026-07-05 | Codex | 接入 DeepSeek 字幕翻译候选 provider（配置启用，默认关闭） |
| 1.22.0 | 2026-07-05 | Codex | 将字幕翻译质量决策抽象到 subtitle_translation_quality，主流程只保留编排职责 |
| 1.23.0 | 2026-07-05 | Codex | 质量审核复用 TranslationContext 的领域、事实与术语提示，并写入审计事件 |
| 1.24.0 | 2026-07-06 | Codex | 字幕质量上下文写入受保护英文实体，供审计与一致性检查复用 |
| 1.25.0 | 2026-07-06 | Codex | 字幕 provider 选择改为 warning-aware 仲裁，优先采用无告警候选 |
| 1.26.0 | 2026-07-06 | Codex | 将翻译候选仲裁状态机抽离到 utils，降低字幕处理器职责 |
| 1.27.0 | 2026-07-09 | Codex | 为 requests 系 SDK 请求补默认连接/读取超时，避免代理或上游 API 卡死时 auto-caption 无限等待 |
| 1.28.0 | 2026-07-09 | Codex | 新增翻译质量 fail-open 开关逻辑：临时降级阻断为告警放行 |
| 1.29.0 | 2026-07-13 | Codex | 动态模型池接入真实 provider 错误，按限流、权限、网络和解析问题冷却 |
| 1.30.0 | 2026-07-13 | Codex | 字幕翻译逐视频写入 SQLite AI 审计，记录 provider 尝试、降级、质量和最终结果 |
"""
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

import whisper
from deep_translator import GoogleTranslator
import pysubs2
import requests
import os
import json  # [Claude_Sonnet_4.6_Thinking_planning] moved from function body (P2 fix)
import time  # [Claude_Sonnet_4.6_Thinking_planning] moved from function body (P2 fix)

# [Gemini_3.1_Pro_High_planning] Monkeypatch requests to bypass VPN SSL interception
old_request = requests.Session.request
def new_request(*args, **kwargs):
    kwargs['verify'] = False
    kwargs.setdefault('timeout', (20, 90))
    return old_request(*args, **kwargs)
requests.Session.request = new_request

# Suppress InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ..core.base import VideoProcessorBase, VideoProcessingError
from ..utils.translation_helper import translate_batch as _google_batch_fallback
from ..utils.vocab_helper import extract_vocab_batch  # [Claude_Sonnet_4.6_Thinking_planning]
from ..utils.translation_context import build_translation_context
from ..utils.subtitle_translation_provider import (
    SubtitleTranslationCandidate,
    apply_translation_candidate,
)
from ..utils.subtitle_translation_quality import (
    SubtitleTranslationQualityContext,
    SubtitleTranslationQualityDecision,
    evaluate_subtitle_translation_candidate,
)
from ..utils.translation_candidate_arbitration import TranslationCandidateArbiter
from ..utils.translation_model_pool import DynamicTranslationModelPool, PROFILES, classify_error
from ..utils.deepseek_translation import (
    translate_batch_deepseek,
    translate_batch_with_vocab_deepseek,
)
from ..db.database import PipelineDB
from config.settings import settings

logger = logging.getLogger(__name__)

import textwrap

# 定义字幕样式方案
# 格式: {name: {zh_color: hex, en_color: hex, bg_color: hex, bg_alpha: 0-255, outline: int, shadow: int}}
# pysubs2.Color alpha: 0(transparent) -> 255(opaque)
# Note: In ASS raw, alpha is 00(opaque) -> FF(transparent). pyubs2 handles the conversion logic usually.
# pysubs2.Color(r,g,b,a=255) means OPAQUE. So 255 is solid.
# User said "100" was too transparent. 
# So we want HIGHER values for more opacity. 
# 200 = ~80% opaque. 128 = ~50% opaque.

CAPTION_STYLES = {
    "default": { # 经典白字黑底 (强对比)
        "zh_color": "&HFFFFFF", 
        "en_color": "&HD0D0D0", 
        "bg_color": "&H000000", 
        "bg_alpha": 200,        # Increased opacity
        "border_style": 3,
        "outline": 0,
        "shadow": 0
    },
    "movie_yellow": { # 电影黄 (无盒，描边)
        "zh_color": "&H00FFFF", 
        "en_color": "&HFFFFFF",
        "bg_color": "&H000000",
        "bg_alpha": 0,          # No background box usually
        "border_style": 1,
        "outline": 2,
        "shadow": 1
    },
    "tech_blue": { # 科技蓝 (深蓝半透明盒)
        "zh_color": "&H00FFFF", # Yellow
        "en_color": "&HFFFFFF", # White
        "bg_color": "&H320000", # Dark Blue (BGR: 32, 0, 0 => R=0 G=0 B=50)
        "bg_alpha": 180,        # More visible (~70% opaque)
        "border_style": 3,
        "outline": 0,
        "shadow": 0
    },
    "cyberpunk": { # 赛博朋克 (霓虹风格)
        "zh_color": "&HFE00FE", # Neon Pink/Purple (BGR) -> Fuhsia
        "en_color": "&H00FFFF", # Yellow/Cyan
        "bg_color": "&H200520", # Dark Purple
        "bg_alpha": 200,
        "border_style": 3,
        "outline": 1,
        "shadow": 0
    },
     "soft_pink": { # 柔和粉 (生活/Vlog)
        "zh_color": "&HFFFFFF", 
        "en_color": "&HF0E0E0", 
        "bg_color": "&H806090", # Pinkish/Purple
        "bg_alpha": 160,
        "border_style": 3,
        "outline": 0,
        "shadow": 0
    }
}
# ... (rest of imports)



class AutoCaptionProcessor(VideoProcessorBase):
    """
    智能字幕处理器
    
    功能：
    1. 提取音频
    2. 使用 Whisper 进行语音转文字 (ASR)
    3. 翻译字幕 (EN -> ZH)
    4. 生成双语 ASS 字幕文件
    5. 烧录字幕到视频
    """
    
    def __init__(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        model_size: str = "small",
        src_lang: str = "en",
        target_lang: str = "zh-CN",
        device: str = "cpu",
        style: str = "default"
    ):
        super().__init__(input_path, output_path)
        self.model_size = model_size
        self.src_lang = src_lang
        self.target_lang = target_lang
        self.device = device
        self.style = style if style in CAPTION_STYLES else "default"
        
        # 延迟加载模型
        self.model = None
        self.detected_lang = None  # [Gemini_3.5_Flash_planning] 保存 Whisper ASR 检测到的语种
        self._translation_quality_audit: List[Dict[str, Any]] = []
        self._translation_audit_run_id: Optional[int] = None

    def process(self, **kwargs) -> Path:
        """
        处理视频：提取音频 -> 转录 -> (翻译) -> (生成ASS) -> (烧录)
        """
        logger.info(f"Processing video: {self.input_path} with style: {self.style}")
        
        # 1. 确保模型已加载
        self._load_model()
        
        # 2. 提取音频
        audio_path = self._extract_audio()
        if audio_path:
            logger.info(f"Audio extracted to: {audio_path}")
        else:
            logger.info("No audio stream extracted (video is likely silent).")
        
        try:
            # 3. 转录
            if audio_path is not None:
                segments = self._transcribe_audio(audio_path)
            else:
                logger.info("Skipping transcription since there is no audio track.")
                segments = []
            
            # 4. 翻译 (如果提供了目标语言且不同于源语言)
            if self.target_lang and self.target_lang != self.src_lang:
                segments = self._translate_segments(segments)
            
            # 5. 生成 ASS 字幕 (双语样式)
            ass_path = self._generate_ass_file(segments)
            logger.info(f"Generated ASS file: {ass_path}")
            
            # 6. 烧录字幕 (使用 ASS 滤镜)
            final_output = self._burn_subtitles(ass_path)
            logger.info(f"Subtitles burned to: {final_output}")
            
            return final_output
            
        finally:
            # 清理临时文件 (音频 和 ASS文件?)
            # 用户可能想要保留 ASS 文件以便后续修改，这里暂时只清理音频
            if audio_path and audio_path.exists():
                os.remove(audio_path)
                logger.debug(f"Removed temp audio: {audio_path}")
    
    def _burn_subtitles(self, ass_path: Path) -> Path:
        """使用 FFmpeg 将 ASS 字幕烧录到视频"""
        import subprocess
        
        output_path = self.output_path or self.input_path.parent / f"{self.input_path.stem}_captioned{self.input_path.suffix}"
        self.output_path = output_path # Update self.output_path
        
        # 验证输出路径
        if output_path.exists():
            # 简单覆盖策略
            pass
            
        # 构建命令
        # 转义路径中的特殊字符
        escaped_ass_path = str(ass_path).replace("'", "'\\''").replace(":", "\\:")
        
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        # [Gemini_3.5_Flash_planning] 检测输入视频是否含有音频流，避免无音频流时使用 -c:a copy 报错
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
        
        cmd = [
            ffmpeg_exe, "-y",
            "-i", str(self.input_path),
            "-vf", f"ass='{escaped_ass_path}'",
        ]
        
        if has_audio:
            cmd += ["-c:a", "copy"]  # 音频流直接复制，不重编码
            
        cmd.append(str(output_path))
        
        logger.info(f"Burning subtitles: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if not output_path.exists():
            raise VideoProcessingError("Subtitle burn-in failed")
            
        return output_path

    def _get_video_resolution(self):
        import subprocess
        try:
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
                str(self.input_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            w, h = map(int, result.stdout.strip().split('x'))
            return w, h
        except:
            return 1920, 1080

    def _generate_ass_file(self, segments: List[Dict[str, Any]]) -> Path:
        """生成双语 ASS 字幕文件"""
        subs = pysubs2.SSAFile()
        video_w, video_h = self._get_video_resolution()
        is_vertical = video_w < video_h
        
        subs.info["PlayResX"] = str(video_w)
        subs.info["PlayResY"] = str(video_h)
        
        # 动态缩放字体与边距 - 引入红蓝博弈防御机制 (2D自适应缩放)
        if is_vertical:
            scale_factor = video_w / 1080.0  # 竖屏锚定宽度，防止横向溢出
        else:
            scale_factor = video_h / 1080.0  # 横屏锚定高度
            
        base_fontsize = int(115 * scale_factor)
        en_fontsize = int(50 * scale_factor)
        base_marginv = int(70 * scale_factor)
        
        # 获取样式配置
        config = CAPTION_STYLES[self.style]
        
        # 手动解析样式参数，因为 pysubs2.Color 需要 RGB, alpha 0=opaque, 255=transparent
        outline_color = pysubs2.Color(0, 0, 0, 0) # 默认描边颜色
        primary_color = pysubs2.Color(255, 255, 255, 0) # 默认主色
        
        if self.style == "default":
             primary_color = pysubs2.Color(255, 255, 255, 0) # 白色字 (White)
             bg_color = pysubs2.Color(0, 0, 0, 0) # 不透明黑色阴影色
             outline_color = pysubs2.Color(255, 215, 0, 0) # 金色描边 (Gold)
             border_style = 1 # 1=描边模式, 3=底盒模式
             outline = 4 # 加粗描边
             shadow = 2 # 添加黑色阴影
        elif self.style == "movie_yellow":
             bg_color = pysubs2.Color(0, 0, 0, config.get('bg_alpha', 0))
             border_style = config.get('border_style', 1)
             outline = config.get('outline', 2)
             shadow = config.get('shadow', 1)
        elif self.style == "tech_blue":
             bg_color = pysubs2.Color(0, 0, 50, config.get('bg_alpha', 180)) 
             border_style = config.get('border_style', 3)
             outline = config.get('outline', 0)
             shadow = config.get('shadow', 0)
        elif self.style == "soft_pink":
             bg_color = pysubs2.Color(128, 96, 144, config.get('bg_alpha', 160))
             border_style = config.get('border_style', 3)
             outline = config.get('outline', 0)
             shadow = config.get('shadow', 0)
        else: # Cyberpunk etc fallback
             bg_color = pysubs2.Color(32, 5, 32, config.get('bg_alpha', 200))
             border_style = config.get('border_style', 3)
             outline = config.get('outline', 1)
             shadow = config.get('shadow', 0)

        zh_c = config['zh_color']
        en_c = config['en_color']

        # 定义通用样式
        style = pysubs2.SSAStyle(
            fontsize=base_fontsize, 
            primarycolor=primary_color,
            backcolor=bg_color,
            outlinecolor=outline_color,
            borderstyle=border_style,
            outline=int(outline * scale_factor * 2),
            shadow=int(shadow * scale_factor * 2),
            alignment=2, # Bottom Center
            marginv=base_marginv,
            fontname="Arial Unicode MS",
            bold=True
        )
        subs.styles["Default"] = style
        
        # 换行宽度控制 (字体再次加大，极度收紧宽度强制分行)
        zh_wrap_width = 10 if is_vertical else 12
        en_wrap_width = 25 if is_vertical else 40
        
        for seg in segments:
            start_ms = int(seg['start'] * 1000)
            end_ms = int(seg['end'] * 1000)
            en_text = seg.get('text', '').strip()
            zh_text = seg.get('zh_text', '').strip()
            
            en_text = textwrap.fill(en_text, width=en_wrap_width)
            zh_text = textwrap.fill(zh_text, width=zh_wrap_width)
            
            if zh_text:
                zh_text = zh_text.replace('\n', '\\N')
                evt_zh = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=zh_text)
                evt_zh.marginv = base_marginv
                subs.events.append(evt_zh)
            
        # 保存到与输入同一目录
        ass_path = self.input_path.with_suffix('.ass')
        subs.save(str(ass_path))
        return ass_path

    def _extract_audio(self) -> Optional[Path]:
        """从视频提取音频到临时 .wav 文件 (16kHz, mono for Whisper)"""
        import tempfile
        import subprocess
        
        # [Gemini_3.5_Flash_planning] 预先检测音轨是否存在
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
            
        if not has_audio:
            logger.warning(f"No audio stream found in {self.input_path}. Skipping audio extraction.")
            return None
        
        temp_dir = Path(tempfile.gettempdir())
        audio_path = temp_dir / f"{self.input_path.stem}_temp_audio.wav"
        
        # [Gemini_3.1_Pro_High_planning] 修复硬编码 FFmpeg 调用导致找不到 libass 的问题
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        cmd = [
            ffmpeg_exe, "-y",
            "-i", str(self.input_path),
            "-vn",  # No video
            "-acodec", "pcm_s16le",
            "-ar", "16000",  # Whisper likes 16k
            "-ac", "1",      # Mono
            str(audio_path)
        ]
        
        logger.debug(f"Extracting audio: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            stderr_str = e.stderr.decode('utf-8', errors='ignore') if e.stderr else ""
            # 如果 FFmpeg 因找不到音频流报错，也视为无音轨，返回 None
            if "does not contain any stream" in stderr_str or "Output file does not contain any stream" in stderr_str:
                logger.warning(f"FFmpeg reported no audio stream during extraction: {stderr_str.strip()}")
                return None
            raise e
        
        if not audio_path.exists():
            raise VideoProcessingError("Audio extraction failed")
            
        return audio_path

    def _transcribe_audio(self, audio_path: Path) -> List[Dict[str, Any]]:
        """使用 Whisper 转录音频"""
        logger.info("Starting transcription...")
        # language=None means auto-detect. 
        # task="transcribe" default.
        result = self.model.transcribe(
            str(audio_path), 
            language=self.src_lang if self.src_lang != "auto" else None,
            fp16=False # Force FP32 for CPU compatibility if needed, or check device
        )
        self.detected_lang = result.get("language")  # [Gemini_3.5_Flash_planning] 保存 ASR 识别的语种，供 TTS 智能判断使用
        return result["segments"]

    # [Claude_Sonnet_4.6_Thinking_planning] v1.12.0: _translate_segments_gemini 已移除。
    # 所有 Gemini SDK 交互现由 vocab_helper.extract_vocab_batch 高内聚地封装。

    def _translate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量翻译字幕片段 — Gemini 主译 → DeepSeek 交叉候选 → Google 终级兜底。

        [Claude_Sonnet_4.6_Thinking_planning] v1.13.0:
        Gemini 优先：其对习语/隐喻/语境有正确理解（如 'in code'→'暗示' 而非'代码'），
        且翻译与词汇注释在同一次调用中天然对齐，vocab 值即为 translation 子串，
        使 SubtitleStylist.apply_chinese_highlights 能 100% 命中并画出下划线。

        DeepSeek 作为独立的翻译 + vocabulary 候选，Google 只在前两者不可用时兜底。
        """
        if not segments:
            return segments

        logger.info(f"Translating {len(segments)} segments from {self.src_lang} to {self.target_lang}...")
        texts = [seg.get("text", "").strip() for seg in segments]
        self._translation_quality_audit = []
        self._translation_audit_run_id = self._start_translation_audit()
        translation_context = build_translation_context(texts)
        translation_prompt_context = translation_context.to_prompt_context()
        quality_context = SubtitleTranslationQualityContext(
            source_context_text="\n".join(texts),
            domain=translation_context.domain,
            facts=translation_context.facts,
            entities=translation_context.entities,
            term_notes=translation_context.term_notes,
            style_notes=translation_context.style_notes,
        )

        project_root = getattr(settings, "project_root", None)
        state_path = (
            project_root / "output" / "translation_model_pool.json"
            if project_root is not None
            else None
        )
        pool = DynamicTranslationModelPool(state_path)
        configured_providers = settings.subtitle_translation_provider_order_list
        if hasattr(settings, "enable_deepseek_vocab_fallback") and not settings.enable_deepseek_vocab_fallback:
            configured_providers = [provider for provider in configured_providers if provider != "deepseek"]
        provider_order = pool.order(
            configured_providers,
            required={"translate", "vocab"},
            # Gemini 的限流必须落到具体模型；不可让旧的 provider 冷却掩盖 3.1 Flash Lite 等余量。
            ignore_cooldown={"gemini"},
        )
        arbiter = TranslationCandidateArbiter()
        for idx, provider in enumerate(provider_order):
            final_provider = idx == len(provider_order) - 1
            self._last_provider_error = ""
            attempt_started = time.monotonic()
            candidate = self._build_translation_candidate(provider, texts, translation_prompt_context)
            duration_ms = int((time.monotonic() - attempt_started) * 1000)
            if not candidate or not candidate.is_usable_for(len(segments)):
                logger.warning("[Translate] Provider %s produced no usable candidate.", provider)
                error = self._last_provider_error or "empty_or_insufficient_translation"
                error_class = classify_error(error)
                pool.record_failure(provider, error, category=error_class)
                self._record_translation_attempt(
                    provider, idx + 1, "FAILED", duration_ms, error_class=error_class, error_message=error,
                )
                continue

            decision = self._evaluate_translation_quality(
                texts,
                candidate.translations[:len(segments)],
                provider=candidate.provider,
                final_provider=final_provider,
                quality_context=quality_context,
            )
            event = self._record_translation_quality_decision(
                decision,
                provider=candidate.provider,
                final_provider=final_provider,
                selected=False,
            )
            outcome = arbiter.consider(
                candidate=candidate,
                decision=decision,
                event=event,
                final_provider=final_provider,
            )
            quality_score = max(0.0, 100.0 - len(decision.warning_issues) * 8.0 - len(decision.blocking_issues) * 30.0)
            if decision.should_fallback or decision.should_fail:
                pool.record_failure(provider, decision.blocking_summary(), category="quality_blocked")

            attempt_status = "BLOCKED" if decision.should_fallback or decision.should_fail else "SUCCEEDED"
            self._record_translation_attempt(
                provider,
                idx + 1,
                attempt_status,
                duration_ms,
                error_class="quality_blocked" if attempt_status == "BLOCKED" else None,
                error_message=decision.blocking_summary() if attempt_status == "BLOCKED" else None,
                quality_score=quality_score,
                warning_count=len(decision.warning_issues),
                blocking_count=len(decision.blocking_issues),
                selected=outcome.should_use_candidate,
            )

            if decision.should_fallback:
                self._write_translation_quality_report()
                logger.warning(
                    "[TranslationGuard][%s] Blocking issue found; falling back to next provider: %s",
                    candidate.provider,
                    decision.blocking_summary(),
                )
                continue

            if outcome.should_use_candidate:
                self._apply_selected_translation_candidate(
                    segments,
                    outcome.candidate,
                    texts,
                    translation_prompt_context,
                )
                pool.record_quality(provider, score=quality_score, warning_count=len(decision.warning_issues))
                self._record_selected_gemini_model_quality(outcome.candidate, quality_score, state_path)
                self._finish_translation_audit("SUCCEEDED", outcome.candidate, quality_score, decision.status, idx > 0, segments)
                self._write_translation_quality_report()
                return segments

            if outcome.should_fail:
                self._write_translation_quality_report()
                raise VideoProcessingError(
                    f"Translation quality guard blocked {candidate.provider} output: {decision.blocking_summary()}"
                )

        outcome = arbiter.finish()
        if outcome.should_use_candidate:
            self._apply_selected_translation_candidate(
                segments,
                outcome.candidate,
                texts,
                translation_prompt_context,
            )
            self._record_selected_gemini_model_quality(outcome.candidate, 90.0, state_path)
            self._finish_translation_audit("SUCCEEDED", outcome.candidate, None, "accepted_after_arbitration", True, segments)
            self._write_translation_quality_report()
            return segments

        self._finish_translation_audit(
            "FAILED", None, None, "all_providers_failed", bool(provider_order), segments,
            error_class="all_providers_failed", error_message="All subtitle translation providers failed or were blocked.",
        )
        raise VideoProcessingError("All subtitle translation providers failed or were blocked.")

    def _record_selected_gemini_model_quality(self, candidate: SubtitleTranslationCandidate, score: float, state_path: Optional[Path]) -> None:
        if candidate.provider.lower() != "gemini" or not candidate.model:
            return
        for model_name in candidate.model.split(","):
            DynamicTranslationModelPool(state_path).record_quality(model_name, score=score)

    def _start_translation_audit(self) -> Optional[int]:
        """创建可观测性运行记录；审计故障不可阻断视频处理。"""
        try:
            return PipelineDB().start_ai_processing_run(self.input_path.stem)
        except Exception as exc:
            logger.warning("[AIAudit] failed to start translation audit: %s", exc)
            return None

    def _record_translation_attempt(
        self,
        provider: str,
        attempt_order: int,
        status: str,
        duration_ms: int,
        *,
        error_class: Optional[str] = None,
        error_message: Optional[str] = None,
        quality_score: Optional[float] = None,
        warning_count: int = 0,
        blocking_count: int = 0,
        selected: bool = False,
    ) -> None:
        if self._translation_audit_run_id is None:
            return
        try:
            key = provider.lower()
            profile = PROFILES.get(key)
            model = {
                "gemini": "dynamic Gemini pool",
                "deepseek": getattr(settings, "deepseek_model", "") or "DeepSeek default",
                "google": "Google Translate",
            }.get(key)
            capabilities = ",".join(sorted(profile.capabilities)) if profile else "translate"
            PipelineDB().record_ai_provider_attempt(
                self._translation_audit_run_id,
                provider=provider,
                model=model,
                capabilities=capabilities,
                attempt_order=attempt_order,
                status=status,
                duration_ms=duration_ms,
                error_class=error_class,
                error_message=error_message,
                quality_score=quality_score,
                warning_count=warning_count,
                blocking_count=blocking_count,
                selected=selected,
            )
        except Exception as exc:
            logger.warning("[AIAudit] failed to record provider attempt: %s", exc)

    def _finish_translation_audit(
        self,
        status: str,
        candidate: Optional[SubtitleTranslationCandidate],
        quality_score: Optional[float],
        quality_status: str,
        fallback_used: bool,
        segments: List[Dict[str, Any]],
        *,
        error_class: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        if self._translation_audit_run_id is None:
            return
        try:
            chinese_coverage = (
                sum(bool(str(segment.get("zh_text") or "").strip()) for segment in segments) / len(segments)
                if segments else 0.0
            )
            vocabulary_segments = sum(bool(segment.get("vocab")) for segment in segments)
            PipelineDB().finish_ai_processing_run(
                self._translation_audit_run_id,
                status=status,
                final_provider=candidate.provider if candidate else None,
                fallback_used=fallback_used,
                quality_score=quality_score,
                chinese_coverage=chinese_coverage,
                vocabulary_segments=vocabulary_segments,
                quality_status=quality_status,
                error_class=error_class,
                error_message=error_message,
            )
        except Exception as exc:
            logger.warning("[AIAudit] failed to finish translation audit: %s", exc)

    def _apply_selected_translation_candidate(
        self,
        segments: List[Dict[str, Any]],
        candidate: SubtitleTranslationCandidate,
        texts: List[str],
        translation_context: str,
    ) -> None:
        """应用最终选中的 provider-neutral 候选，并按需补齐 vocab。"""
        apply_translation_candidate(segments, candidate)
        if not candidate.supports_vocab:
            self._align_vocab_after_plain_translation(texts, segments, translation_context, candidate.provider)

    def _build_translation_candidate(
        self,
        provider: str,
        texts: List[str],
        translation_context: str,
    ) -> Optional[SubtitleTranslationCandidate]:
        """按 provider 名称构建字幕翻译候选。"""
        if provider == "gemini":
            return self._build_gemini_candidate(texts, translation_context)
        if provider == "deepseek":
            return self._build_deepseek_candidate(texts, translation_context)
        if provider == "google":
            return self._build_google_candidate(texts)
        logger.warning("[Translate] Unknown provider ignored: %s", provider)
        return None

    def _build_gemini_candidate(
        self,
        texts: List[str],
        translation_context: str,
    ) -> Optional[SubtitleTranslationCandidate]:
        """Gemini 主译：翻译 + vocab 天然对齐。"""
        used_models: List[str] = []
        try:
            gemini_results = extract_vocab_batch(
                texts,
                chinese_translations=None,
                context_text=translation_context,
                model_out=used_models,
            )
        except Exception as e:
            logger.warning(f"Gemini translation/vocab extraction failed: {e}")
            self._last_provider_error = str(e)
            gemini_results = None

        if gemini_results:
            logger.info("Gemini translation succeeded. Using Gemini as primary translator.")
            return SubtitleTranslationCandidate(
                provider="Gemini",
                translations=[res.get("translation", "") for res in gemini_results],
                vocabs=[res.get("vocab", {}) for res in gemini_results],
                supports_vocab=True,
                model=",".join(used_models) or None,
            )
        self._last_provider_error = self._last_provider_error or "Gemini returned no aligned candidate"
        return None

    def _build_deepseek_candidate(
        self,
        texts: List[str],
        translation_context: str,
    ) -> Optional[SubtitleTranslationCandidate]:
        """DeepSeek：对比开关开启后一次返回翻译与 vocab。"""
        # 旧的测试替身没有新开关：保留旧 plain provider 兼容路径；真实 Settings 默认关闭，
        # 等 A/B 完成后再开启一体化候选。
        if not hasattr(settings, "enable_deepseek_vocab_fallback"):
            translated = translate_batch_deepseek(texts, context_text=translation_context)
            return (
                SubtitleTranslationCandidate(provider="DeepSeek", translations=translated)
                if translated else None
            )
        if not settings.enable_deepseek_vocab_fallback:
            return None
        errors: List[str] = []
        results = translate_batch_with_vocab_deepseek(
            texts,
            context_text=translation_context,
            error_out=errors,
        )
        if results:
            logger.info("DeepSeek produced a subtitle translation+vocab candidate.")
            return SubtitleTranslationCandidate(
                provider="DeepSeek",
                translations=[res.get("translation", "") for res in results],
                vocabs=[res.get("vocab", {}) for res in results],
                supports_vocab=True,
            )
        self._last_provider_error = "; ".join(errors) or "DeepSeek returned no aligned candidate"
        return None

    def _build_google_candidate(self, texts: List[str]) -> SubtitleTranslationCandidate:
        """Google Translate 终级 fallback：仅翻译，无 vocab。"""
        logger.info("Google Translate produced a subtitle translation candidate (no vocab alignment).")
        gt_translated = _google_batch_fallback(texts, src_lang="auto", target_lang=self.target_lang)
        if not gt_translated or any(not text or not text.strip() for text in gt_translated[:len(texts)]):
            self._last_provider_error = "Google returned empty translation"
        return SubtitleTranslationCandidate(provider="Google", translations=gt_translated)

    def _align_vocab_after_plain_translation(
        self,
        texts: List[str],
        segments: List[Dict[str, Any]],
        translation_context: str,
        provider: str,
    ) -> None:
        """Google 终级翻译后尝试用 Gemini 对齐模式补 vocab。"""
        try:
            zh_texts = [seg.get('zh_text', '') for seg in segments]
            vocab_results = extract_vocab_batch(
                texts,
                chinese_translations=zh_texts,
                context_text=translation_context,
            )
            if vocab_results:
                logger.info("Gemini vocab alignment succeeded (post-%s).", provider)
                for i, res in enumerate(vocab_results):
                    if i < len(segments):
                        segments[i]['vocab'] = res.get('vocab', {})
            else:
                logger.info("Gemini vocab alignment also failed. Proceeding without vocab.")
        except Exception as e:
            logger.warning(f"Gemini vocab alignment failed: {e}. Proceeding without vocab.")

    def _guard_translation_quality(
        self,
        source_texts: List[str],
        segments: List[Dict[str, Any]],
        *,
        provider: str,
        final_provider: bool = True,
        quality_context: SubtitleTranslationQualityContext | None = None,
    ) -> bool:
        """翻译后事实保真审计并返回候选是否可接受。"""
        translated_texts = [seg.get("zh_text", "") for seg in segments]
        decision = self._evaluate_translation_quality(
            source_texts,
            translated_texts,
            provider=provider,
            final_provider=final_provider,
            quality_context=quality_context,
        )
        self._record_translation_quality_decision(
            decision,
            provider=provider,
            final_provider=final_provider,
            selected=decision.accepted,
        )

        if decision.should_fallback:
            self._write_translation_quality_report()
            logger.warning(
                "[TranslationGuard][%s] Blocking issue found; falling back to next provider: %s",
                provider,
                decision.blocking_summary(),
            )
            return False
        if decision.should_fail:
            self._write_translation_quality_report()
            raise VideoProcessingError(
                f"Translation quality guard blocked {provider} output: {decision.blocking_summary()}"
            )
        return True

    def _evaluate_translation_quality(
        self,
        source_texts: List[str],
        translated_texts: List[str],
        *,
        provider: str,
        final_provider: bool,
        quality_context: SubtitleTranslationQualityContext | None,
    ) -> SubtitleTranslationQualityDecision:
        """只评估候选质量，不修改字幕段或审计状态。"""
        fallback_context_text = "\n".join(source_texts)
        decision = evaluate_subtitle_translation_candidate(
            source_texts,
            translated_texts,
            provider=provider,
            final_provider=final_provider,
            context_text=fallback_context_text,
            quality_context=quality_context,
            enable_numeric_checks=getattr(settings, "enable_translation_numeric_guard", True),
        )

        # TODO 临时处理：量化误杀（金额单位漂移/事件方向偏差）和频道策略误判高发阶段，先保证发布可继续。
        # 长期要求：恢复阻断语义后关闭开关，改由更细粒度规则修复。
        if getattr(settings, "enable_translation_quality_fail_open", False) and decision.blocking_issues:
            logger.warning(
                "[TranslationGuard] TEMP_FAIL_OPEN: blocking quality issues ignored (provider=%s)."
                " Issues: %s",
                provider,
                decision.blocking_summary(),
            )
            return SubtitleTranslationQualityDecision(
                provider=decision.provider,
                accepted=True,
                status="passed_temporarily",
                action="accept",
                warning_issues=[*decision.warning_issues, *decision.blocking_issues],
                blocking_issues=[],
                quality_context=decision.quality_context,
            )

        return decision

    def _record_translation_quality_decision(
        self,
        decision: SubtitleTranslationQualityDecision,
        *,
        provider: str,
        final_provider: bool,
        selected: bool,
    ) -> Dict[str, Any]:
        """记录质量决策审计事件并输出 warning 日志。"""
        for issue in decision.warning_issues:
            logger.warning(
                "[TranslationGuard][%s][%s] %s | source=%s translation=%s",
                provider,
                issue.code,
                issue.message,
                issue.source_signal,
                issue.translation_signal,
            )

        event = decision.to_audit_event(final_provider=final_provider)
        event["selected"] = selected
        self._translation_quality_audit.append(event)
        return event

    def _write_translation_quality_report(self) -> None:
        """写出字幕翻译质量审计报告，供后续统计和排障。"""
        if not self._translation_quality_audit:
            return
        report_path = self.input_path.with_suffix(".translation_quality.json")
        payload = {
            "input": str(self.input_path),
            "src_lang": self.src_lang,
            "target_lang": self.target_lang,
            "events": self._translation_quality_audit,
        }
        try:
            report_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"[TranslationGuard] quality report → {report_path}")
        except Exception as e:
            logger.warning(f"[TranslationGuard] failed to write quality report: {e}")

    def _load_model(self):
        """加载 Whisper 模型"""
        if not self.model:
            logger.info(f"Loading Whisper model: {self.model_size} on {self.device}...")
            self.model = whisper.load_model(self.model_size, device=self.device)
            logger.info("Model loaded.")

# 辅助 import，防止循环或者缺少
from ..utils.time_utils import seconds_to_time_string

if __name__ == "__main__":
    # 简单的测试入口
    print("AutoCaptionProcessor module loaded successfully.")

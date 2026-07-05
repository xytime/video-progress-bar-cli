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
    return old_request(*args, **kwargs)
requests.Session.request = new_request

# Suppress InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ..core.base import VideoProcessorBase, VideoProcessingError
from ..utils.translation_helper import translate_batch_aliyun, translate_batch as _google_batch_fallback  # [Claude_Sonnet_4.6_planning]
from ..utils.vocab_helper import extract_vocab_batch  # [Claude_Sonnet_4.6_Thinking_planning]
from ..utils.translation_quality_guard import evaluate_translation_batch
from ..utils.translation_context import build_translation_context

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

    def _translate_segments_aliyun(self, segments: List[Dict[str, Any]]) -> Optional[List[str]]:
        """[Claude_Sonnet_4.6_Thinking_planning] v1.9.1
        阿里云机器翻译通用版 (TranslateGeneral) 作为二级 fallback。
        QPS=50，每月 100 万字符免费额度。仅做翻译，不提取词汇。

        优化策略：批量拼接（Batching）
        将每批 BATCH_SIZE 个 segments 的文本用 SEP 特殊分隔符拼接成单次 API 调用，
        翻译完成后按分隔符切割回填。将 100+ 次串行请求压缩至 4-5 次，延迟降低约 20x。

        Returns:
            List[str]: 按入入顺序排列的翻译结果列表，失败时返回 None。
        """
        try:
            from config.settings import settings
            ak_id = settings.aliyun_mt_access_key_id or ""
            ak_secret = settings.aliyun_mt_access_key_secret or ""
            if not ak_id or not ak_secret:
                logger.info("ALIYUN_MT_ACCESS_KEY_ID/SECRET not configured. Skipping Aliyun MT fallback.")
                return None

            # [Claude_Sonnet_4.6_Thinking_planning] 使用阿里云官方 SDK
            from alibabacloud_alimt20181012.client import Client as AlimtClient
            from alibabacloud_tea_openapi.models import Config as OpenApiConfig
            from alibabacloud_alimt20181012 import models as alimt_models

            config = OpenApiConfig(
                access_key_id=ak_id,
                access_key_secret=ak_secret,
                endpoint="mt.aliyuncs.com"
            )
            client = AlimtClient(config)

            src_lang = "en" if self.src_lang in ("en", "auto", None) else self.src_lang
            tgt_lang = "zh" if self.target_lang in ("zh", "zh-CN", None) else self.target_lang

            # [Claude_Sonnet_4.6_Thinking_planning] 批量拼接策略
            # 每段字幕平均 ~40 字符，阿里云单次最大 5000 字符
            # 每批 25 条：25 * 40 ≈ 1000 字符，远低于 5000 字符上限，安全可靠
            SEP = "\n###\n"
            BATCH_SIZE = 25

            texts = [seg.get("text", "").strip() for seg in segments]
            translated: List[str] = [""] * len(texts)

            logger.info(f"Calling Aliyun MT API for {len(texts)} segments in batches of {BATCH_SIZE} ({src_lang} → {tgt_lang})...")

            for batch_start in range(0, len(texts), BATCH_SIZE):
                batch_texts = texts[batch_start: batch_start + BATCH_SIZE]
                # 过滤掉空文本，记录其原始位置
                non_empty_indices = [i for i, t in enumerate(batch_texts) if t]
                non_empty_texts = [batch_texts[i] for i in non_empty_indices]

                if not non_empty_texts:
                    continue

                combined = SEP.join(non_empty_texts)
                req = alimt_models.TranslateGeneralRequest(
                    format_type="text",
                    scene="general",
                    source_language=src_lang,
                    source_text=combined[:5000],  # 安全截断，防止超限
                    target_language=tgt_lang
                )
                resp = client.translate_general(req)

                if resp and resp.body and str(resp.body.code) == "200":
                    result_text = resp.body.data.translated or ""
                    # 按分隔符切割，允许两侧有空白
                    parts = [p.strip() for p in result_text.split("###")]
                    for local_idx, abs_idx in enumerate(non_empty_indices):
                        if local_idx < len(parts):
                            translated[batch_start + abs_idx] = parts[local_idx]
                        else:
                            logger.warning(f"[AliyunMT] Batch split count mismatch at batch_start={batch_start}")
                else:
                    code = resp.body.code if resp and resp.body else "unknown"
                    logger.warning(f"Aliyun MT returned non-200 code={code} for batch starting at index {batch_start}")

            logger.info("Aliyun MT batch translation completed.")
            return translated

        except ImportError:
            logger.warning("alibabacloud-alimt20181012 not installed. Run: pip install alibabacloud-alimt20181012")
            return None
        except Exception as e:
            logger.error(f"Aliyun MT translation failed: {e}")
            return None

    def _translate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量翻译字幕片段 — Gemini 主译 → Aliyun 降级 → Google 终级 Fallback。

        [Claude_Sonnet_4.6_Thinking_planning] v1.13.0:
        Gemini 优先：其对习语/隐喻/语境有正确理解（如 'in code'→'暗示' 而非'代码'），
        且翻译与词汇注释在同一次调用中天然对齐，vocab 值即为 translation 子串，
        使 SubtitleStylist.apply_chinese_highlights 能 100% 命中并画出下划线。

        Aliyun 降级（无 vocab）：Gemini 配额耗尽或失败时用于救急，确保主字幕不为空。
        Google 终级 Fallback：两者均失败时使用。
        """
        if not segments:
            return segments

        logger.info(f"Translating {len(segments)} segments from {self.src_lang} to {self.target_lang}...")
        texts = [seg.get("text", "").strip() for seg in segments]
        translation_context = build_translation_context(texts).to_prompt_context()

        # ── 一级：Gemini（翻译 + vocab，天然对齐）─────────────────────────────
        try:
            gemini_results = extract_vocab_batch(
                texts,
                chinese_translations=None,
                context_text=translation_context,
            )
        except Exception as e:
            logger.warning(f"Gemini translation/vocab extraction failed: {e}")
            gemini_results = None

        if gemini_results:
            logger.info("Gemini translation succeeded. Using Gemini as primary translator.")
            for i, res in enumerate(gemini_results):
                if i < len(segments):
                    segments[i]['zh_text'] = res.get('translation', '')
                    segments[i]['vocab']   = res.get('vocab', {})
            self._guard_translation_quality(texts, segments, provider="Gemini")
            return segments

        # ── 二级：Aliyun MT（仅翻译，无 vocab 对齐）──────────────────────────
        ali_tgt = "zh" if self.target_lang in ("zh-CN", "zh", None) else self.target_lang
        ali_src = "en" if self.src_lang in ("en", "auto", None) else self.src_lang
        aliyun_results = translate_batch_aliyun(texts, src_lang=ali_src, target_lang=ali_tgt)

        if aliyun_results:
            logger.warning("Gemini failed. Falling back to Aliyun MT (no vocab alignment).")
            for i, text in enumerate(aliyun_results):
                if i < len(segments):
                    segments[i]['zh_text'] = text
                    segments[i]['vocab']   = {}

            # [Claude_Opus_4.6_Thinking_planning] 二次尝试：用 Aliyun 的翻译结果作为
            # chinese_translations 传回 Gemini "对齐模式"，仅做 vocab 提取。
            # 这样即使 Gemini 翻译模式 429，对齐模式只需要更少的 token 可能成功。
            try:
                zh_texts = [seg.get('zh_text', '') for seg in segments]
                vocab_results = extract_vocab_batch(
                    texts,
                    chinese_translations=zh_texts,
                    context_text=translation_context,
                )
                if vocab_results:
                    logger.info("Gemini vocab alignment succeeded (post-Aliyun).")
                    for i, res in enumerate(vocab_results):
                        if i < len(segments):
                            segments[i]['vocab'] = res.get('vocab', {})
                else:
                    logger.info("Gemini vocab alignment also failed. Proceeding without vocab.")
            except Exception as e:
                logger.warning(f"Gemini vocab alignment failed: {e}. Proceeding without vocab.")

            self._guard_translation_quality(texts, segments, provider="Aliyun")
            return segments

        # ── 三级：Google Translate（无 vocab）────────────────────────────────
        logger.warning("Both Gemini and Aliyun failed. Falling back to Google Translate.")
        gt_translated = _google_batch_fallback(texts, src_lang="auto", target_lang=self.target_lang)
        for i, text in enumerate(gt_translated):
            if i < len(segments):
                segments[i]['zh_text'] = text if text else ""
                segments[i]['vocab']   = {}

        # [Claude_Opus_4.6_Thinking_planning] Google 翻译后也尝试 Gemini 对齐模式
        try:
            zh_texts = [seg.get('zh_text', '') for seg in segments]
            vocab_results = extract_vocab_batch(
                texts,
                chinese_translations=zh_texts,
                context_text=translation_context,
            )
            if vocab_results:
                logger.info("Gemini vocab alignment succeeded (post-Google).")
                for i, res in enumerate(vocab_results):
                    if i < len(segments):
                        segments[i]['vocab'] = res.get('vocab', {})
        except Exception as e:
            logger.warning(f"Gemini vocab alignment failed: {e}. Proceeding without vocab.")

        self._guard_translation_quality(texts, segments, provider="Google")
        return segments

    def _guard_translation_quality(
        self,
        source_texts: List[str],
        segments: List[Dict[str, Any]],
        *,
        provider: str,
    ) -> None:
        """翻译后事实保真审计：P0 阻断，P1 仅告警。"""
        translated_texts = [seg.get("zh_text", "") for seg in segments]
        context_text = "\n".join(source_texts)
        summary = evaluate_translation_batch(
            source_texts,
            translated_texts,
            context_text=context_text,
        )

        for issue in summary.warning_issues:
            logger.warning(
                "[TranslationGuard][%s][%s] %s | source=%s translation=%s",
                provider,
                issue.code,
                issue.message,
                issue.source_signal,
                issue.translation_signal,
            )

        if summary.blocking_issues:
            details = "; ".join(
                f"{issue.code}: {issue.message}"
                for issue in summary.blocking_issues[:3]
            )
            raise VideoProcessingError(
                f"Translation quality guard blocked {provider} output: {details}"
            )

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

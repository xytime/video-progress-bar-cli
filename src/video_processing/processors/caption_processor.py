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

    def _translate_segments_gemini(self, segments: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """[Gemini_3.5_Flash_planning] 使用 Gemini API 进行高质量批翻译与重点单词释义提取"""
        try:
            from config.settings import settings
            api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                logger.warning("GEMINI_API_KEY not found. Fallback to Google Translate.")
                return None
                
            # [Claude_Sonnet_4.6_Thinking_planning] 迁移至 google.genai SDK v2.6.0，废弃已停止维护的 google.generativeai
            from google import genai as _genai
            from google.genai import types as _genai_types
            _client = _genai.Client(api_key=api_key)
            
            texts = [seg['text'].strip() for seg in segments]

            # [Gemini_3.5_Flash_planning] 升级提示词：要求词组的中文释义与翻译句子中的对应字符子串严格一致（不超过 3 个），方便画下划线
            prompt = (
                "You are an expert video subtitle translator and English educator. For each of the following English subtitle segments:\n"
                "1. Translate it into natural, native, and screen-friendly Chinese (zh-CN).\n"
                "2. Identify 2 to 3 key, academic, or difficult vocabulary words/phrases (CEFR B2-C2 or TOEFL/IELTS/GRE level) that are essential to the segment's meaning. Provide their concise Chinese definitions. CRITICAL: For each extracted word/phrase, its Chinese definition in the 'vocab' dictionary MUST be the exact substring as it appears in your translated 'translation' string (e.g. if the translation sentence uses '先驱' instead of '先驱者', use '先驱' as the definition). Do not extract common/easy words. If there are no difficult words, leave the vocabulary dictionary empty.\n"
                "Return a JSON array of objects (one for each segment in the exact same order and count). Each object must contain:\n"
                "- \"translation\": string (Chinese translation)\n"
                "- \"vocab\": object (keys are the exact English words/phrases as they appear in the text, values are their concise Chinese translations)\n\n"
                f"Input segments:\n{json.dumps(texts, ensure_ascii=False)}"
            )

            
            # [Claude_Sonnet_4.6_Thinking_planning] 指数退避重试 + 多模型 Fallback
            # P1 fix: retry_delay 从 4 压缩到 2（初始），min() 限制最大 8s，防止 pipeline 冻结过久
            # P3 fix: 非 429/RESOURCE_EXHAUSTED 的 fatal 错误立即 raise，不浪费时间遍历其他模型
            # [Gemini_3.5_Flash_planning] Fallback model switched to gemini-2.5-flash (which works under the current API key)
            models_to_try = ["gemini-3.5-flash", "gemini-2.5-flash"]
            response = None
            last_err = None

            for model_name in models_to_try:
                max_retries = 3
                retry_delay = 2  # [Claude_Sonnet_4.6_Thinking_planning] P1 fix: 初始 2s（原为 4s）
                for attempt in range(max_retries):
                    try:
                        logger.info(f"Calling Gemini API with {model_name} (attempt {attempt + 1}/{max_retries})...")
                        response = _client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=_genai_types.GenerateContentConfig(
                                response_mime_type="application/json"
                            )
                        )
                        break  # 成功，退出重试循环
                    except Exception as e:
                        last_err = e
                        err_msg = str(e)
                        is_rate_limit = (
                            "429" in err_msg
                            or "RESOURCE_EXHAUSTED" in err_msg
                            or "rate limit" in err_msg.lower()
                        )
                        if is_rate_limit:
                            if attempt < max_retries - 1:
                                wait = min(retry_delay, 8)  # [Claude_Sonnet_4.6_Thinking_planning] P1 fix: 上限 8s
                                logger.warning(f"{model_name} rate limited (429). Retrying in {wait}s... ({attempt + 1}/{max_retries})")
                                time.sleep(wait)
                                retry_delay *= 2
                                continue
                            # 429 且重试耗尽 → 尝试下一个模型
                            logger.warning(f"{model_name} exhausted all {max_retries} retries due to rate limiting. Falling back to next model.")
                            break
                        else:
                            # [Gemini_3.5_Flash_planning] 区分客户端致命错误与服务端/网络临时错误。
                            # 400/401/403 等配置错误立即 raise；但连接断开、500/503等允许 Fallback 尝试其他模型。
                            is_fatal_client_error = (
                                "400" in err_msg
                                or "401" in err_msg
                                or "403" in err_msg
                                or "API_KEY" in err_msg
                            )
                            if is_fatal_client_error:
                                logger.error(f"{model_name} fatal client error: {e}")
                                raise
                            else:
                                logger.warning(f"{model_name} non-fatal error: {e}. Falling back to next model.")
                                break
                if response is not None:
                    break

            if response is None:
                if last_err:
                    raise last_err
                raise Exception("Failed to get response from any Gemini model.")

            result = json.loads(response.text)
            
            if isinstance(result, dict) and "translations" in result:
                result = result["translations"]
            elif isinstance(result, dict) and "list" in result:
                result = result["list"]
                
            if isinstance(result, list) and len(result) == len(texts):
                logger.info("Gemini translation and vocabulary extraction completed successfully.")
                return result
            else:
                logger.warning(f"Gemini returned invalid translation list structure: {result}")
                return None
        except Exception as e:
            logger.error(f"Gemini translation failed: {e}")
            return None

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
        """批量翻译字幕片段 — 阿里云 MT → Gemini vocab → Google Translate 三级降级。

        [Claude_Sonnet_4.6_planning] v1.11.0:
        使用 translation_helper.translate_batch_aliyun 统一调用阿里云翻译，
        Google Translate fallback 亦通过 translation_helper 统一路由。
        Gemini 仅负责难词（vocab）提取，不再用于一级翻译。
        """
        if not segments:
            return segments

        logger.info(f"Translating {len(segments)} segments from {self.src_lang} to {self.target_lang}...")

        # 标准化语言代码（阿里云使用 "zh"，Google 使用 "zh-CN"）
        ali_tgt = "zh" if self.target_lang in ("zh-CN", "zh", None) else self.target_lang
        ali_src = "en" if self.src_lang in ("en", "auto", None) else self.src_lang

        # [Claude_Sonnet_4.6_planning] 优先调用阿里云 MT（通过 translation_helper 统一入口）
        texts = [seg.get("text", "").strip() for seg in segments]
        aliyun_results = translate_batch_aliyun(texts, src_lang=ali_src, target_lang=ali_tgt)

        # [Gemini_3.5_Flash_planning] 同时调用 Gemini 进行难词提取（允许失败降级）
        try:
            gemini_results = self._translate_segments_gemini(segments)
        except Exception as e:
            logger.warning(f"Gemini translation/vocab extraction failed (non-blocking fallback): {e}")
            gemini_results = None

        if aliyun_results:
            # 优先使用阿里云的翻译
            logger.info("Prioritizing Aliyun MT translation results.")
            for i, text in enumerate(aliyun_results):
                if i < len(segments):
                    segments[i]['zh_text'] = text
                    # 如果 Gemini 难词提取成功，则进行难词填充
                    if gemini_results and i < len(gemini_results):
                        segments[i]['vocab'] = gemini_results[i].get('vocab', {})
                    else:
                        segments[i]['vocab'] = {}
            return segments

        if gemini_results:
            # 阿里云失败，回退使用 Gemini 翻译与难词
            logger.warning("Aliyun MT failed. Falling back to Gemini translation and vocabulary.")
            for i, res in enumerate(gemini_results):
                if i < len(segments):
                    segments[i]['zh_text'] = res.get('translation', '')
                    segments[i]['vocab'] = res.get('vocab', {})
            return segments

        # 三级 fallback：Google Translate（通过 translation_helper 统一路由）
        logger.warning("Both Aliyun MT and Gemini failed. Falling back to Google Translate.")
        gt_translated = _google_batch_fallback(texts, src_lang="auto", target_lang=self.target_lang)

        for i, text in enumerate(gt_translated):
            if i < len(segments):
                segments[i]['zh_text'] = text if text else ""
                segments[i]['vocab'] = {}  # fallback with empty vocabulary

        return segments

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

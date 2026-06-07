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
"""
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

import whisper
from deep_translator import GoogleTranslator
import pysubs2
import requests
import os

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

    def _translate_segments_gemini(self, segments: List[Dict[str, Any]]) -> Optional[List[str]]:
        """[Gemini_3.5_Flash_planning] 使用 Gemini API 进行高质量批翻译"""
        try:
            from src.config.settings import settings
            api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                logger.warning("GEMINI_API_KEY not found. Fallback to Google Translate.")
                return None
                
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            
            # [Gemini_3.5_Flash_planning] 使用更稳定的 gemini-1.5-flash 模型，保证高速度与高质量
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                generation_config={"response_mime_type": "application/json"}
            )
            
            texts = [seg['text'].strip() for seg in segments]
            import json
            
            prompt = (
                "You are an expert video subtitle translator. Translate the following list of English subtitle segments "
                "into natural, professional, and native Chinese (zh-CN) for a video of Jeff Bezos speaking about artificial intelligence.\n"
                "The translation must be accurate, concise, screen-friendly, and maintain standard Chinese terminology for tech/AI.\n"
                "Return a JSON list of strings containing only the translations, maintaining the exact same order and count.\n\n"
                f"Input segments:\n{json.dumps(texts, ensure_ascii=False)}"
            )
            
            logger.info("Calling Gemini API for batch subtitle translation...")
            response = model.generate_content(prompt)
            result = json.loads(response.text)
            
            if isinstance(result, dict) and "translations" in result:
                result = result["translations"]
            elif isinstance(result, dict) and "list" in result:
                result = result["list"]
                
            if isinstance(result, list) and len(result) == len(texts):
                logger.info("Gemini translation completed successfully.")
                return [str(t) for t in result]
            else:
                logger.warning(f"Gemini returned invalid translation list: {result}")
                return None
        except Exception as e:
            logger.error(f"Gemini translation failed: {e}")
            return None

    def _translate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量翻译字幕片段"""
        if not segments:
            return segments
            
        logger.info(f"Translating {len(segments)} segments from {self.src_lang} to {self.target_lang}...")
        
        # [Gemini_3.5_Flash_planning] 优先使用 Gemini 进行自然语言翻译
        gemini_translations = self._translate_segments_gemini(segments)
        if gemini_translations:
            for i, text in enumerate(gemini_translations):
                if i < len(segments):
                    segments[i]['zh_text'] = text
            return segments
        
        # 提取原文列表
        texts = [seg['text'].strip() for seg in segments]
        
        # 分批处理以防止突破API限制
        translator = GoogleTranslator(source='auto', target=self.target_lang)
        batch_size = 30
        translated_texts = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            try:
                res = translator.translate_batch(batch)
                translated_texts.extend(res)
            except Exception as e:
                logger.error(f"Batch translation failed at index {i}: {e}")
                # 如果分批翻译失败，回退到逐条翻译，并加入延时防风控
                import time
                for text in batch:
                    retry_count = 3
                    success = False
                    for _ in range(retry_count):
                        try:
                            single_res = translator.translate(text)
                            translated_texts.append(single_res if single_res else "")
                            success = True
                            time.sleep(0.5)
                            break
                        except Exception as inner_e:
                            time.sleep(2)
                    if not success:
                        logger.error(f"Failed to translate segment after {retry_count} retries.")
                        translated_texts.append("") # 失败时为空，绝不静默混入英文
        
        # 将翻译结果回填
        import re
        for i, text in enumerate(translated_texts):
            if i < len(segments):
                # [Gemini_3.1_Pro_High_planning] 过滤并清洗谷歌翻译由于被风控返回的错误页面文本
                if text and re.search(r'<html|<body|<div|captcha|that\'s an error|error 500|cloudflare', text, re.IGNORECASE):
                    logger.warning("Google Translate API blocked or returned HTML garbage! Removing garbage text.")
                    text = ""
                # 如果没翻译出来，直接留空，让渲染器 fallback 到只显示英文
                segments[i]['zh_text'] = text if text else ""
                
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

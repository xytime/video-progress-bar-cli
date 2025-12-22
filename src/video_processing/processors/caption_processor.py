"""智能字幕处理器 - 提供语音转文字、翻译及ASS字幕生成功能"""
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

import whisper
from deep_translator import GoogleTranslator
import pysubs2

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

    def process(self, **kwargs) -> Path:
        """
        处理视频：提取音频 -> 转录 -> (翻译) -> (生成ASS) -> (烧录)
        """
        logger.info(f"Processing video: {self.input_path} with style: {self.style}")
        
        # 1. 确保模型已加载
        self._load_model()
        
        # 2. 提取音频
        audio_path = self._extract_audio()
        logger.info(f"Audio extracted to: {audio_path}")
        
        try:
            # 3. 转录
            segments = self._transcribe_audio(audio_path)
            
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
            if audio_path.exists():
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
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(self.input_path),
            "-vf", f"ass='{escaped_ass_path}'",
            "-c:a", "copy",  # 音频流直接复制，不重编码
            str(output_path)
        ]
        
        logger.info(f"Burning subtitles: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if not output_path.exists():
            raise VideoProcessingError("Subtitle burn-in failed")
            
        return output_path

    def _generate_ass_file(self, segments: List[Dict[str, Any]]) -> Path:
        """生成双语 ASS 字幕文件"""
        subs = pysubs2.SSAFile()
        
        # 获取样式配置
        config = CAPTION_STYLES[self.style]
        
        # 手动解析样式参数，因为 pysubs2.Color 需要 RGB
        if self.style == "default":
             bg_color = pysubs2.Color(0, 0, 0, config.get('bg_alpha', 100))
             border_style = config.get('border_style', 3)
             outline = config.get('outline', 0)
             shadow = config.get('shadow', 0)
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
            fontsize=20, 
            primarycolor=pysubs2.Color(255, 255, 255),
            backcolor=bg_color,
            borderstyle=border_style,
            outline=outline,
            shadow=shadow,
            alignment=2, # Bottom Center
            marginv=20,
            fontname="Arial Unicode MS"
        )
        subs.styles["Default"] = style
        
        for seg in segments:
            start_ms = int(seg['start'] * 1000)
            end_ms = int(seg['end'] * 1000)
            en_text = seg.get('text', '').strip()
            zh_text = seg.get('zh_text', '').strip()
            
            # Wrap text to avoid overflow
            en_text = textwrap.fill(en_text, width=60)
            zh_text = textwrap.fill(zh_text, width=30)
            
            # 双语格式化
            if zh_text and en_text:
                # 1. 英文 (下层，小字)
                text_en = f"{{\\c{en_c}\\fs14}}{en_text}"
                evt_en = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=text_en)
                evt_en.marginv = 10 # Bottom 10
                subs.events.append(evt_en)
                
                # 2. 中文 (上层，标准字号)
                en_lines = len(en_text.split('\\n')) # textwrap returns \n but ASS uses \N? No, pysubs2 handles \n as \N usually. 
                # Check pysubs2 behavior: it treats \n as literal newline in ASS I think.
                # Actually textwrap uses \n. pysubs2 might need replacement to \N.
                # Let's replace \n with \N explicitly to be safe for ASS.
                en_text = en_text.replace('\n', '\\N')
                zh_text = zh_text.replace('\n', '\\N')
                
                en_lines = len(en_text.split('\\N'))
                margin_zh = 10 + (en_lines * 18) + 5
                
                # Recalculate text with \N
                text_en = f"{{\\c{en_c}\\fs14}}{en_text}"
                # Re-create event
                subs.events[-1].text = text_en
                
                text_zh = f"{{\\c{zh_c}}}{zh_text}"
                evt_zh = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=text_zh)
                evt_zh.marginv = int(margin_zh)
                subs.events.append(evt_zh)
                
            elif zh_text:
                zh_text = zh_text.replace('\n', '\\N')
                text = f"{{\\c{zh_c}}}{zh_text}"
                evt = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=text)
                subs.events.append(evt)
            else:
                en_text = en_text.replace('\n', '\\N')
                text = f"{{\\c{en_c}}}{en_text}"
                evt = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=text)
                subs.events.append(evt)
            
        # 保存到与输入同一目录
        ass_path = self.input_path.with_suffix('.ass')
        subs.save(str(ass_path))
        return ass_path

    def _extract_audio(self) -> Path:
        """从视频提取音频到临时 .wav 文件 (16kHz, mono for Whisper)"""
        import tempfile
        import subprocess
        
        temp_dir = Path(tempfile.gettempdir())
        audio_path = temp_dir / f"{self.input_path.stem}_temp_audio.wav"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(self.input_path),
            "-vn",  # No video
            "-acodec", "pcm_s16le",
            "-ar", "16000",  # Whisper likes 16k
            "-ac", "1",      # Mono
            str(audio_path)
        ]
        
        logger.debug(f"Extracting audio: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
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
        return result["segments"]

    def _translate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量翻译字幕片段"""
        if not segments:
            return segments
            
        logger.info(f"Translating {len(segments)} segments from {self.src_lang} to {self.target_lang}...")
        
        # 提取原文列表
        texts = [seg['text'].strip() for seg in segments]
        
        # 批量翻译
        try:
            translator = GoogleTranslator(source='auto', target=self.target_lang)
            # GoogleTranslator has a char limit per request (usually 5k chars).
            # deep_translator's translate_batch mostly handles this, but large batches might fail.
            # safe approach: chunking if efficient, but for now try direct batch.
            translated_texts = translator.translate_batch(texts)
            
            # 将翻译结果回填
            for i, text in enumerate(translated_texts):
                segments[i]['zh_text'] = text
                
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            # Fallback: leave zh_text empty or equal to source
            for seg in segments:
                seg['zh_text'] = ""
                
        return segments

    def _load_model(self):
        """加载 Whisper 模型"""
        if not self.model:
            logger.info(f"Loading Whisper model: {self.model_size} on {self.device}...")
            self.model = whisper.load_model(self.model_size, device=self.device)
            logger.info("Model loaded.")

# 辅助 import，防止循环或者缺少
import os
from ..utils.time_utils import seconds_to_time_string

if __name__ == "__main__":
    # 简单的测试入口
    print("AutoCaptionProcessor module loaded successfully.")

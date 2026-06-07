# -*- coding: utf-8 -*-
"""竖屏视频处理器 (9:16) — 提供三段式布局、字幕与配音生成

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking | 初始创建，支持三段式与边缘配音/本地配音 |
| 1.1.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 集成 CosyVoice 语音合成 Provider 支持并实现 TTS 说话时背景音动态闪避 (Ducking) 功能，标注 # [Gemini_3.5_Flash_planning] |
| 1.1.1   | 2026-05-28 | Gemini_3.5_Flash_planning | 新增 mute_original 参数支持，允许将原视频静音只保留 TTS 音轨，标注 # [Gemini_3.5_Flash_planning] |
| 1.2.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 新增 tts_volume 和 tts_speech_rate 支持，并在分段混合前引入 atempo 自动加速防重叠安全阀机制，标注 # [Gemini_3.5_Flash_planning] |
| 1.3.0   | 2026-05-28 | Gemini_2.5_Pro_planning  | TTSEngine 默认 fallback voice 改为 "auto"，自动从精选播音音色池随机选取，标注 # [Gemini_2.5_Pro_planning] |
| 1.4.0   | 2026-05-28 | Gemini_3.5_Flash_planning | [已废弃] 非中文视频自动开启 TTS 配音逻辑（不符合默认行为需求，已在 1.5.0 移除） |
| 1.5.0   | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 移除"非中文视频自动开启 TTS"行为：TTS 默认关闭，只有用户通过 --tts-cosy / --tts-real 参数，或 Telegram /tts 命令明确指定时才启用 |
| 1.6.0   | 2026-06-07 | Gemini_3.5_Flash_planning | Handle audio-less videos gracefully during vertical subtitle burn-in. |
| 1.7.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 竖屏视频输入时将字幕起始 y 坐标调整为 1400，防止遮挡画面中心内容，标注 # [Gemini_3.5_Flash_planning] |
| 1.8.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 双语字幕中英文顺序互换，英文设为金色（Gold），字号与中文接近一致（0.82倍），标注 # [Gemini_3.5_Flash_planning] |
"""
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

import pysubs2

from .caption_processor import AutoCaptionProcessor, CAPTION_STYLES, VideoProcessingError
from ..utils.layout import VerticalLayout
from ..core.tts_engine import TTSEngine, TTSProvider
from ..core.audio_mixer import AudioMixer

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
        tts_speech_rate: float = 1.0  # [Gemini_3.5_Flash_planning]
    ):
        super().__init__(
            input_path, output_path, model_size, src_lang, target_lang, device, style
        )
        self.title = title or input_path.stem  # Default to filename if empty
        self.bg_blur = bg_blur
        self.font_path = font_path
        self.font_size = font_size
        self.bilingual = bilingual
        self.tts_provider = tts_provider
        self.tts_voice = tts_voice  # [Gemini_3.5_Flash_planning]
        self.mute_original = mute_original  # [Gemini_3.5_Flash_planning]
        self.tts_volume = tts_volume  # [Gemini_3.5_Flash_planning]
        self.tts_speech_rate = tts_speech_rate  # [Gemini_3.5_Flash_planning]
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
        
        # Calculate dynamic wrap width
        # User feedback: Width can be wider (currently looks like 80%).
        # Increase safety factor to 0.96 (approx 1036px)
        safe_width = int(VerticalLayout.CANVAS_WIDTH * 0.96)
        
        # Approximate char width factor
        # Fonts vary, but usually 1 em = font_size.
        # We'll allow a bit more density. 
        # [Gemini_3.5_Flash_planning] English is primary (font_size), Chinese is secondary (font_size * 0.82)
        wrap_width_zh = max(10, int(safe_width / (font_size * 0.82)))
        wrap_width_en = max(20, int(safe_width / (font_size * 0.45)))
        
        import textwrap

        # Get base config
        config = CAPTION_STYLES.get(self.style, CAPTION_STYLES["default"])
        
        
        # User feedback: Subtitles shouldn't jump around (fixed top position) 
        # and shouldn't overlap video.
        # Solution: Use Top-Center Alignment (8) and fixed MarginV from Top.
        # Video Top = 350. Video Height (16:9) ~ 607. Video Bottom ~ 957.
        # Let's start subtitles at Y = 1000.
        # [Gemini_3.5_Flash_planning] For vertical videos, move subtitles down to Y=1400 (bottom safety/blank zone)
        # to avoid covering center content. For landscape videos, keep at Y=1000.
        try:
            video_w, video_h = self._get_video_resolution()
            is_vertical_input = video_w < video_h
        except Exception as e:
            logger.warning(f"Could not probe video size for subtitle margin, fallback to landscape layout: {e}")
            is_vertical_input = False

        if is_vertical_input:
            subtitle_top_y = 1400
        else:
            subtitle_top_y = 1000
        
        style = pysubs2.SSAStyle(
            fontsize=font_size,
            primarycolor=pysubs2.Color(255, 255, 255),
            backcolor=pysubs2.Color(0, 0, 0, 0), 
            borderstyle=1, 
            outline=2,
            shadow=0,
            alignment=8, # Top Center (Fixes jumping, grows downwards)
            marginv=subtitle_top_y,
            fontname="Arial Unicode MS"
        )
        subs.styles["Default"] = style
        
        zh_c = config['zh_color']
        # [Gemini_3.5_Flash_planning] 英文颜色强制设为金色 (Gold)
        gold_c = "&H00D7FF"

        for seg in segments:
            start_ms = int(seg['start'] * 1000)
            end_ms = int(seg['end'] * 1000)
            en_text = seg.get('text', '').strip().replace('\n', ' ')
            zh_text = seg.get('zh_text', '').strip().replace('\n', ' ')
            
            # Wrap Text
            if zh_text:
                zh_text = textwrap.fill(zh_text, width=wrap_width_zh).replace('\n', '\\N')
            if en_text:
                en_text = textwrap.fill(en_text, width=wrap_width_en).replace('\n', '\\N')
            
            # [Gemini_3.5_Flash_planning] 双语字幕互调：英文在上（金色），中文在下（白色/默认，0.82倍大小）
            if zh_text and en_text:
                if self.bilingual:
                    text = f"{{\\c{gold_c}}}{en_text}\\N{{\\fs{int(font_size*0.82)} \\c{zh_c}}}{zh_text}"
                else:
                    text = f"{{\\c{zh_c}}}{zh_text}"
            elif zh_text:
                text = f"{{\\c{zh_c}}}{zh_text}"
            else:
                text = f"{{\\c{gold_c}}}{en_text}"

                
            evt = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=text)
            subs.events.append(evt)
            
        ass_path = self.input_path.with_suffix('.ass')
        subs.save(str(ass_path))
        return ass_path

    def _burn_subtitles(self, ass_path: Path) -> Path:
        """Compose 3-section layout using FFmpeg filter_complex"""
        
        output_path = self.output_path or self.input_path.parent / f"{self.input_path.stem}_vertical{self.input_path.suffix}"
        self.output_path = output_path
        
        # [Claude_Sonnet_4.6_Thinking_planning] v1.5.0: TTS 默认关闭。
        # 只有用户通过 --tts / --tts-cosy / --tts-real 参数，或 Telegram /tts 命令
        # 明确指定 tts_provider 后，才启用语音合成。非中文视频不再自动激活 TTS。
        if self.tts_provider:
            logger.info(f"[TTS] Provider explicitly set: {self.tts_provider}")


        generated_audio_track = None
        audio_segments = []  # [Gemini_3.5_Flash_planning] 声明为外部作用域变量，以供后面的 Ducking 计算使用
        if self.tts_provider and self.segments:
            logger.info(f"Generating TTS audio using provider: {self.tts_provider}")
            try:
                # Initialize Engine
                # [Gemini_3.5_Flash_planning] 支持 cosyvoice 配音服务
                if self.tts_provider == "indextts":
                    provider = TTSProvider.INDEXTTS
                elif self.tts_provider == "cosyvoice":
                    provider = TTSProvider.COSYVOICE
                else:
                    provider = TTSProvider.EDGE
                # [Gemini_2.5_Pro_planning] tts_voice 默认为 "auto"，触发精选播音池随机选取；用户也可传具体 voice ID 覆盖
                tts_engine = TTSEngine(
                    provider=provider,
                    cosyvoice_voice=self.tts_voice or "auto",
                    cosyvoice_volume=self.tts_volume,              # [Gemini_3.5_Flash_planning]
                    cosyvoice_speech_rate=self.tts_speech_rate    # [Gemini_3.5_Flash_planning]
                )
                
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
                    tts_engine.batch_generate(tts_items, audio_dir, voice_prompt="examples/test_audio.wav" if provider == TTSProvider.INDEXTTS else "onyx")
                    
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
        
        # Smart Truncate Title
        # 1080px width, fontsize=60. 
        # Max capacity approx 16-17 full-width chars.
        # We estimate width: Wide(>255)=1.0, Narrow=0.5
        max_em = 16.5
        current_em = 0
        display_title = ""
        for char in self.title:
            w = 1.0 if ord(char) > 255 else 0.5
            if current_em + w > max_em:
                display_title += "..."
                break
            current_em += w
            display_title += char
            
        title_text = display_title.replace("'", "'\\''").replace(":", "\\:")
        
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

        # Font file for drawtext
        font_cmd = f":fontfile='{self.font_path}'" 
        
        # Colors & Style Logic
        config = CAPTION_STYLES.get(self.style, CAPTION_STYLES["default"])
        
        def ass_to_ffmpeg_color(ass_hex: str) -> str:
            # ASS: &HBBGGRR -> FFmpeg: #RRGGBB
            clean = ass_hex.replace('&H', '').replace('&', '').strip()
            if len(clean) == 8: # AABBGGRR? usually ASS is BBGGRR in config dict here
                clean = clean[2:]
            if len(clean) == 6:
                b = clean[0:2]
                g = clean[2:4]
                r = clean[4:6]
                return f"#{r}{g}{b}"
            return "white" # fallback
            
        title_color = ass_to_ffmpeg_color(config['zh_color'])
        
        # Box Logic
        # Priority: Style Config > Bg Blur Fallback
        box_cmd = ""
        has_box = (config.get('border_style', 1) == 3)
        
        if has_box:
            # Use style's box color
            box_color = ass_to_ffmpeg_color(config.get('bg_color', '&H000000'))
            alpha = config.get('bg_alpha', 128)
            # Map 0-255 to 0.0-1.0
            opacity = round(alpha / 255.0, 2)
            box_cmd = f":box=1:boxcolor={box_color}@{opacity}:boxborderw=20"
        elif self.bg_blur:
            # Fallback for visibility on blurred bg (if style doesn't insist on no box)
            # Or maybe Shadow is better? But user liked valid mask.
            box_cmd = ":box=1:boxcolor=black@0.4:boxborderw=20"
        
        # Add Shadow/Border for styles without box?
        # Movie Yellow has outline=2.
        if not has_box and config.get('outline', 0) > 0:
             # Drawtext border
             # borderw=2:bordercolor=black
             box_cmd += ":borderw=2:bordercolor=black"

        filters.append(
            f"[merged]drawtext=text='{title_text}':fontcolor={title_color}:fontsize=60:"
            f"x=(w-text_w)/2:y={layout.title_y}{font_cmd}{box_cmd}[titled]"
        )
        
        # Burn Subtitles
        filters.append(f"[titled]ass='{escaped_ass}'[out]")
        
        filter_str = ";".join(filters)
        
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        cmd = [
            ffmpeg_exe, "-y",
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
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        return output_path

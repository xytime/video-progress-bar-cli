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
        tts_provider: Optional[str] = None
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
        self.segments = [] # Store for TTS usage

    def _generate_ass_file(self, segments: List[Dict[str, Any]]) -> Path:
        """Override to adjust subtitle vertical position (MarginV) and font size"""
        # Calculate layout first to get MarginV
        # We need video dimensions. Typically we'd probe. 
        # But here we just assume the default margin for the standardized 1080x1920 canvas.
        # The VerticalLayout defaults are good enough for the ASS generation 
        # because the canvas size is fixed to 1080x1920 regardless of input video.
        
        
        # Store segments for TTS generation later
        self.segments = segments
        
        # Initialize ASS file
        subs = pysubs2.SSAFile()
        subs.info['PlayResX'] = VerticalLayout.CANVAS_WIDTH
        subs.info['PlayResY'] = VerticalLayout.CANVAS_HEIGHT
        
        # Adjust Font Size
        font_size = self.font_size
        
        # Calculate dynamic wrap width
        # User feedback: Width can be wider (currently looks like 80%).
        # Increase safety factor to 0.96 (approx 1036px)
        safe_width = int(VerticalLayout.CANVAS_WIDTH * 0.96)
        
        # Approximate char width factor
        # Fonts vary, but usually 1 em = font_size.
        # We'll allow a bit more density. 
        wrap_width_zh = max(10, int(safe_width / font_size))
        wrap_width_en = max(20, int(safe_width / (font_size * 0.5)))
        
        import textwrap

        # Get base config
        config = CAPTION_STYLES.get(self.style, CAPTION_STYLES["default"])
        

        
        # User feedback: Subtitles shouldn't jump around (fixed top position) 
        # and shouldn't overlap video.
        # Solution: Use Top-Center Alignment (8) and fixed MarginV from Top.
        # Video Top = 350. Video Height (16:9) ~ 607. Video Bottom ~ 957.
        # Let's start subtitles at Y = 1000.
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
        en_c = config['en_color']

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
            
            # Simple Dual Line: ZH top, EN bottom (smaller)
            if zh_text and en_text:
                if self.bilingual:
                    text = f"{{\\c{zh_c}}}{zh_text}\\N{{\\fs{int(font_size*0.6)} \\c{en_c}}}{en_text}"
                else:
                    text = f"{{\\c{zh_c}}}{zh_text}"
            elif zh_text:
                text = f"{{\\c{zh_c}}}{zh_text}"
            else:
                text = f"{{\\c{en_c}}}{en_text}"

                
            evt = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=text)
            subs.events.append(evt)
            
        ass_path = self.input_path.with_suffix('.ass')
        subs.save(str(ass_path))
        return ass_path

    def _burn_subtitles(self, ass_path: Path) -> Path:
        """Compose 3-section layout using FFmpeg filter_complex"""
        
        output_path = self.output_path or self.input_path.parent / f"{self.input_path.stem}_vertical{self.input_path.suffix}"
        self.output_path = output_path
        
        # TTS Logic
        generated_audio_track = None
        if self.tts_provider and self.segments:
            logger.info(f"Generating TTS audio using provider: {self.tts_provider}")
            try:
                # Initialize Engine
                provider = TTSProvider.INDEXTTS if self.tts_provider == "indextts" else TTSProvider.EDGE
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
                    tts_engine.batch_generate(tts_items, audio_dir, voice_prompt="examples/test_audio.wav" if provider == TTSProvider.INDEXTTS else "onyx")
                    
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
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(self.input_path),
        ]
        
        # Audio Mapping Logic
        audio_inputs = ["-map", "0:a"] # Default: Original Audio
        
        if generated_audio_track and generated_audio_track.exists():
            # Add new audio as input 1
            cmd += ["-i", str(generated_audio_track)]
            
            audio_filter = f"[0:a]volume=0.1[bg];[1:a]volume=1.5[fg];[bg][fg]amix=inputs=2:duration=first[aout]"
            filter_str += f";{audio_filter}"
            
            audio_inputs = ["-map", "[aout]"]
        
        cmd += [
            "-filter_complex", filter_str,
            "-map", "[out]",
            *audio_inputs, 
            "-c:v", "libx264",
            "-c:a", "aac",
            str(output_path)
        ]
        
        logger.info(f"Rendering Vertical Video: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        return output_path

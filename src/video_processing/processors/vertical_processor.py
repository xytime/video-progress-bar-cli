import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

import pysubs2

from .caption_processor import AutoCaptionProcessor, CAPTION_STYLES, VideoProcessingError
from ..utils.layout import VerticalLayout

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
        bilingual: bool = False
    ):
        super().__init__(
            input_path, output_path, model_size, src_lang, target_lang, device, style
        )
        self.title = title or input_path.stem  # Default to filename if empty
        self.bg_blur = bg_blur
        self.font_path = font_path
        self.font_size = font_size
        self.bilingual = bilingual

    def _generate_ass_file(self, segments: List[Dict[str, Any]]) -> Path:
        """Override to adjust subtitle vertical position (MarginV) and font size"""
        # Calculate layout first to get MarginV
        # We need video dimensions. Typically we'd probe. 
        # But here we just assume the default margin for the standardized 1080x1920 canvas.
        # The VerticalLayout defaults are good enough for the ASS generation 
        # because the canvas size is fixed to 1080x1920 regardless of input video.
        
        
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
        
        # Font file for drawtext
        font_cmd = f":fontfile='{self.font_path}'" 
        
        # Colors
        title_color = "yellow" # As per user requirement A (Classic Black/Yellow)
        
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

        # Draw Title
        # split long title? drawtext doesn't wrap automatically well without complex options.
        # User said "Two lines large title".
        # Let's simple-draw for now at title_y.
        # fontsize=60
        filters.append(
            f"[merged]drawtext=text='{title_text}':fontcolor={title_color}:fontsize=60:"
            f"x=(w-text_w)/2:y={layout.title_y}{font_cmd}[titled]"
        )
        
        # Burn Subtitles
        filters.append(f"[titled]ass='{escaped_ass}'[out]")
        
        filter_str = ";".join(filters)
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(self.input_path),
            "-filter_complex", filter_str,
            "-map", "[out]",
            "-map", "0:a", # Copy audio
            "-c:v", "libx264",
            "-c:a", "aac", # Re-encode audio to be safe or copy? 
            # If we limit length or anything, copy might drift if not careful.
            # But here we just filter video. 'copy' usually fails with filter_complex for video. 
            # Audio can be copied if unchanged.
            str(output_path)
        ]
        
        logger.info(f"Rendering Vertical Video: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        return output_path

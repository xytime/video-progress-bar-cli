# -*- coding: utf-8 -*-
"""自动生成字幕 CLI 命令 — 提供语音识别、翻译及烧录入口

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking | 初始创建，提供 cli 主入口与 edge/indextts 选择 |
| 1.1.0   | 2026-05-28 | Gemini_3.5_Flash_planning | 新增 --tts-cosy 参数，支持阿里云百炼 CosyVoice 配音服务，标有 # [Gemini_3.5_Flash_planning] |
"""
import click
from pathlib import Path
import logging
from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.processors.vertical_processor import VerticalCaptionProcessor
from video_processing.core.base import VideoProcessingError

logger = logging.getLogger(__name__)

@click.command()
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.option('--model', '-m', default="small", help='Whisper model size (tiny, base, small, medium, large)', show_default=True)
@click.option('--src-lang', default="en", help='Source language code (e.g. en)', show_default=True)
@click.option('--target-lang', default="zh-CN", help='Target language code for translation (e.g. zh-CN)', show_default=True)
@click.option('--device', default="cpu", help='Device to use (cpu, cuda, mps)', show_default=True)
@click.option('--style', default="default", help='Caption style (default, movie_yellow, tech_blue)', show_default=True)
@click.option('--output', '-o', type=click.Path(path_type=Path), help='Output file path')
# Vertical Layout Options
@click.option('--vertical', is_flag=True, help='Enable 9:16 vertical layout mode with 3 sections')
@click.option('--title', help='Custom title for vertical video. Defaults to filename if empty.')
@click.option('--bg-blur', is_flag=True, help='Use blurred video background instead of black (Vertical mode only)')
@click.option('--font-path', type=click.Path(path_type=Path), default="/Library/Fonts/Arial Unicode.ttf", show_default=True, help='Font file path for title/subtitles.')
@click.option('--font-size', type=int, default=84, show_default=True, help='Subtitle font size (Vertical mode only, default 84)')
@click.option('--bilingual', is_flag=True, help='Show bilingual subtitles (ZH+EN) in Vertical mode. Default is Chinese only.')
@click.option('--tts', is_flag=True, help='Generate speech using Edge TTS (Free).')
@click.option('--tts-real', is_flag=True, help='Generate speech using IndexTTS (requires local IndexTTS installation).')
@click.option('--tts-cosy', is_flag=True, help='Generate speech using Aliyun CosyVoice.')  # [Gemini_3.5_Flash_planning]
@click.option('--tts-voice', default="longanzhi_v3", help='TTS voice name (e.g. longanzhi_v3, longsanshu_v3, longshuo_v3).', show_default=True)  # [Gemini_3.5_Flash_planning]
def auto_caption(input_path, model, src_lang, target_lang, device, style, output, vertical, title, bg_blur, font_path, font_size, bilingual, tts, tts_real, tts_cosy, tts_voice):
    """Generate and burn bilingual subtitles for a video."""
    try:
        
        # Determine TTS provider
        # [Gemini_3.5_Flash_planning]
        tts_provider = None
        if tts:
            tts_provider = "edge"
        elif tts_real:
            tts_provider = "indextts"
        elif tts_cosy:
            tts_provider = "cosyvoice"

        if vertical:
            processor = VerticalCaptionProcessor(
                input_path=input_path,
                output_path=output,
                model_size=model,
                src_lang=src_lang,
                target_lang=target_lang,
                device=device,
                style=style,
                title=title,
                bg_blur=bg_blur,
                font_path=str(font_path),
                font_size=font_size,
                bilingual=bilingual,
                tts_provider=tts_provider,
                tts_voice=tts_voice  # [Gemini_3.5_Flash_planning]
            )
            mode_str = "Vertical (9:16)"
        else:
            processor = AutoCaptionProcessor(
                input_path=input_path,
                output_path=output,
                model_size=model,
                src_lang=src_lang,
                target_lang=target_lang,
                device=device,
                style=style
            )
            mode_str = "Standard"
        
        click.echo(f"Starting auto-captioning for: {input_path}")
        click.echo(f"Mode: {mode_str}")
        click.echo(f"Configuration: Model={model}, Src={src_lang}, Target={target_lang}, Device={device}, Style={style}")
        
        output_file = processor.process()
        
        click.echo(f"Success! Output saved to: {output_file}")
        
    except VideoProcessingError as e:
        logger.error(f"Processing error: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        logger.exception("Unexpected error")
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort()

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
def auto_caption(input_path, model, src_lang, target_lang, device, style, output, vertical, title, bg_blur, font_path, font_size, bilingual):
    """Generate and burn bilingual subtitles for a video."""
    try:
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
                bilingual=bilingual
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

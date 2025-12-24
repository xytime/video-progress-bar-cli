import click
from pathlib import Path
import logging
from video_processing.processors.subtitle_extractor import SubtitleExtractionProcessor
from video_processing.core.base import VideoProcessingError

logger = logging.getLogger(__name__)

@click.command()
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.option('--model', '-m', default="small", help='Whisper model size (tiny, base, small, medium, large)', show_default=True)
@click.option('--device', default="cpu", help='Device to use (cpu, cuda, mps)', show_default=True)
@click.option('--output', '-o', type=click.Path(path_type=Path), help='Output file path or directory')
@click.option('--format', '-f', default="srt", type=click.Choice(['srt', 'ass', 'vtt', 'txt'], case_sensitive=False), help='Output format', show_default=True)
def extract_subs(input_path, model, device, output, format):
    """Extract subtitles from video without translation."""
    try:
        processor = SubtitleExtractionProcessor(
            input_path=input_path,
            output_path=output,
            model_size=model,
            device=device,
            output_format=format
        )
        
        click.echo(f"Starting subtitle extraction for: {input_path}")
        click.echo(f"Configuration: Model={model}, Device={device}, Format={format}")
        
        output_file = processor.process()
        
        click.echo(f"Success! Subtitles saved to: {output_file}")
        
    except VideoProcessingError as e:
        logger.error(f"Processing error: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        logger.exception("Unexpected error")
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort()

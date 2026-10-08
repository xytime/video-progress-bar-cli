"""Click CLI command for handwritten pager video generation.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of handwritten-pager CLI command |
"""

import json
from pathlib import Path
import click

from video_processing.handwritten_pager import (
    HandwrittenPagerConfig,
    HandwrittenPagerRenderer,
    CoverGenerator,
    Copywriter,
)


@click.command("handwritten-pager")
@click.option("--audio", type=click.Path(exists=True, path_type=Path), required=True, help="Path to input audio (WAV/MP3/AAC)")
@click.option("--lyrics-json", type=click.Path(exists=True, path_type=Path), required=True, help="Path to lyrics JSON with word timestamps")
@click.option("--output", type=click.Path(path_type=Path), required=True, help="Output MP4 video path")
@click.option("--title", default="Let Me Down Slowly", help="Song title")
@click.option("--artist", default="Alec Benjamin", help="Artist name")
@click.option("--chinese-title", default="慢慢放手", help="Chinese title")
@click.option("--fps", type=int, default=60, help="Output frame rate (default 60)")
@click.option("--covers-dir", type=click.Path(path_type=Path), help="Directory to save generated covers")
@click.option("--copy-output", type=click.Path(path_type=Path), help="Path to save copywriting JSON")
def handwritten_pager(audio, lyrics_json, output, title, artist, chinese_title, fps, covers_dir, copy_output):
    """Generate high-resolution handwritten notebook reading & pen-follow video."""
    config = HandwrittenPagerConfig(fps=fps)
    raw_lyrics = json.loads(lyrics_json.read_text(encoding="utf-8"))

    click.echo(f"Starting handwritten pager video generation: {title} by {artist}")

    # 1. Render Video
    renderer = HandwrittenPagerRenderer(config)
    result = renderer.render_video(
        audio_path=audio,
        output_path=output,
        raw_lyrics=raw_lyrics,
        title=title,
        artist=artist,
    )
    click.echo(f"Video rendered successfully: {output} ({result['render_seconds']:.1f}s, {result['render_fps']:.1f} fps)")

    # 2. Generate Covers
    if covers_dir:
        cover_gen = CoverGenerator(config)
        covers = cover_gen.generate_covers(
            raw_lyrics=raw_lyrics,
            output_dir=covers_dir,
            title=title,
            artist=artist,
        )
        click.echo(f"Covers generated: {json.dumps(covers, ensure_ascii=False, indent=2)}")

    # 3. Generate Copywriting
    copywriter = Copywriter()
    copy_pkg = copywriter.generate_copy(
        title=title,
        artist=artist,
        chinese_title=chinese_title,
    )
    copy_dict = {
        "wechat_short_title": copy_pkg.wechat_short_title,
        "wechat_copy": copy_pkg.wechat_copy,
        "douyin_title": copy_pkg.douyin_title,
        "douyin_copy": copy_pkg.douyin_copy,
        "hashtags": copy_pkg.hashtags,
    }
    if copy_output:
        Path(copy_output).write_text(json.dumps(copy_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        click.echo(f"Copywriting saved to: {copy_output}")
    else:
        click.echo(json.dumps(copy_dict, ensure_ascii=False, indent=2))

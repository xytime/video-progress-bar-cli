#!/usr/bin/env python3
"""End-to-end pipeline runner for handwritten pager video production & publishing.

Automates downloading, audio extraction, timestamped lyrics preparation,
60fps notebook video rendering with realistic pen physics, multi-platform cover generation,
viral copywriting, and optional automated submission to WeChat Channels and Douyin.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of end-to-end handwritten pager pipeline runner. |
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config.settings import settings  # noqa: E402
from video_processing.handwritten_pager import (  # noqa: E402
    HandwrittenPagerConfig,
    HandwrittenPagerRenderer,
    CoverGenerator,
    Copywriter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("handwritten_pager_pipeline")


def _sanitize_slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\-_]", "_", text)
    return re.sub(r"_+", "_", cleaned).strip("_")


def download_youtube_audio(url: str, output_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Download best audio and extract metadata from YouTube URL using yt-dlp."""
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_wav = output_dir / "audio.wav"
    metadata_json = output_dir / "metadata.json"

    cookies_args: list[str] = []
    cookies_path = PROJECT_ROOT / "output" / "youtube_cookies.txt"
    if cookies_path.exists():
        cookies_args = ["--cookies", str(cookies_path)]

    cmd_info = [
        str(PROJECT_ROOT / ".venv" / "bin" / "yt-dlp"),
        "--dump-json",
        "--no-playlist",
        *cookies_args,
        url,
    ]
    logger.info("Fetching YouTube metadata: %s", url)
    res_info = subprocess.run(cmd_info, capture_output=True, text=True, check=True)
    meta = json.loads(res_info.stdout.strip())
    metadata_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if not audio_wav.exists():
        cmd_dl = [
            str(PROJECT_ROOT / ".venv" / "bin" / "yt-dlp"),
            "-x",
            "--audio-format", "wav",
            "--audio-quality", "0",
            "-o", str(output_dir / "audio.%(ext)s"),
            "--no-playlist",
            *cookies_args,
            url,
        ]
        logger.info("Downloading audio via yt-dlp...")
        subprocess.run(cmd_dl, check=True)

    # Re-sample to standard 48kHz stereo WAV for audio precision
    resampled_wav = output_dir / "audio_resampled.wav"
    if not resampled_wav.exists() and audio_wav.exists():
        cmd_resample = [
            "ffmpeg", "-y", "-i", str(audio_wav),
            "-ar", "48000", "-ac", "2",
            str(resampled_wav),
        ]
        subprocess.run(cmd_resample, check=True, capture_output=True)
        return resampled_wav, meta

    return audio_wav, meta


def run_pipeline(
    *,
    url: str | None = None,
    audio_path: Path | None = None,
    lyrics_json_path: Path | None = None,
    title: str = "Let Me Down Slowly",
    artist: str = "Alec Benjamin",
    chinese_title: str = "慢慢放手",
    work_dir: Path | None = None,
    fps: int = 60,
    publish_wechat: bool = False,
    publish_douyin: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute the complete handwritten pager video production and publication flow."""
    # 1. Determine working directory
    if work_dir is None:
        slug = _sanitize_slug(f"{artist}_{title}")
        work_dir = PROJECT_ROOT / "output" / "handwritten_pager" / slug
    work_dir.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {}
    if url:
        logger.info("Step 1: Downloading from YouTube: %s", url)
        audio_file, meta = download_youtube_audio(url, work_dir)
    elif audio_path and audio_path.exists():
        audio_file = audio_path
    else:
        raise ValueError("Must provide either a valid YouTube URL or an existing audio file.")

    # 2. Prepare Lyrics
    if lyrics_json_path and lyrics_json_path.exists():
        logger.info("Step 2: Loading timestamped lyrics from: %s", lyrics_json_path)
        raw_lyrics = json.loads(lyrics_json_path.read_text(encoding="utf-8"))
    else:
        target_lyrics_file = work_dir / "lyrics.json"
        if target_lyrics_file.exists():
            logger.info("Step 2: Reusing existing lyrics.json in work dir")
            raw_lyrics = json.loads(target_lyrics_file.read_text(encoding="utf-8"))
        else:
            raise FileNotFoundError(
                f"lyrics.json not found at {target_lyrics_file}. Please provide --lyrics-json."
            )

    # 3. Render 60fps Video with Realistic Pen Physics
    logger.info("Step 3: Rendering 60fps notebook video with dual shadows & physics...")
    config = HandwrittenPagerConfig(fps=fps)
    renderer = HandwrittenPagerRenderer(config)
    output_video_path = work_dir / "final_handwritten_pager.mp4"

    render_result = renderer.render_video(
        audio_path=audio_file,
        output_path=output_video_path,
        raw_lyrics=raw_lyrics,
        title=title,
        artist=artist,
    )
    logger.info("Video render finished: %s", output_video_path)

    # 4. Generate Multi-Platform Covers
    logger.info("Step 4: Generating WeChat 9:16 and Douyin 3:4 / 4:3 covers...")
    cover_gen = CoverGenerator(config)
    covers_dir = work_dir / "covers"
    covers = cover_gen.generate_covers(
        raw_lyrics=raw_lyrics,
        output_dir=covers_dir,
        title=title,
        artist=artist,
    )
    logger.info("Covers generated: %s", list(covers.keys()))

    # 5. Generate Copywriting
    logger.info("Step 5: Generating platform copywriting...")
    copywriter = Copywriter()
    copy_pkg = copywriter.generate_copy(
        title=title,
        artist=artist,
        chinese_title=chinese_title,
    )

    wechat_title_file = work_dir / "wechat_title.txt"
    wechat_copy_file = work_dir / "wechat_copy.txt"
    douyin_title_file = work_dir / "douyin_title.txt"
    douyin_copy_file = work_dir / "douyin_copy.txt"

    wechat_title_file.write_text(copy_pkg.wechat_short_title, encoding="utf-8")
    wechat_copy_file.write_text(copy_pkg.wechat_copy, encoding="utf-8")
    douyin_title_file.write_text(copy_pkg.douyin_title, encoding="utf-8")
    douyin_copy_file.write_text(copy_pkg.douyin_copy, encoding="utf-8")

    # 6. Publishing (if requested and not dry_run)
    publication_results: dict[str, Any] = {}
    if not dry_run:
        if publish_wechat:
            logger.info("Step 6a: Submitting to WeChat Channels...")
            cmd_wc = [
                str(PROJECT_ROOT / ".venv" / "bin" / "python"),
                str(PROJECT_ROOT / "scripts" / "wechat_uploader.py"),
                "--video", str(output_video_path),
                "--title-file", str(wechat_title_file),
                "--copy", str(wechat_copy_file),
                "--cover", str(covers["wechat_9_16"]),
                "--state", str(PROJECT_ROOT / "output" / "wechat_state.json"),
            ]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(SRC_ROOT)
            res_wc = subprocess.run(cmd_wc, env=env, capture_output=True, text=True)
            publication_results["wechat"] = {
                "exit_code": res_wc.returncode,
                "stdout": res_wc.stdout[-500:],
                "stderr": res_wc.stderr[-500:],
            }

        if publish_douyin:
            logger.info("Step 6b: Submitting to Douyin...")
            # Use YouTube ID if available, otherwise synthetic ID
            yt_id = meta.get("id", _sanitize_slug(title))
            cmd_dy = [
                str(PROJECT_ROOT / ".venv" / "bin" / "python"),
                str(PROJECT_ROOT / "scripts" / "submit_generic_douyin.py"),
                "--video", str(output_video_path),
                "--youtube-id", yt_id,
                "--title-file", str(douyin_title_file),
                "--copy", str(douyin_copy_file),
                "--cover", str(covers["douyin_3_4"]),
                "--horizontal-cover", str(covers["douyin_4_3"]),
            ]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(SRC_ROOT)
            res_dy = subprocess.run(cmd_dy, env=env, capture_output=True, text=True)
            publication_results["douyin"] = {
                "exit_code": res_dy.returncode,
                "stdout": res_dy.stdout[-500:],
                "stderr": res_dy.stderr[-500:],
            }

    return {
        "video_path": str(output_video_path),
        "covers": {k: str(v) for k, v in covers.items()},
        "copywriting": {
            "wechat_title": copy_pkg.wechat_short_title,
            "douyin_title": copy_pkg.douyin_title,
        },
        "render_stats": render_result,
        "publications": publication_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run end-to-end handwritten pager video generation and publishing pipeline."
    )
    parser.add_argument("--url", help="YouTube video or short URL")
    parser.add_argument("--audio", type=Path, help="Local audio or video file")
    parser.add_argument("--lyrics-json", type=Path, help="Path to lyrics JSON with timestamps")
    parser.add_argument("--title", default="Let Me Down Slowly", help="Song title")
    parser.add_argument("--artist", default="Alec Benjamin", help="Artist name")
    parser.add_argument("--chinese-title", default="慢慢放手", help="Chinese title")
    parser.add_argument("--work-dir", type=Path, help="Working directory for artifacts")
    parser.add_argument("--fps", type=int, default=60, help="Output frame rate (default 60)")
    parser.add_argument("--publish-wechat", action="store_true", help="Submit to WeChat Channels")
    parser.add_argument("--publish-douyin", action="store_true", help="Submit to Douyin")
    parser.add_argument("--dry-run", action="store_true", help="Generate all assets without publishing")

    args = parser.parse_args()
    try:
        results = run_pipeline(
            url=args.url,
            audio_path=args.audio,
            lyrics_json_path=args.lyrics_json,
            title=args.title,
            artist=args.artist,
            chinese_title=args.chinese_title,
            work_dir=args.work_dir,
            fps=args.fps,
            publish_wechat=args.publish_wechat,
            publish_douyin=args.publish_douyin,
            dry_run=args.dry_run,
        )
        print("\n" + "=" * 60)
        print("🎉 Pipeline Execution Completed Successfully!")
        print(f"🎬 Video: {results['video_path']}")
        print(f"🖼️  Covers: {json.dumps(results['covers'], indent=2, ensure_ascii=False)}")
        print(f"📝 WeChat Title: {results['copywriting']['wechat_title']}")
        print(f"📝 Douyin Title: {results['copywriting']['douyin_title']}")
        if results["publications"]:
            print(f"🚀 Publications: {json.dumps(results['publications'], indent=2, ensure_ascii=False)}")
        print("=" * 60)
        return 0
    except Exception as e:
        logger.exception("Pipeline failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""封面生成器 — 从视频提取关键帧并叠加品牌水印，生成微信视频号封面图

# Modification History
| Version | Date       | Author                              | Description  |
|---------|------------|-------------------------------------|--------------|
| 1.0.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建     |
"""

import os
import sys
import argparse
import logging
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("cover_generator")

COVER_W, COVER_H = 1080, 1350
CHANNEL_NAME = "AI科技前沿"


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        return float(subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip())
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
        return 30.0


def extract_frame(video_path: str, timestamp: float, out_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        out_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg frame extraction failed: {e.stderr.decode()[:300]}")
        return False


def get_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode MS.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.FreeTypeFont,
              max_width: int, draw: ImageDraw.ImageDraw) -> list:
    lines, current = [], ""
    for char in text:
        test = current + char
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = char
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def generate_cover(video_path: str, title: str, output_path: str) -> bool:
    video_path  = str(Path(video_path).resolve())
    output_path = str(Path(output_path).resolve())

    duration  = get_video_duration(video_path)
    timestamp = max(3.0, duration * 0.10)
    tmp_frame = output_path + ".frame.jpg"

    logger.info(f"Extracting frame at {timestamp:.1f}s ...")
    if not extract_frame(video_path, timestamp, tmp_frame):
        timestamp = duration * 0.30
        if not extract_frame(video_path, timestamp, tmp_frame):
            logger.error("Cannot extract frame from video.")
            return False

    bg    = Image.open(tmp_frame).convert("RGB")
    ratio = max(COVER_W / bg.width, COVER_H / bg.height)
    bg    = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
    left  = (bg.width - COVER_W) // 2
    top   = (bg.height - COVER_H) // 2
    bg    = bg.crop((left, top, left + COVER_W, top + COVER_H))

    overlay   = Image.new("RGBA", (COVER_W, COVER_H), (0, 0, 0, 0))
    draw_ov   = ImageDraw.Draw(overlay)
    grad_h    = int(COVER_H * 0.55)
    for y in range(grad_h):
        alpha = int(200 * (y / grad_h))
        draw_ov.line([(0, COVER_H - grad_h + y), (COVER_W, COVER_H - grad_h + y)],
                     fill=(0, 0, 0, alpha))

    canvas = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    draw   = ImageDraw.Draw(canvas)

    title_font   = get_font(64)
    channel_font = get_font(36)
    margin       = 60
    title_lines  = wrap_text(title, title_font, COVER_W - margin * 2, draw)

    line_h  = 74
    block_h = len(title_lines) * line_h + 50 + 44
    text_y  = COVER_H - block_h - margin

    for i, line in enumerate(title_lines):
        y = text_y + i * line_h
        draw.text((margin + 2, y + 2), line, font=title_font, fill=(0, 0, 0))
        draw.text((margin, y),         line, font=title_font, fill=(255, 255, 255))

    ch_y = text_y + len(title_lines) * line_h + 16
    draw.text((margin, ch_y), f"📺 {CHANNEL_NAME}", font=channel_font, fill=(200, 200, 200))

    canvas.save(output_path, "JPEG", quality=92)
    logger.info(f"Cover saved: {output_path}  ({COVER_W}x{COVER_H})")
    Path(tmp_frame).unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video",  required=True)
    parser.add_argument("--title",  required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sys.exit(0 if generate_cover(args.video, args.title, args.output) else 1)


if __name__ == "__main__":
    main()

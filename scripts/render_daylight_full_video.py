#!/usr/bin/env python3
"""Render full multi-page 60fps handwritten pager video for David Kushner - Daylight."""

import logging
import time
from pathlib import Path

from video_processing.handwritten_pager.contracts import HandwrittenPagerConfig
from video_processing.handwritten_pager.daylight_pages import get_daylight_pages_data
from video_processing.handwritten_pager.multipage_renderer import MultiPageHandwrittenPagerRenderer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
work_dir = PROJECT_ROOT / "output/handwritten_pager/daylight"
audio_path = work_dir / "audio_trimmed.wav"
output_video_path = work_dir / "daylight_full_handwritten_pager.mp4"

pages_data = get_daylight_pages_data()

# 5 inter-page transitions for 6 pages
transitions = [
    (30.2, 31.8),   # P1 -> P2 (during 4.67s musical rest)
    (57.8, 58.2),   # P2 -> P3 (0.4s fast page flip right at chant start)
    (74.5, 76.0),   # P3 -> P4 (during 3.55s piano interlude)
    (104.5, 106.2), # P4 -> P5 (during 3.59s break)
    (134.8, 135.2), # P5 -> P6 (0.4s flip into Grand Finale)
]

config = HandwrittenPagerConfig(fps=60)
renderer = MultiPageHandwrittenPagerRenderer(config)

print("Starting full-length 60fps multi-page video rendering...")
t0 = time.time()
stats = renderer.render_multipage_video(
    audio_path=audio_path,
    output_path=output_video_path,
    page_specs=pages_data,
    transitions=transitions,
    duration=190.5,
)
print("Rendering finished successfully!")
print("Stats:", stats)
print(f"Total wall time: {time.time() - t0:.1f}s")

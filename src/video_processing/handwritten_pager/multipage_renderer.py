"""Multi-page video renderer for handwritten pager notebook video pipeline.

Supports seamless multi-page notebook flips and continuous pen physics tracking
across full songs (3+ minutes, 60fps, 1080x1920 H.264 + AAC).

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of multi-page handwritten pager renderer with smooth page flips |
"""

from __future__ import annotations

import logging
import math
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from config.settings import settings
from .canvas_builder import CanvasBuilder
from .contracts import HandwrittenPagerConfig, HandwrittenPagerError, LyricLine, LyricWord, PenState
from .pen_physics import PenPhysicsEngine, _pchip_interpolate

logger = logging.getLogger(__name__)


class MultiPageHandwrittenPagerRenderer:
    """Renders full-length multi-page notebook videos with continuous pen physics & page transitions."""

    def __init__(self, config: Optional[HandwrittenPagerConfig] = None):
        self.config = config or HandwrittenPagerConfig()
        self.config.validate()
        self.canvas_builder = CanvasBuilder(self.config)
        self.pen_engine = PenPhysicsEngine(self.config)

    def compute_multipage_trajectory(
        self,
        pages_lines: List[List[LyricLine]],
        total_duration: float,
        fps: int = 60,
    ) -> List[PenState]:
        """Computes continuous, seamless pen trajectory across all pages and transitions."""
        total_frames = int(round(total_duration * fps))

        # Build master keyframes: (t, x, y, z)
        keyframes: List[Tuple[float, float, float, float]] = []

        # Opening hover: start above the first word of page 1
        first_line = pages_lines[0][0]
        first_w = first_line.words[0]
        first_y = first_line.y_en + self.config.tip_y_offset
        first_t = first_w.start_time

        keyframes.append((0.0, first_w.x_start - 30.0, first_y - 20.0, 16.0))
        if first_t > 0.5:
            keyframes.append((first_t - 0.45, first_w.x_start - 10.0, first_y - 8.0, 8.0))
            keyframes.append((first_t - 0.08, first_w.x_start, first_y, 0.0))

        # Iterate through every page
        for p_idx, lines in enumerate(pages_lines):
            for l_idx, line in enumerate(lines):
                ly = line.y_en + self.config.tip_y_offset
                for w_idx, w in enumerate(line.words):
                    t_s = max(keyframes[-1][0] + 0.005, w.start_time)
                    t_e = max(t_s + 0.01, w.end_time)

                    # Last word in line
                    if w_idx == len(line.words) - 1:
                        # Check next line on same page or next page
                        if l_idx < len(lines) - 1:
                            next_start = lines[l_idx + 1].words[0].start_time
                            if next_start - t_e < 0.25:
                                t_e = max(t_s + 0.10, next_start - 0.28)
                        elif p_idx < len(pages_lines) - 1:
                            next_start = pages_lines[p_idx + 1][0].words[0].start_time
                            if next_start - t_e < 0.50:
                                t_e = max(t_s + 0.10, next_start - 0.55)

                    keyframes.append((t_s, w.x_start, ly, 0.0))
                    keyframes.append((t_e, w.x_end, ly, 0.0))

                    # Intra-line word gap
                    if w_idx < len(line.words) - 1:
                        next_w = line.words[w_idx + 1]
                        gap = next_w.start_time - t_e
                        if gap > 0.10:
                            t_mid = (t_e + next_w.start_time) / 2.0
                            x_mid = (w.x_end + next_w.x_start) / 2.0
                            keyframes.append((t_mid, x_mid, ly, 3.5))

                # Inter-line carriage return (on same page)
                if l_idx < len(lines) - 1:
                    next_line = lines[l_idx + 1]
                    next_first_w = next_line.words[0]
                    next_ly = next_line.y_en + self.config.tip_y_offset

                    t_ret_start = keyframes[-1][0]
                    t_ret_end = next_first_w.start_time
                    t_mid = (t_ret_start + t_ret_end) / 2.0
                    x_mid = (keyframes[-1][1] + next_first_w.x_start) / 2.0
                    y_mid = (ly + next_ly) / 2.0
                    keyframes.append((t_mid, x_mid, y_mid, 14.0))

            # Inter-page transition lift & glide
            if p_idx < len(pages_lines) - 1:
                next_p_first_line = pages_lines[p_idx + 1][0]
                next_p_first_w = next_p_first_line.words[0]
                next_p_ly = next_p_first_line.y_en + self.config.tip_y_offset

                t_flip_start = keyframes[-1][0]
                t_flip_end = next_p_first_w.start_time
                # Midpoint lift: pen hovers high as page flips
                t_mid = (t_flip_start + t_flip_end) / 2.0
                x_mid = 600.0  # Center of page
                y_mid = 450.0  # Upper mid
                keyframes.append((t_flip_start + 0.3, keyframes[-1][1] + 30.0, ly - 20.0, 18.0))
                keyframes.append((t_mid, x_mid, y_mid, 28.0))
                keyframes.append((t_flip_end - 0.25, next_p_first_w.x_start - 20.0, next_p_ly - 15.0, 12.0))
                keyframes.append((t_flip_end - 0.05, next_p_first_w.x_start, next_p_ly, 0.0))

        # Outro lift
        last_line = pages_lines[-1][-1]
        last_w = last_line.words[-1]
        last_y = last_line.y_en + self.config.tip_y_offset
        t_last = keyframes[-1][0]

        keyframes.append((t_last + 0.40, last_w.x_end + 35.0, last_y - 15.0, 12.0))
        keyframes.append((min(total_duration, t_last + 2.0), last_w.x_end + 70.0, last_y - 40.0, 22.0))
        keyframes.append((total_duration + 0.1, 750.0, 1200.0, 30.0))

        # Sort and deduplicate keyframes
        k_t, k_x, k_y, k_z = [], [], [], []
        for pt in sorted(keyframes, key=lambda p: p[0]):
            if not k_t or pt[0] > k_t[-1] + 1e-4:
                k_t.append(pt[0])
                k_x.append(pt[1])
                k_y.append(pt[2])
                k_z.append(pt[3])

        t_eval = np.linspace(0.0, total_duration, total_frames)
        x_eval = _pchip_interpolate(np.array(k_t), np.array(k_x), t_eval)
        y_eval = _pchip_interpolate(np.array(k_t), np.array(k_y), t_eval)
        z_eval = np.maximum(0.0, _pchip_interpolate(np.array(k_t), np.array(k_z), t_eval))

        # Flatten all words for active tagging
        all_words_list: List[LyricWord] = []
        for lines in pages_lines:
            for line in lines:
                all_words_list.extend(line.words)

        states: List[PenState] = []
        for f_idx in range(total_frames):
            t = float(t_eval[f_idx])
            raw_x = float(x_eval[f_idx])
            raw_y = float(y_eval[f_idx])
            raw_z = float(z_eval[f_idx])

            # Physiological human micro-tremor
            jitter_x = 0.35 * math.sin(2 * math.pi * 9.1 * t + 1.2) + 0.20 * math.cos(2 * math.pi * 13.5 * t + 2.5)
            jitter_y = 0.30 * math.cos(2 * math.pi * 8.4 * t + 0.8) + 0.15 * math.sin(2 * math.pi * 14.2 * t + 3.1)

            # Determine active word
            active_word: Optional[str] = None
            is_active = False
            for w in all_words_list:
                if w.start_time <= t <= w.end_time:
                    active_word = w.word
                    is_active = True
                    break

            # Angle dynamics: natural holding angle ~ -2.5 to -3.5 deg
            dynamic_angle = self.pen_engine.base_angle + 0.35 * math.sin(2 * math.pi * 1.5 * t)

            states.append(
                PenState(
                    frame_idx=f_idx,
                    t=t,
                    x=raw_x + jitter_x,
                    y=raw_y + jitter_y,
                    z=raw_z,
                    angle_deg=dynamic_angle,
                    is_active=is_active,
                    active_word=active_word,
                )
            )

        return states

    def render_multipage_video(
        self,
        audio_path: Path,
        output_path: Path,
        page_specs: List[Dict[str, Any]],
        transitions: List[Tuple[float, float]],  # List of (trans_start, trans_end) between pages
        duration: Optional[float] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Renders the full multi-page video and pipes directly into FFmpeg."""
        audio_path = Path(audio_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not audio_path.exists():
            raise HandwrittenPagerError("FILE_NOT_FOUND", f"Audio file not found: {audio_path}")

        if duration is None:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
            duration = float(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip())

        logger.info(f"Rendering multi-page handwritten video: {len(page_specs)} pages, {duration:.2f}s audio")

        # 1. Pre-render all page canvases and extract measured lines
        from .daylight_pages import render_daylight_page_canvas

        page_canvases: List[Image.Image] = []
        pages_lines: List[List[LyricLine]] = []
        for p in page_specs:
            c, l = render_daylight_page_canvas(p, self.canvas_builder)
            page_canvases.append(c)
            pages_lines.append(l)

        # 2. Compute multi-page continuous trajectory
        fps = self.config.fps
        states = self.compute_multipage_trajectory(pages_lines, total_duration=duration, fps=fps)
        total_frames = len(states)
        logger.info(f"Trajectory computed: {total_frames} frames ({fps} fps)")

        # 3. Launch FFmpeg process
        import imageio_ffmpeg
        import shutil
        ffmpeg_bin = getattr(settings, "ffmpeg_path", None) or shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "-s", f"{self.config.width}x{self.config.height}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "320k",
            "-movflags", "+faststart",
            "-shortest",
            str(output_path),
        ]

        logger.info("Spawning FFmpeg stream process...")
        t_start = time.perf_counter()
        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

        num_pages = len(page_canvases)

        # 4. Stream rendered frames
        for f_idx, state in enumerate(states):
            t = state.t

            # Determine canvas for time t
            cur_page_idx = 0
            is_transition = False
            trans_alpha = 0.0
            next_page_idx = 0

            for p_i in range(num_pages - 1):
                t_trans_start, t_trans_end = transitions[p_i]
                if t < t_trans_start:
                    cur_page_idx = p_i
                    break
                elif t_trans_start <= t <= t_trans_end:
                    is_transition = True
                    cur_page_idx = p_i
                    next_page_idx = p_i + 1
                    trans_alpha = (t - t_trans_start) / max(0.01, t_trans_end - t_trans_start)
                    break
                else:
                    cur_page_idx = p_i + 1

            if is_transition:
                # Smooth crossfade page transition
                bg_canvas = Image.blend(page_canvases[cur_page_idx], page_canvases[next_page_idx], trans_alpha)
            else:
                bg_canvas = page_canvases[cur_page_idx]

            # Render pen frame
            frame = self.pen_engine.render_pen_frame(bg_canvas, state)
            proc.stdin.write(frame.tobytes())

            if (f_idx + 1) % 300 == 0 or (f_idx + 1) == total_frames:
                pct = ((f_idx + 1) / total_frames) * 100.0
                elapsed = time.perf_counter() - t_start
                cur_fps = (f_idx + 1) / max(0.001, elapsed)
                logger.info(f"Render progress: {f_idx + 1}/{total_frames} ({pct:.1f}%) - {cur_fps:.1f} fps")
                if progress_callback:
                    progress_callback(f_idx + 1, total_frames)

        proc.stdin.close()
        proc.wait()

        render_seconds = time.perf_counter() - t_start
        overall_fps = total_frames / max(0.001, render_seconds)
        logger.info(f"Multi-page render complete in {render_seconds:.1f}s ({overall_fps:.1f} fps) -> {output_path}")

        return {
            "output_path": str(output_path),
            "total_frames": total_frames,
            "render_seconds": render_seconds,
            "render_fps": overall_fps,
            "num_pages": num_pages,
            "duration": duration,
        }

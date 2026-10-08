"""High performance video renderer for handwritten pager video pipeline.

Streams 1080x1920 frames directly into FFmpeg stdin pipe:
- H.264 High Profile, CRF 18, 60fps for silky smooth handwriting motion.
- High-fidelity AAC stereo audio.
- Faststart enabled for instant mobile video playback.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of video renderer |
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import settings

from .canvas_builder import CanvasBuilder
from .contracts import HandwrittenPagerConfig, HandwrittenPagerError
from .pen_physics import PenPhysicsEngine

logger = logging.getLogger(__name__)


class HandwrittenPagerRenderer:
    """Renders complete 1080x1920 vertical video with synced pen motion dynamics."""

    def __init__(self, config: Optional[HandwrittenPagerConfig] = None):
        self.config = config or HandwrittenPagerConfig()
        self.config.validate()
        self.canvas_builder = CanvasBuilder(self.config)
        self.pen_engine = PenPhysicsEngine(self.config)

    def render_video(
        self,
        audio_path: Path,
        output_path: Path,
        raw_lyrics: List[Dict[str, Any]],
        title: str = "Let Me Down Slowly",
        artist: str = "Alec Benjamin",
        study_notes: Optional[List[tuple]] = None,
        duration: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Renders video and muxes with audio into production MP4."""
        audio_path = Path(audio_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not audio_path.exists():
            raise HandwrittenPagerError("FILE_NOT_FOUND", f"Audio file not found: {audio_path}")

        # Get audio duration if not provided
        if duration is None:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                duration = float(res.stdout.strip())
            except Exception as e:
                logger.warning(f"Could not probe audio duration: {e}, defaulting to 15.0s")
                duration = 15.0

        # 1. Build base canvas & measure lyric word coordinates
        base_canvas, measured_lines = self.canvas_builder.build_canvas(
            raw_lyrics=raw_lyrics,
            title=title,
            artist=artist,
            study_notes=study_notes,
        )

        # 2. Compute physics trajectory for every frame
        fps = self.config.fps
        states = self.pen_engine.compute_trajectory(
            lines=measured_lines,
            total_duration=duration,
            fps=fps,
        )
        total_frames = len(states)
        logger.info(f"Computed {total_frames} frames of pen trajectory at {fps} fps ({duration:.2f}s)")

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
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "320k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]

        t0 = time.time()
        proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        try:
            for state in states:
                frame_img = self.pen_engine.render_pen_frame(base_canvas, state)
                proc.stdin.write(frame_img.tobytes())

            proc.stdin.close()
            stderr_out = proc.stderr.read().decode("utf-8", errors="replace")
            ret_code = proc.wait()

            if ret_code != 0:
                raise HandwrittenPagerError("RENDER_FAILED", f"FFmpeg failed (code {ret_code}): {stderr_out}")

        except Exception as e:
            proc.kill()
            raise HandwrittenPagerError("RENDER_FAILED", f"Render pipeline aborted: {e}") from e

        render_sec = time.time() - t0
        render_fps = total_frames / max(0.001, render_sec)
        logger.info(f"Rendered {output_path.name} in {render_sec:.2f}s ({render_fps:.1f} fps)")

        if not output_path.exists() or output_path.stat().st_size < 10000:
            raise HandwrittenPagerError("OUTPUT_CORRUPTED", f"Output video file is missing or too small: {output_path}")

        return {
            "output_path": str(output_path),
            "duration": duration,
            "total_frames": total_frames,
            "fps": fps,
            "render_seconds": render_sec,
            "render_fps": render_fps,
            "file_size_bytes": output_path.stat().st_size,
        }

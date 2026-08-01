# -*- coding: utf-8 -*-
"""模板 A 的 FFmpeg 合成器。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：独立合成原片小窗、旋转唱片与逐词红线，输出 manifest。 |
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import imageio_ffmpeg

from .models import StudyCardContent
from .template_a import ACCENT, DISC_BOX, VIDEO_BOX, RecordUnderlineTemplate


class StudyCardRenderer:
    """单模板的纯渲染入口；调用方负责采集、选段、对齐和内容生成。"""

    def __init__(self, template: RecordUnderlineTemplate | None = None) -> None:
        self.template = template or RecordUnderlineTemplate()

    def render(
        self,
        source_video: Path,
        content: StudyCardContent,
        output_path: Path,
        *,
        source_start: float = 0.0,
        duration: float | None = None,
        keep_assets: bool = False,
    ) -> Path:
        """渲染一个小于等于 30 秒的原声新闻精读卡片。"""
        source_video = source_video.expanduser().resolve()
        output_path = output_path.expanduser().resolve()
        if source_start < 0:
            raise ValueError("source_start 不能小于 0")
        clip_duration = duration if duration is not None else content.words[-1].end
        if clip_duration <= 0 or clip_duration > 30:
            raise ValueError("新闻精读片段必须大于 0 且不超过 30 秒")
        if content.words and content.words[-1].end > clip_duration + 0.05:
            raise ValueError("逐词时间轴超出所截取的视频时长")
        if not source_video.is_file():
            raise FileNotFoundError(f"找不到源视频: {source_video}")
        source_duration = self._probe_duration(source_video)
        if source_start + clip_duration > source_duration + 0.05:
            raise ValueError(
                f"截取区间超出源视频时长: {source_start:.3f}+{clip_duration:.3f} > {source_duration:.3f}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="study_card_"))
        try:
            assets = self.template.render_static(content, work_dir)
            timed_boxes = self.template.map_word_boxes(content.words, assets.word_boxes)
            self._run_ffmpeg(
                source_video=source_video,
                base_image=assets.base_image,
                disc_image=assets.disc_image,
                timed_boxes=timed_boxes,
                output_path=output_path,
                source_start=source_start,
                duration=clip_duration,
            )
            self._write_manifest(output_path, content, source_video, source_start, clip_duration, timed_boxes)
            if keep_assets:
                assets_dir = output_path.with_suffix("").with_name(output_path.stem + "_assets")
                shutil.copytree(work_dir, assets_dir, dirs_exist_ok=True)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        return output_path

    @staticmethod
    def _probe_duration(source_video: Path) -> float:
        """在合成前确认源片可覆盖所请求区间，避免生成被静默截短的 MP4。"""
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(source_video),
            ],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"无法读取源视频时长: {completed.stderr.strip()}")
        try:
            duration = float(completed.stdout.strip())
        except ValueError as exc:
            raise RuntimeError(f"无法解析源视频时长: {completed.stdout!r}") from exc
        if duration <= 0:
            raise RuntimeError("源视频时长必须大于 0")
        return duration

    def _run_ffmpeg(
        self,
        *,
        source_video: Path,
        base_image: Path,
        disc_image: Path,
        timed_boxes: list[tuple[Any, Any]],
        output_path: Path,
        source_start: float,
        duration: float,
    ) -> None:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        video_w = VIDEO_BOX[2] - VIDEO_BOX[0]
        video_h = VIDEO_BOX[3] - VIDEO_BOX[1]
        disc_w = DISC_BOX[2] - DISC_BOX[0]
        disc_h = DISC_BOX[3] - DISC_BOX[1]
        filters = [
            f"[1:v]scale={video_w}:{video_h}:force_original_aspect_ratio=increase,crop={video_w}:{video_h},fps=30[clip]",
            f"[2:v]format=rgba,scale={disc_w}:{disc_h},rotate=2*PI*t/3:c=none:ow=rotw(iw):oh=roth(ih)[disc]",
            f"[0:v][clip]overlay={VIDEO_BOX[0]}:{VIDEO_BOX[1]}:shortest=1[page]",
            f"[page][disc]overlay={DISC_BOX[0]}:{DISC_BOX[1]}:shortest=1[animated]",
        ]
        current = "animated"
        for index, (word, box) in enumerate(timed_boxes):
            output_label = f"underline_{index}"
            filters.append(
                f"[{current}]drawbox=x={box.x}:y={box.y}:w={box.width}:h=6:"
                f"color={ACCENT}@0.96:t=fill:enable='between(t,{word.start:.3f},{word.end:.3f})'"
                f"[{output_label}]"
            )
            current = output_label

        command = [
            ffmpeg, "-y",
            "-loop", "1", "-framerate", "30", "-i", str(base_image),
            "-ss", f"{source_start:.3f}", "-t", f"{duration:.3f}", "-i", str(source_video),
            "-loop", "1", "-framerate", "30", "-i", str(disc_image),
            "-filter_complex", ";".join(filters),
            "-map", f"[{current}]", "-map", "1:a?",
            "-t", f"{duration:.3f}", "-r", "30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"新闻精读卡片渲染失败: {completed.stderr[-2000:]}")

    def _write_manifest(
        self,
        output_path: Path,
        content: StudyCardContent,
        source_video: Path,
        source_start: float,
        duration: float,
        timed_boxes: list[tuple[Any, Any]],
    ) -> None:
        manifest = {
            "template": self.template.name,
            "source_video": str(source_video),
            "source_start": source_start,
            "duration": duration,
            "word_count": len(content.words),
            "vocabulary_count": len(content.vocabulary),
            "underline_events": [
                {"word": word.text, "start": word.start, "end": word.end, "x": box.x, "y": box.y, "width": box.width}
                for word, box in timed_boxes
            ],
        }
        output_path.with_suffix(".manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

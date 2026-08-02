# -*- coding: utf-8 -*-
"""模板 A 的 FFmpeg 合成器。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-02 | Codex | 初始创建：独立合成原片小窗、旋转唱片与逐词红线，输出 manifest。 |
| 1.1.0 | 2026-08-02 | Codex | 以最后一个已纳入正文的单词为硬终点，音视频同步裁切并淡出，杜绝露出后续导语。 |
| 1.2.0 | 2026-08-02 | Codex | 将正文与红线合成为同一透明长图层，按语音进度分段滚动；测试模式可显式放宽时长上限。 |
| 1.2.1 | 2026-08-02 | Codex | 逐词红线改为在最终不透明画面上绘制，并由 Python 预计算滚动后的屏幕坐标确保可见。 |
| 1.3.0 | 2026-08-03 | Codex | 红线按当前单词的朗读进度由左至右增长，避免仅闪现整条下划线。 |
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import imageio_ffmpeg

from .models import StudyCardContent
from .template_a import (
    CANVAS_WIDTH,
    DISC_BOX,
    READING_VIEWPORT_BOTTOM,
    TEXT_TOP,
    VIDEO_BOX,
    RecordUnderlineTemplate,
)

_AUDIO_TAIL_SECONDS = 0.18
_AUDIO_FADE_SECONDS = 0.08
_PRODUCTION_MAX_DURATION = 30.0
_TEST_MAX_DURATION = 60.0


@dataclass(frozen=True)
class ScrollStep:
    """正文向上移动的一次短过渡：开始、结束、起点偏移、终点偏移。"""

    start: float
    end: float
    from_offset: int
    to_offset: int


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
        allow_long_test: bool = False,
    ) -> Path:
        """渲染原声新闻精读卡片；仅显式测试模式允许超过 30 秒。"""
        source_video = source_video.expanduser().resolve()
        output_path = output_path.expanduser().resolve()
        if source_start < 0:
            raise ValueError("source_start 不能小于 0")
        if not content.words:
            raise ValueError("新闻精读卡片至少需要一个逐词时间轴")
        requested_duration = duration if duration is not None else content.words[-1].end + _AUDIO_TAIL_SECONDS
        maximum_duration = _TEST_MAX_DURATION if allow_long_test else _PRODUCTION_MAX_DURATION
        if requested_duration <= 0 or requested_duration > maximum_duration:
            mode = "测试模式" if allow_long_test else "生产模式"
            raise ValueError(f"{mode}新闻精读片段必须大于 0 且不超过 {maximum_duration:g} 秒")
        if content.words[-1].end > requested_duration + 0.05:
            raise ValueError("逐词时间轴超出所截取的视频时长")
        clip_duration = self._resolve_render_duration(content, requested_duration)
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
            scroll_steps = self._build_scroll_steps(timed_boxes)
            self._run_ffmpeg(
                source_video=source_video,
                base_image=assets.base_image,
                reading_image=assets.reading_image,
                disc_image=assets.disc_image,
                timed_boxes=timed_boxes,
                output_path=output_path,
                source_start=source_start,
                duration=clip_duration,
                scroll_steps=scroll_steps,
            )
            self._write_manifest(
                output_path, content, source_video, source_start, clip_duration, timed_boxes, scroll_steps,
            )
            if keep_assets:
                assets_dir = output_path.with_suffix("").with_name(output_path.stem + "_assets")
                shutil.copytree(work_dir, assets_dir, dirs_exist_ok=True)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        return output_path

    @staticmethod
    def _resolve_render_duration(content: StudyCardContent, requested_duration: float) -> float:
        """在最后一个学习词之后留极短收尾，绝不播放未纳入正文的下一个词。"""
        spoken_end = content.words[-1].end
        return min(requested_duration, spoken_end + _AUDIO_TAIL_SECONDS)

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
        reading_image: Path,
        disc_image: Path,
        timed_boxes: list[tuple[Any, Any]],
        output_path: Path,
        source_start: float,
        duration: float,
        scroll_steps: list[ScrollStep],
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
            "[3:v]format=rgba[reading_source]",
        ]
        scroll_expression = self._scroll_offset_expression(scroll_steps)
        viewport_height = READING_VIEWPORT_BOTTOM - TEXT_TOP
        filters.append(
            f"color=c=black@0.0:s={CANVAS_WIDTH}x{viewport_height}:r=30,format=rgba[reading_window]"
        )
        filters.append(
            f"[reading_window][reading_source]overlay=0:'-{TEXT_TOP}-{scroll_expression}':eval=frame[reading_clipped]"
        )
        filters.append(
            f"[animated][reading_clipped]overlay=0:{TEXT_TOP}:shortest=1[composited]"
        )
        video_label = "composited"
        for index, (word, box) in enumerate(timed_boxes):
            underline_label = f"underline_source_{index}"
            output_label = f"underlined_{index}"
            screen_y = box.y - self._scroll_offset_at((word.start + word.end) / 2, scroll_steps)
            underline_alpha = self._underline_alpha_expression(box.width, word.start, word.end)
            filters.append(
                f"color=c=black@0.0:s={box.width}x6:r=30,format=rgba,"
                f"geq=r='198':g='67':b='45':a='{underline_alpha}'[{underline_label}]"
            )
            filters.append(
                f"[{video_label}][{underline_label}]overlay={box.x}:{screen_y}:"
                f"shortest=1:enable='between(t,{word.start:.3f},{word.end:.3f})'"
                f"[{output_label}]"
            )
            video_label = output_label

        has_audio = self._has_audio(source_video)
        audio_label = None
        if has_audio:
            fade_duration = min(_AUDIO_FADE_SECONDS, duration)
            fade_start = max(0.0, duration - fade_duration)
            audio_label = "trimmed_audio"
            filters.append(
                f"[1:a]atrim=end={duration:.3f},"
                f"afade=t=out:st={fade_start:.3f}:d={fade_duration:.3f}[{audio_label}]"
            )

        command = [
            ffmpeg, "-y",
            "-loop", "1", "-framerate", "30", "-i", str(base_image),
            "-ss", f"{source_start:.3f}", "-t", f"{duration:.3f}", "-i", str(source_video),
            "-loop", "1", "-framerate", "30", "-i", str(disc_image),
            "-loop", "1", "-framerate", "30", "-i", str(reading_image),
            "-filter_complex", ";".join(filters),
            "-map", f"[{video_label}]",
            "-t", f"{duration:.3f}", "-r", "30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
        ]
        if audio_label:
            command.extend(["-map", f"[{audio_label}]", "-c:a", "aac"])
        command.extend([
            "-shortest",
            str(output_path),
        ])
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"新闻精读卡片渲染失败: {completed.stderr[-2000:]}")

    @staticmethod
    def _has_audio(source_video: Path) -> bool:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(source_video)],
            capture_output=True,
            text=True,
        )
        return completed.returncode == 0 and bool(completed.stdout.strip())

    def _write_manifest(
        self,
        output_path: Path,
        content: StudyCardContent,
        source_video: Path,
        source_start: float,
        duration: float,
        timed_boxes: list[tuple[Any, Any]],
        scroll_steps: list[ScrollStep],
    ) -> None:
        manifest = {
            "template": self.template.name,
            "source_video": str(source_video),
            "source_start": source_start,
            "duration": duration,
            "speech_end": content.words[-1].end,
            "audio_tail_seconds": round(max(0.0, duration - content.words[-1].end), 3),
            "word_count": len(content.words),
            "vocabulary_count": len(content.vocabulary),
            "scroll_steps": [
                {
                    "start": round(step.start, 3), "end": round(step.end, 3),
                    "from_offset": step.from_offset, "to_offset": step.to_offset,
                }
                for step in scroll_steps
            ],
            "underline_events": [
                {"word": word.text, "start": word.start, "end": word.end, "x": box.x, "y": box.y, "width": box.width}
                for word, box in timed_boxes
            ],
        }
        output_path.with_suffix(".manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _build_scroll_steps(timed_boxes: list[tuple[Any, Any]]) -> list[ScrollStep]:
        """以当前朗读词为锚点滚动，保证正在读的英文保持在正文可读中区。"""
        steps: list[ScrollStep] = []
        offset = 0
        trigger_y = 1540
        target_y = 1040
        transition_seconds = 0.34
        last_end = 0.0
        for word, box in timed_boxes:
            visible_y = box.y - offset
            if visible_y <= trigger_y:
                continue
            target_offset = max(offset, box.y - target_y)
            if target_offset == offset:
                continue
            end = max(last_end + 0.05, word.start - 0.04)
            start = max(last_end, end - transition_seconds)
            if start >= end:
                start = max(0.0, word.start - transition_seconds)
                end = word.start
            steps.append(ScrollStep(start, end, offset, target_offset))
            offset = target_offset
            last_end = end
        return steps

    @staticmethod
    def _scroll_offset_at(timestamp: float, steps: list[ScrollStep]) -> int:
        """按滚动计划预计算某个时间点的正文偏移，供红线使用固定屏幕坐标。"""
        offset = 0.0
        for step in steps:
            if timestamp < step.start:
                break
            if timestamp < step.end:
                ratio = (timestamp - step.start) / (step.end - step.start)
                offset = step.from_offset + (step.to_offset - step.from_offset) * ratio
                break
            offset = step.to_offset
        return int(round(offset))

    @staticmethod
    def _underline_alpha_expression(box_width: int, start: float, end: float) -> str:
        """返回逐帧增长的透明度遮罩；drawbox 的宽度并不支持逐帧求值。"""
        if box_width <= 0 or end <= start:
            raise ValueError("红线宽度与时间轴必须有效")
        return (
            f"if(between(T\\,{start:.3f}\\,{end:.3f})*"
            f"lte(X\\,{box_width}*(T-{start:.3f})/{end - start:.3f})\\,255\\,0)"
        )

    @staticmethod
    def _scroll_offset_expression(steps: list[ScrollStep]) -> str:
        """生成 FFmpeg 可逐帧求值的偏移表达式，逗号在 filtergraph 中必须转义。"""
        expression = "0"
        for step in steps:
            transition = (
                f"{step.from_offset}+({step.to_offset}-{step.from_offset})*"
                f"(t-{step.start:.3f})/{step.end - step.start:.3f}"
            )
            expression = (
                f"if(lt(t,{step.start:.3f}),{expression},"
                f"if(lt(t,{step.end:.3f}),{transition},{step.to_offset}))"
            )
        return expression.replace(",", r"\,")

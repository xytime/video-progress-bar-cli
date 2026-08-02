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
| 1.4.0 | 2026-08-03 | Codex | 为正文滚动插入 0.5 秒静音冻结段，并支持右上影子跟读 Banner 静态素材。 |
| 1.5.0 | 2026-08-03 | Codex | 将逐词红线预渲染为单个透明视频层，避免长样片中数百层 FFmpeg overlay 过慢。 |
| 1.5.1 | 2026-08-03 | Codex | 主合成不再用 shortest 截短，兼容源文件视频流略短于音频流的情况。 |
| 1.5.2 | 2026-08-03 | Codex | 滚动目标位下移，减少翻页后顶部残留孤立标点或半行文本。 |
"""

from __future__ import annotations

import json
from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import imageio_ffmpeg
from PIL import Image, ImageDraw

from .models import StudyCardContent, StudyWord
from .template_a import (
    CANVAS_WIDTH,
    FEATURE_BOX,
    READING_VIEWPORT_BOTTOM,
    TEXT_TOP,
    VIDEO_BOX,
    RecordUnderlineTemplate,
)

_AUDIO_TAIL_SECONDS = 0.18
_AUDIO_FADE_SECONDS = 0.08
_SCROLL_PAUSE_SECONDS = 0.5
_PRODUCTION_MAX_DURATION = 30.0
_TEST_MAX_DURATION = 60.0


@dataclass(frozen=True)
class ScrollStep:
    """正文向上移动的一次短过渡：开始、结束、起点偏移、终点偏移。"""

    start: float
    end: float
    from_offset: int
    to_offset: int


@dataclass(frozen=True)
class TimelinePause:
    """输出时间轴中的一段阅读暂停；源片在 source_time 冻结，音频填静音。"""

    source_time: float
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


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
        source_clip_duration = self._resolve_render_duration(content, requested_duration)
        if not source_video.is_file():
            raise FileNotFoundError(f"找不到源视频: {source_video}")
        source_duration = self._probe_duration(source_video)
        if source_start + source_clip_duration > source_duration + 0.05:
            raise ValueError(
                f"截取区间超出源视频时长: {source_start:.3f}+{source_clip_duration:.3f} > {source_duration:.3f}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="study_card_"))
        try:
            assets = self.template.render_static(content, work_dir)
            source_timed_boxes = self.template.map_word_boxes(content.words, assets.word_boxes)
            scroll_steps, pause_segments = self._build_scroll_steps(source_timed_boxes)
            timed_boxes = self._shift_timed_boxes_for_pauses(source_timed_boxes, pause_segments)
            output_duration = source_clip_duration + self._total_pause_duration_before(
                source_clip_duration, pause_segments,
            )
            underline_video = work_dir / "template_a_underlines.mov"
            self._render_underline_overlay(underline_video, timed_boxes, scroll_steps, output_duration)
            self._run_ffmpeg(
                source_video=source_video,
                base_image=assets.base_image,
                reading_image=assets.reading_image,
                feature_image=assets.feature_image,
                underline_video=underline_video,
                output_path=output_path,
                source_start=source_start,
                source_duration=source_clip_duration,
                output_duration=output_duration,
                scroll_steps=scroll_steps,
                pause_segments=pause_segments,
            )
            self._write_manifest(
                output_path, content, source_video, source_start, source_clip_duration,
                output_duration, timed_boxes, scroll_steps, pause_segments,
            )
            if keep_assets:
                assets_dir = output_path.with_suffix("").with_name(output_path.stem + "_assets")
                shutil.copytree(work_dir, assets_dir, dirs_exist_ok=True)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        return output_path

    @staticmethod
    def _resolve_render_duration(content: StudyCardContent, requested_duration: float) -> float:
        """源片时间轴只在最后一个学习词之后留极短收尾，绝不播放未纳入正文的下一个词。"""
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
        feature_image: Path,
        underline_video: Path,
        output_path: Path,
        source_start: float,
        source_duration: float,
        output_duration: float,
        scroll_steps: list[ScrollStep],
        pause_segments: list[TimelinePause],
    ) -> None:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        video_w = VIDEO_BOX[2] - VIDEO_BOX[0]
        video_h = VIDEO_BOX[3] - VIDEO_BOX[1]
        feature_w = FEATURE_BOX[2] - FEATURE_BOX[0]
        feature_h = FEATURE_BOX[3] - FEATURE_BOX[1]
        has_audio = self._has_audio(source_video)
        filters = [
            self._source_video_filter(
                video_w=video_w,
                video_h=video_h,
                source_duration=source_duration,
                pause_segments=pause_segments,
            ),
            *self._source_audio_filters(
                source_duration=source_duration,
                output_duration=output_duration,
                pause_segments=pause_segments,
                has_audio=has_audio,
            ),
            f"[2:v]format=rgba,scale={feature_w}:{feature_h}[feature]",
            f"[0:v][clip]overlay={VIDEO_BOX[0]}:{VIDEO_BOX[1]}[page]",
            f"[page][feature]overlay={FEATURE_BOX[0]}:{FEATURE_BOX[1]}:shortest=1[animated]",
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
        filters.append("[4:v]format=rgba[underline_layer]")
        filters.append(f"[composited][underline_layer]overlay=0:{TEXT_TOP}[underlined]")

        command = [
            ffmpeg, "-y",
            "-loop", "1", "-framerate", "30", "-i", str(base_image),
            "-ss", f"{source_start:.3f}", "-t", f"{source_duration:.3f}", "-i", str(source_video),
            "-loop", "1", "-framerate", "30", "-i", str(feature_image),
            "-loop", "1", "-framerate", "30", "-i", str(reading_image),
            "-i", str(underline_video),
            "-filter_complex", ";".join(filters),
            "-map", "[underlined]",
            "-t", f"{output_duration:.3f}", "-r", "30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
        ]
        if has_audio:
            command.extend(["-map", "[trimmed_audio]", "-c:a", "aac"])
        command.append(str(output_path))
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"新闻精读卡片渲染失败: {completed.stderr[-2000:]}")

    def _render_underline_overlay(
        self,
        output_path: Path,
        timed_boxes: list[tuple[StudyWord, Any]],
        scroll_steps: list[ScrollStep],
        duration: float,
    ) -> None:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        viewport_height = READING_VIEWPORT_BOTTOM - TEXT_TOP
        frame_count = max(1, int(math.ceil(duration * 30)) + 15)
        command = [
            ffmpeg, "-y",
            "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{CANVAS_WIDTH}x{viewport_height}", "-r", "30",
            "-i", "pipe:0",
            "-an", "-c:v", "qtrle", str(output_path),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert process.stdin is not None
        active_index = 0
        try:
            for frame_index in range(frame_count):
                timestamp = frame_index / 30
                while active_index < len(timed_boxes) and timed_boxes[active_index][0].end < timestamp:
                    active_index += 1
                frame = Image.new("RGBA", (CANVAS_WIDTH, viewport_height), (0, 0, 0, 0))
                draw = ImageDraw.Draw(frame)
                for word, box in timed_boxes[active_index:active_index + 2]:
                    if word.start <= timestamp <= word.end:
                        width = self._underline_progress_width(box.width, word.start, word.end, timestamp)
                        if width > 0:
                            y = box.y - self._scroll_offset_at(timestamp, scroll_steps) - TEXT_TOP
                            if -6 <= y < viewport_height:
                                draw.rectangle((box.x, y, box.x + width, y + 5), fill=(198, 67, 45, 255))
                process.stdin.write(frame.tobytes())
            process.stdin.close()
        except BrokenPipeError:
            pass
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        if process.wait() != 0:
            raise RuntimeError(f"红线透明层渲染失败: {stderr[-2000:]}")

    @staticmethod
    def _source_video_filter(
        *,
        video_w: int,
        video_h: int,
        source_duration: float,
        pause_segments: list[TimelinePause],
    ) -> str:
        pauses = _active_pauses(source_duration, pause_segments)
        scale = f"scale={video_w}:{video_h}:force_original_aspect_ratio=increase,crop={video_w}:{video_h},fps=30"
        if not pauses:
            return f"[1:v]{scale}[clip]"

        filters: list[str] = []
        labels: list[str] = []
        cursor = 0.0
        part = 0
        for pause in pauses:
            if pause.source_time > cursor + 0.005:
                label = f"vseg_{part}"
                filters.append(
                    f"[1:v]trim=start={cursor:.3f}:end={pause.source_time:.3f},"
                    f"setpts=PTS-STARTPTS[{label}]"
                )
                labels.append(label)
                part += 1
            frame_duration = min(1 / 30, max(0.001, source_duration - pause.source_time))
            label = f"vpause_{part}"
            filters.append(
                f"[1:v]trim=start={pause.source_time:.3f}:duration={frame_duration:.3f},"
                f"setpts=PTS-STARTPTS,fps=30,"
                f"tpad=stop_mode=clone:stop_duration={max(0.0, pause.duration - frame_duration):.3f}[{label}]"
            )
            labels.append(label)
            cursor = pause.source_time
            part += 1
        if source_duration > cursor + 0.005:
            label = f"vseg_{part}"
            filters.append(
                f"[1:v]trim=start={cursor:.3f}:end={source_duration:.3f},"
                f"setpts=PTS-STARTPTS[{label}]"
            )
            labels.append(label)
        filters.append(
            "".join(f"[{label}]" for label in labels)
            + f"concat=n={len(labels)}:v=1:a=0,fps=30[clip_timeline]"
        )
        filters.append(f"[clip_timeline]{scale}[clip]")
        return ";".join(filters)

    @staticmethod
    def _source_audio_filters(
        *,
        source_duration: float,
        output_duration: float,
        pause_segments: list[TimelinePause],
        has_audio: bool,
    ) -> list[str]:
        if not has_audio:
            return []
        pauses = _active_pauses(source_duration, pause_segments)
        audio_format = "aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        fade_duration = min(_AUDIO_FADE_SECONDS, output_duration)
        fade_start = max(0.0, output_duration - fade_duration)
        if not pauses:
            return [
                f"[1:a]atrim=end={source_duration:.3f},asetpts=PTS-STARTPTS,"
                f"{audio_format},afade=t=out:st={fade_start:.3f}:d={fade_duration:.3f}[trimmed_audio]"
            ]

        filters: list[str] = []
        labels: list[str] = []
        cursor = 0.0
        part = 0
        for pause in pauses:
            if pause.source_time > cursor + 0.005:
                label = f"aseg_{part}"
                filters.append(
                    f"[1:a]atrim=start={cursor:.3f}:end={pause.source_time:.3f},"
                    f"asetpts=PTS-STARTPTS,{audio_format}[{label}]"
                )
                labels.append(label)
                part += 1
            label = f"apause_{part}"
            filters.append(
                f"anullsrc=r=48000:cl=stereo:d={pause.duration:.3f},"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{label}]"
            )
            labels.append(label)
            cursor = pause.source_time
            part += 1
        if source_duration > cursor + 0.005:
            label = f"aseg_{part}"
            filters.append(
                f"[1:a]atrim=start={cursor:.3f}:end={source_duration:.3f},"
                f"asetpts=PTS-STARTPTS,{audio_format}[{label}]"
            )
            labels.append(label)
        filters.append(
            "".join(f"[{label}]" for label in labels)
            + f"concat=n={len(labels)}:v=0:a=1,{audio_format},"
            f"afade=t=out:st={fade_start:.3f}:d={fade_duration:.3f}[trimmed_audio]"
        )
        return filters

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
        source_duration: float,
        output_duration: float,
        timed_boxes: list[tuple[Any, Any]],
        scroll_steps: list[ScrollStep],
        pause_segments: list[TimelinePause],
    ) -> None:
        manifest = {
            "template": self.template.name,
            "source_video": str(source_video),
            "source_start": source_start,
            "source_duration": source_duration,
            "duration": output_duration,
            "speech_end": timed_boxes[-1][0].end if timed_boxes else content.words[-1].end,
            "audio_tail_seconds": round(
                max(0.0, output_duration - (timed_boxes[-1][0].end if timed_boxes else content.words[-1].end)), 3
            ),
            "word_count": len(content.words),
            "vocabulary_count": len(content.vocabulary),
            "pause_segments": [
                {
                    "source_time": round(pause.source_time, 3),
                    "start": round(pause.start, 3),
                    "end": round(pause.end, 3),
                    "duration": round(pause.duration, 3),
                }
                for pause in pause_segments
            ],
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
    def _build_scroll_steps(timed_boxes: list[tuple[Any, Any]]) -> tuple[list[ScrollStep], list[TimelinePause]]:
        """以当前朗读词为锚点滚动；每次滚动在输出时间轴中插入一段静音冻结。"""
        steps: list[ScrollStep] = []
        pauses: list[TimelinePause] = []
        offset = 0
        trigger_y = 1540
        target_y = 1110
        inserted_pause = 0.0
        for word, box in timed_boxes:
            visible_y = box.y - offset
            if visible_y <= trigger_y:
                continue
            target_offset = max(offset, box.y - target_y)
            if target_offset == offset:
                continue
            start = max(0.0, word.start + inserted_pause)
            end = start + _SCROLL_PAUSE_SECONDS
            steps.append(ScrollStep(start, end, offset, target_offset))
            pauses.append(TimelinePause(word.start, start, end))
            inserted_pause += _SCROLL_PAUSE_SECONDS
            offset = target_offset
        return steps, pauses

    @staticmethod
    def _shift_timed_boxes_for_pauses(
        timed_boxes: list[tuple[StudyWord, Any]],
        pause_segments: list[TimelinePause],
    ) -> list[tuple[StudyWord, Any]]:
        shifted: list[tuple[StudyWord, Any]] = []
        for word, box in timed_boxes:
            shift = StudyCardRenderer._total_pause_duration_before(word.start, pause_segments)
            shifted.append((StudyWord(word.text, word.start + shift, word.end + shift), box))
        return shifted

    @staticmethod
    def _total_pause_duration_before(source_time: float, pause_segments: list[TimelinePause]) -> float:
        return sum(pause.duration for pause in pause_segments if pause.source_time <= source_time + 0.0005)

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
    def _underline_progress_width(box_width: int, start: float, end: float, timestamp: float) -> int:
        """按当前词朗读进度计算红线长度；用于预渲染透明红线层。"""
        if box_width <= 0 or end <= start:
            raise ValueError("红线宽度与时间轴必须有效")
        if timestamp <= start:
            return 0
        if timestamp >= end:
            return box_width
        return int(round(box_width * (timestamp - start) / (end - start)))

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


def _active_pauses(source_duration: float, pause_segments: list[TimelinePause]) -> list[TimelinePause]:
    return [
        pause for pause in pause_segments
        if pause.duration > 0 and 0 <= pause.source_time <= source_duration - 0.001
    ]

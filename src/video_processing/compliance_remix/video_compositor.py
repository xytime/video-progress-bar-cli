# -*- coding: utf-8 -*-
"""9:16 竖屏合成与时长验证。

仅使用清单中经人工批准的镜头；本模块不提供自动画面风险识别或去脸保证。

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-25 | Antigravity | 初始创建，实现 B-Roll 切割、动态卡片叠加与 9:16 竖屏滤镜链渲染 |
| 1.2.0 | 2026-10-25 | GPT-6.1 Sol | 精确滤镜能力检测、内容缓存和实际时长有界拼接 |
| 1.1.0   | 2026-10-25 | Antigravity | 修复 PROJECT_ROOT 路径层级，增加 libass 滤镜探测与 imageio_ffmpeg 自动选路，支持 B-Roll 自动循环对齐音频时长杜绝尾部截断 |
"""

from __future__ import annotations

import hashlib
import math
import re
import argparse
import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from video_processing.utils.video_metadata import resolve_ffmpeg_cmd

logger = logging.getLogger(__name__)


class VideoCompositor:
    """9:16 竖屏视频合成器。"""

    def __init__(self, ffmpeg_bin: Optional[str] = None):
        candidates = [str(ffmpeg_bin)] if ffmpeg_bin else [resolve_ffmpeg_cmd(None)]
        try:
            import imageio_ffmpeg
            candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
        except Exception:
            pass
        self.ffmpeg_bin = next((c for c in candidates if c and self._supports_ass_filter(c)), None)
        if self.ffmpeg_bin is None:
            raise RuntimeError("所有 FFmpeg 候选均缺少 ass 滤镜，拒绝生产")

    @staticmethod
    def _supports_ass_filter(ffmpeg_path: str) -> bool:
        try:
            res = subprocess.run([ffmpeg_path, "-filters"], capture_output=True, text=True, timeout=5)
            return res.returncode == 0 and any(
                re.match(r"^\s*[TSC.]{3}\s+ass\s+", line) for line in res.stdout.splitlines())
        except Exception:
            return False

    @staticmethod
    def probe_duration(path):
        if not Path(path).is_file():
            raise ValueError("媒体文件不存在")
        from video_processing.utils.video_metadata import _resolve_ffprobe_cmd
        result = VideoCompositor._run_media(
            [_resolve_ffprobe_cmd(), "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", str(path)], timeout=15, capture_output=True)
        metadata = json.loads(result.stdout)
        if not any(stream.get("codec_type") in {"video", "audio"} for stream in metadata.get("streams", [])):
            raise ValueError("产物不存在有效媒体流")
        duration = float(metadata["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("实际媒体时长必须为有限正数")
        return duration

    @staticmethod
    def _digest(path):
        h = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _run_media(command, *, timeout, check=True, capture_output=False):
        process = subprocess.Popen(command, stdout=subprocess.PIPE if capture_output else None,
                                   stderr=subprocess.PIPE if capture_output else None,
                                   start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def extract_and_concat_broll(
        self,
        source_video: Path | str,
        shots: List[Tuple[float, float]],
        output_concat_video: Path | str,
        cache_dir: Path | str,
        target_w: int = 1920,
        target_h: int = 1080,
        min_duration: Optional[float] = None,
    ) -> Path:
        """从源视频中切取纯净 B-Roll 片段并拼接为无声母带视频。

        Args:
            source_video: 原始视频路径。
            shots: [(start_time_s, duration_s), ...] 镜头时码列表。
            output_concat_video: 拼接后的视频文件保存路径。
            cache_dir: 切片临时存储目录。
            target_w: 切片统一宽度。
            target_h: 切片统一高度。
            min_duration: 目标最小持续时长（如口播母带总秒数），若不足则自动无缝循环镜头以防 -shortest 截断音频尾部。
        """
        src = Path(source_video)
        source_duration = self.probe_duration(src)
        if not shots or (min_duration is not None and
                         (not math.isfinite(min_duration) or min_duration <= 0)):
            raise ValueError("镜头非空且目标时长必须为有限正数")
        for start, duration in shots:
            if not math.isfinite(start) or start < 0 or start >= source_duration or not math.isfinite(duration) or duration <= 0:
                raise ValueError("镜头时码无效或超出源片")
        out_concat = Path(output_concat_video)
        cdir = Path(cache_dir)
        fingerprint = hashlib.sha256(json.dumps([self._digest(src), shots, target_w, target_h,
                                                  self.ffmpeg_bin], sort_keys=True).encode()).hexdigest()
        clips_dir = cdir / fingerprint
        clips_dir.mkdir(parents=True, exist_ok=True)
        clip_files = []
        for i, (start, duration) in enumerate(shots):
            clip = clips_dir / f"clip_{i:03d}.mp4"
            try:
                actual = self.probe_duration(clip)
            except Exception:
                temporary = clip.with_name(clip.stem + ".tmp.mp4")
                self._run_media([self.ffmpeg_bin, "-y", "-ss", str(start), "-t", str(duration),
                                "-i", str(src), "-vf", f"scale={target_w}:{target_h}", "-r", "25",
                                "-c:v", "libx264", "-preset", "ultrafast", "-an", str(temporary)],
                               check=True, capture_output=True, timeout=300)
                actual = self.probe_duration(temporary)
                temporary.replace(clip)
            clip_files.append((clip, actual))
        cycle_duration = sum(d for _, d in clip_files)
        target_duration = min_duration if min_duration is not None else cycle_duration
        repeats = math.ceil((target_duration + 0.1) / cycle_duration)
        if repeats > 10000:
            raise ValueError("镜头重复次数超过安全上限")
        listing = clips_dir / "concat_list.txt"
        listing.write_text("".join(f"file '{clip.name}'\n" for _ in range(repeats)
                                   for clip, _ in clip_files), encoding="utf-8")
        temporary = out_concat.with_name(out_concat.stem + ".tmp.mp4")
        out_concat.parent.mkdir(parents=True, exist_ok=True)
        self._run_media([self.ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", str(temporary)], check=True, capture_output=True, timeout=600)
        if self.probe_duration(temporary) + 0.02 < target_duration:
            raise ValueError("拼接画面短于完整口播，拒绝渲染")
        temporary.replace(out_concat)
        return out_concat

    def build_filter_complex(
        self,
        cards_with_timings: List[Tuple[int, float, float]],
        ass_path: Optional[Path | str] = None,
        canvas_w: int = 1080,
        canvas_h: int = 1920,
        fg_w: int = 1080,
        fg_h: int = 608,
        fg_y: int = 656,
        card_x: int = 50,
        card_y: int = 1310,
    ) -> str:
        """构建竖屏高斯模糊背景 + 居中高清原画 + 栏目遮罩 + 动态卡片 + ASS 字幕的完整滤镜链。"""
        # 基础画面处理
        filters = [
            # 0:v 分离为背景流与前景流
            "[0:v]split=2[v_bg_in][v_fg_in]",
            # 背景流：缩放填满 1080x1920 + 裁剪 + 高斯模糊 (boxblur=25:5) + 压暗 40%
            f"[v_bg_in]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,crop={canvas_w}:{canvas_h},boxblur=25:5,colorchannelmixer=aa=1.0:rr=0.6:gg=0.6:bb=0.6[v_bg]",
            # 前景流：精确缩放为 1080x608 居中原画
            f"[v_fg_in]scale={fg_w}:{fg_h}[v_fg]",
            # 前景叠加到背景 y=656
            f"[v_bg][v_fg]overlay=0:{fg_y}[v_merged]",
            # 叠加前景画框与右上角栏目徽标遮罩 (input 2:v)
            "[v_merged][2:v]overlay=0:0[v_hdr]",
        ]

        # 动态数据卡片叠加 (inputs 3, 4, ...)
        last_tag = "v_hdr"
        for idx, (input_idx, start_t, end_t) in enumerate(cards_with_timings):
            next_tag = f"v_c{idx+1}"
            filters.append(
                f"[{last_tag}][{input_idx}:v]overlay={card_x}:{card_y}:enable='between(t,{start_t:.2f},{end_t:.2f})'[{next_tag}]"
            )
            last_tag = next_tag

        # ASS 字幕层
        if ass_path:
            escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            filters.append(f"[{last_tag}]ass=filename='{escaped_ass}'[vout]")
        else:
            filters.append(f"[{last_tag}]null[vout]")

        return "; ".join(filters)

    def render_final_vertical_video(
        self,
        broll_video: Path | str,
        master_audio: Path | str,
        overlay_image: Path | str,
        cards_info: List[Tuple[Path | str, float, float]],
        ass_subtitles: Path | str,
        output_video: Path | str,
        crf: int = 20,
        preset: str = "fast",
    ) -> Path:
        """执行全要素 9:16 竖屏二创成片渲染。

        Args:
            broll_video: 拼接完成的纯净 B-Roll 视频。
            master_audio: 包含 TTS 与 BGM 的音频母带。
            overlay_image: 1080x1920 画框与水印遮罩图。
            cards_info: [(card_png_path, start_time_s, end_time_s), ...]
            ass_subtitles: ASS 字幕文件。
            output_video: 最终成片输出路径。
            crf: x264 编码质量因子 (默认 20 保证画质)。
            preset: x264 编码速度预设。
        """
        out_p = Path(output_video)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        duration = self.probe_duration(master_audio)
        if self.probe_duration(broll_video) + 0.02 < duration:
            raise ValueError("B-Roll 不足以覆盖完整口播")
        temporary = out_p.with_name(out_p.stem + ".tmp.mp4")
        cmd = [self.ffmpeg_bin, "-y"]

        # 输入 0: B-Roll 视频
        cmd.extend(["-i", str(broll_video)])
        # 输入 1: 音频母带
        cmd.extend(["-i", str(master_audio)])
        # 输入 2: 画框与徽标遮罩
        cmd.extend(["-i", str(overlay_image)])

        # 输入 3..N: 动态财经卡片
        cards_timings_for_filter = []
        for i, (card_p, start_t, end_t) in enumerate(cards_info):
            input_idx = 3 + i
            cmd.extend(["-i", str(card_p)])
            cards_timings_for_filter.append((input_idx, start_t, end_t))

        filter_graph = self.build_filter_complex(cards_timings_for_filter, ass_subtitles)

        cmd.extend([
            "-filter_complex", filter_graph,
            "-map", "[vout]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf),
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration),
            str(temporary),
        ])

        logger.info(f"Starting FFmpeg vertical video render to {out_p}...")
        self._run_media(cmd, check=True, timeout=3600)
        if self.probe_duration(temporary) + 0.05 < duration:
            raise ValueError("成片截断了口播")
        temporary.replace(out_p)
        logger.info(f"Successfully rendered master vertical video: {out_p}")
        return out_p


def main():
    raise PermissionError("媒体生产必须通过 scripts/compliance_remix.py 的持久审批入口")


if __name__ == "__main__":
    main()

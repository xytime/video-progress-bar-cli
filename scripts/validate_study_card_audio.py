#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用本地 Whisper 验证英语世界学习卡的最终音频收尾。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-09-01 | Codex | 新增 16kHz 单声道 Whisper 末词完整性与下一词泄漏门禁。 |
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import imageio_ffmpeg  # noqa: E402

from video_processing.study_cards.audio_qa import analyse_audio_tail  # noqa: E402
from video_processing.study_cards.timeline_guard import validate_source_caption_boundary  # noqa: E402
from video_processing.utils.video_metadata import get_video_duration_ffprobe  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mp4", required=True, type=Path, help="最终学习卡 MP4")
    parser.add_argument("--timeline", required=True, type=Path, help="与成片对应的 enriched timeline")
    parser.add_argument("--manifest", required=True, type=Path, help="与成片对应的 manifest")
    parser.add_argument("--report", required=True, type=Path, help="输出机器可读 QA 报告")
    parser.add_argument("--model", default="small", help="本地 Whisper 模型名")
    return parser


def _flatten_whisper_words(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for segment in result.get("segments", []) or []:
        if not isinstance(segment, Mapping):
            continue
        for word in segment.get("words", []) or []:
            if isinstance(word, Mapping):
                words.append(dict(word))
    return words


def _extract_audio(mp4: Path, output: Path) -> None:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(mp4), "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"无法提取 16kHz 单声道音频：{completed.stderr[-1000:]}")


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = _parser().parse_args()
    try:
        timeline = json.loads(args.timeline.read_text(encoding="utf-8"))
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(timeline, dict) or not isinstance(manifest, dict):
            raise ValueError("timeline 与 manifest 必须是 JSON 对象")
        validate_source_caption_boundary(timeline, timeline_path=args.timeline)
        actual_duration = float(get_video_duration_ffprobe(args.mp4))
        manifest_duration = float(manifest["duration"])
        if abs(actual_duration - manifest_duration) > 0.25:
            raise ValueError(
                f"manifest 与 MP4 时长不一致：manifest={manifest_duration:.3f}s，"
                f"ffprobe={actual_duration:.3f}s"
            )
        with tempfile.TemporaryDirectory(prefix="study_card_audio_qa_") as temp_dir:
            audio_path = Path(temp_dir) / "audio_16k_mono.wav"
            _extract_audio(args.mp4, audio_path)
            import whisper

            model = whisper.load_model(args.model)
            transcription = model.transcribe(
                str(audio_path), language="en", word_timestamps=True, fp16=False,
            )
        report = analyse_audio_tail(
            timeline.get("words") or [],
            _flatten_whisper_words(transcription),
            output_duration=actual_duration,
        )
        report = {
            "state": "PASS" if report.get("passed") else "FAIL",
            "mp4": str(args.mp4.resolve()),
            "timeline": str(args.timeline.resolve()),
            "manifest": str(args.manifest.resolve()),
            "whisper_model": args.model,
            "sample_rate": 16000,
            "channels": 1,
            **report,
        }
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, ImportError) as exc:
        failure = {"state": "FAIL", "failure_kind": "qa_execution_error", "error": str(exc)}
        _write_report(args.report, failure)
        print(f"validate_study_card_audio: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

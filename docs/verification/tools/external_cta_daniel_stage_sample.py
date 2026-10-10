"""Daniel 首尾包装清理的隔离样本修订；不是生产自动检测器。

用户反馈旧版包装仍有残留，授权本条从讲者站在台上开始。
21.60–914.28 秒来自原分辨率及首字检查，仅用于这条已核对摘要的样本。
在项目媒体沙盒中运行：python external_cta_daniel_stage_sample.py <实验目录>。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-10 | Codex | 修订指定样本首尾范围，保护讲话并验证字幕平移与音画对应 |
"""
from pathlib import Path
import copy
import json
import math
import sys
import time

import cv2
import numpy as np
import pysubs2

from external_cta_daniel_sample import EXPECTED, digest, encode, frame_at, waveform
from video_processing.core import ffmpeg_slot
from video_processing.processors.speech_opening import media_info


START, END = 21.60, 914.28
OUTPUT = "Daniel_vertical_stage_only_v2.mp4"


def run(root):
    ffmpeg_slot._DIRECTORY = root / "ffmpeg-slot"
    before = {name: digest(root / name) for name in EXPECTED}
    if before != EXPECTED:
        raise ValueError("UNVERIFIED_SAMPLE_INPUT")
    source = root / "NRkHdspgnI8.mp4"
    vertical = root / "NRkHdspgnI8_vertical.mp4"
    source_info, vertical_info = media_info(source), media_info(vertical)
    if abs(source_info["duration"] - vertical_info["duration"]) > .1:
        raise ValueError("UNVERIFIED_VERTICAL_TIMELINE")
    subtitles = pysubs2.load(str(root / "NRkHdspgnI8.ass"))
    if max(e.end for e in subtitles) / 1000 >= END:
        raise ValueError("SPEECH_SUBTITLE_CROSSES_END")
    for stamp in (START, END - .04):
        if frame_at(source, stamp).shape != (720, 1280, 3):
            raise ValueError("UNVERIFIED_SAMPLE_FRAME")
    output_path = root / OUTPUT
    output = encode(vertical, output_path, START, END)
    result = {
        "type": "single_real_sample_revision_not_general_detection",
        "input_sha256": before,
        "retained_original_interval": [START, END],
        "removed_original_intervals": [[0, START], [END, source_info["duration"]]],
        "removed_seconds": round(source_info["duration"] - (END - START), 6),
        "output": output,
    }
    shifted = copy.deepcopy(subtitles)
    shifted.events = []
    changed_leading_events = 0
    for event in subtitles:
        if event.end <= START * 1000 or event.start >= END * 1000:
            continue
        mapped = copy.deepcopy(event)
        mapped.start = max(0, event.start - round(START * 1000))
        mapped.end = min(round(END * 1000), event.end) - round(START * 1000)
        changed_leading_events += event.start < START * 1000
        shifted.events.append(mapped)
    ass_path = root / "Daniel_vertical_stage_only_v2.ass"
    shifted.save(str(ass_path))
    reloaded = pysubs2.load(str(ass_path))
    if not shifted.equals(reloaded) or len(reloaded) != len(subtitles):
        raise ValueError("SUBTITLE_MAPPING_CHANGED")
    # 文本、样式及布局不改；仅时间戳前移，首条原本覆盖片头的字幕从零开始。
    for old, new in zip(subtitles, reloaded):
        old_fields, new_fields = old.as_dict(), new.as_dict()
        for key in ("start", "end"):
            old_fields.pop(key)
            new_fields.pop(key)
        if old_fields != new_fields:
            raise ValueError("SUBTITLE_CONTENT_CHANGED")
    result["subtitles"] = {
        "file": ass_path.name, "sha256": digest(ass_path),
        "events": len(reloaded), "time_shift_seconds": -START,
        "leading_events_clamped_to_zero": changed_leading_events,
        "content_styles_unchanged": True,
        "last_event_end_seconds": max(e.end for e in reloaded) / 1000,
    }
    result["preserved_audio_checks"] = []
    for stamp, seconds in [(0, 10), (60, 7), (887, 4)]:
        a = waveform(vertical, stamp + START, seconds)
        b = waveform(output_path, stamp, seconds)
        if len(a) != len(b):
            raise ValueError("PRESERVED_AUDIO_SAMPLE_COUNT_CHANGED")
        correlation = float(np.corrcoef(a, b)[0, 1])
        if not math.isfinite(correlation) or correlation < .98:
            raise ValueError("PRESERVED_AUDIO_CHANGED")
        result["preserved_audio_checks"].append({
            "output_seconds": stamp, "original_seconds": stamp + START,
            "duration_seconds": seconds, "correlation": correlation,
        })
    result["preserved_video_checks"] = []
    for stamp in (0, 1, 7, 60, 600, 911.48 - START, END - START - .04):
        a, b = frame_at(vertical, stamp + START), frame_at(output_path, stamp)
        psnr = float(cv2.PSNR(a, b))
        if a.shape != b.shape or psnr < 30:
            raise ValueError("PRESERVED_VIDEO_CONTENT_CHANGED")
        result["preserved_video_checks"].append({
            "output_seconds": stamp, "original_seconds": stamp + START, "psnr_db": psnr,
        })
    for stamp, name in ((0, "v2-first-frame.png"), (END - START - .04, "v2-last-frame.png")):
        if not cv2.imwrite(str(root / name), frame_at(output_path, stamp)):
            raise ValueError("EVIDENCE_FRAME_WRITE_FAILED")
    result["input_bytes_unchanged"] = {name: digest(root / name) == sha for name, sha in before.items()}
    if not all(result["input_bytes_unchanged"].values()):
        raise ValueError("INPUT_MODIFIED")
    result["status"] = "VERIFIED_LOCAL_SAMPLE"
    return result


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve()
    started = time.monotonic()
    try:
        evidence = run(directory)
    except Exception as exc:
        evidence = {"status": "KEEP_ORIGINAL", "reason": str(exc), "error_type": type(exc).__name__,
                    "production_modified": False, "selected_input": "NRkHdspgnI8.mp4"}
    evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
    (directory / "stage-sample-result-v2.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
    print(json.dumps(evidence, ensure_ascii=False), flush=True)
    raise SystemExit(0 if evidence["status"] == "VERIFIED_LOCAL_SAMPLE" else 1)

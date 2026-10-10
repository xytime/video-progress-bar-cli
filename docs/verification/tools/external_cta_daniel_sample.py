"""Daniel 原片外部平台片尾扣除的隔离实验；不是通用检测器或生产入口。

输入只接受已核对摘要的真实素材副本；917秒是本样本已验证的静态鸣谢帧。
从该帧顺序定位转场，不把样本时间、OCR关键词推广成其他视频删除规则。
用项目隔离环境运行：python external_cta_daniel_sample.py <实验目录>。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-10 | Codex | 真实片尾提取、独立副本、时间轴与原文件保护证据 |
"""
from pathlib import Path
import hashlib
import json
import math
import subprocess
import sys
import time

import cv2
import numpy as np
import pysubs2

from video_processing.core import ffmpeg_slot
from video_processing.processors.speech_opening import media_info, validate_prepared
from video_processing.utils.video_metadata import resolve_ffmpeg_cmd


EXPECTED = {
    "NRkHdspgnI8.mp4": "822c1edb2550a88e64ecec78414a429e8ebf6a4f77233f13559db3f5639436be",
    "NRkHdspgnI8_vertical.mp4": "72988722ec9c4466bd0e8e950123bb56367e3bc6153f4f7ec311034e1aad675f",
    "NRkHdspgnI8.ass": "486cd89569e4f4398ad62a4649205ed732367805abdb4a157cb68e10c4107d9b",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def execute(args, timeout=180):
    return subprocess.run(args, capture_output=True, check=True, timeout=timeout)


def encode(source, destination, start, end):
    pending = destination.with_name(destination.stem + ".pending.mp4")
    started = time.monotonic()
    try:
        execute([resolve_ffmpeg_cmd(), "-v", "error", "-y", "-ss", str(start),
                 "-i", str(source), "-t", str(end - start), "-map", "0:v:0",
                 "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", "-threads", "2", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", str(pending)], timeout=600)
        validate_prepared(pending, end - start)
        execute([resolve_ffmpeg_cmd(), "-v", "error", "-xerror", "-i", str(pending),
                 "-map", "0:v:0", "-map", "0:a:0", "-threads", "2", "-f", "null", "-"], timeout=180)
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)
    info = media_info(destination)
    return {"file": destination.name, "sha256": digest(destination),
            "bytes": destination.stat().st_size, "seconds_with_decode_check": round(time.monotonic() - started, 3),
            "duration": info["duration"], "streams": {kind: {key: info["streams"][kind].get(key)
                     for key in ("start_time", "duration", "width", "height", "sample_rate", "channels")}
                     for kind in ("video", "audio")}}


def waveform(source, start, seconds):
    result = execute([resolve_ffmpeg_cmd(), "-v", "error", "-ss", str(start), "-i", str(source),
                      "-t", str(seconds), "-vn", "-ar", "16000", "-ac", "1", "-f", "f32le", "-"])
    return np.frombuffer(result.stdout, dtype="<f4")


def frame_at(path, seconds):
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(seconds * cap.get(cv2.CAP_PROP_FPS)))
        ok, frame = cap.read()
        if not ok:
            raise ValueError("FRAME_DECODE_FAILED")
        return frame
    finally:
        cap.release()


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
    cap = cv2.VideoCapture(str(source))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps != 25:
        raise ValueError("UNVERIFIED_SAMPLE_FRAME_RATE")
    anchor = 917.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(anchor * fps))
    ok, reference = cap.read()
    if not ok:
        raise ValueError("MISSING_ANCHOR")
    boundary = None
    for i in range(1, 76):
        ok, frame = cap.read()
        if not ok:
            break
        # 本样本静态鸣谢卡逐帧解码完全相同；首个可测变化即片尾淡入。
        if float(np.abs(frame.astype(np.int16) - reference.astype(np.int16)).mean()) > .01:
            boundary = anchor + i / fps
            break
    cap.release()
    if boundary is None or not 918 <= boundary < 919:
        raise ValueError("UNVERIFIED_SAMPLE_TRANSITION")
    end_card = root / "external-platform-end-card.png"
    cv2.imwrite(str(end_card), frame_at(source, 920))
    ocr = execute(["/opt/homebrew/bin/tesseract", str(end_card), "stdout", "--psm", "11"]).stdout.decode()
    if "Thank you for watching" not in ocr or "@tedxnorthernquarter" not in ocr.lower():
        raise ValueError("SAMPLE_END_CARD_NOT_CONFIRMED")
    subtitles = pysubs2.load(str(root / "NRkHdspgnI8.ass"))
    latest_end = max(event.end for event in subtitles) / 1000
    if latest_end + 2 > boundary:
        raise ValueError("SUBTITLE_CONTENT_TOO_CLOSE_TO_CUT")
    result = {"type": "single_real_sample_experiment_not_general_detection", "input_sha256": before,
              "verified_interval": [0, boundary], "removed_interval": [boundary, source_info["duration"]],
              "removed_seconds": round(source_info["duration"] - boundary, 6),
              "ocr": ocr, "last_subtitle_end_seconds": latest_end, "outputs": []}
    for src, name, start, end in [
        (source, "Daniel_external_platform_excerpt.mp4", boundary, source_info["duration"]),
        (source, "Daniel_source_without_external_cta.mp4", 0, boundary),
        (vertical, "Daniel_vertical_without_external_cta.mp4", 0, boundary),
    ]:
        output = encode(src, root / name, start, end)
        result["outputs"].append(output)
        print(json.dumps(output), flush=True)
    output_vertical = root / "Daniel_vertical_without_external_cta.mp4"
    waveform_results = []
    for start, seconds in [(0, 20), (22, 10), (906, 7)]:
        a, b = waveform(vertical, start, seconds), waveform(output_vertical, start, seconds)
        if len(a) != len(b):
            raise ValueError("PRESERVED_AUDIO_SAMPLE_COUNT_CHANGED")
        correlation = float(np.corrcoef(a, b)[0, 1])
        if not math.isfinite(correlation) or correlation < .98:
            raise ValueError("PRESERVED_AUDIO_CHANGED")
        waveform_results.append({"start_seconds": start, "duration_seconds": seconds, "correlation": correlation})
    result["preserved_audio_checks"] = waveform_results
    visual_results = []
    for stamp in [0, 5, 15, 23, 120, 600, 911, 917, boundary - .04]:
        a, b = frame_at(vertical, stamp), frame_at(output_vertical, stamp)
        psnr = float(cv2.PSNR(a, b))
        if a.shape != b.shape or psnr < 30:
            raise ValueError("PRESERVED_VIDEO_CONTENT_CHANGED")
        visual_results.append({"seconds": stamp, "psnr_db": psnr})
    result["preserved_video_checks"] = visual_results
    copied_ass = root / "Daniel_vertical_without_external_cta.ass"
    copied_ass.write_bytes((root / "NRkHdspgnI8.ass").read_bytes())
    result["subtitles_bytes_unchanged"] = digest(copied_ass) == before["NRkHdspgnI8.ass"]
    result["input_bytes_unchanged"] = {name: digest(root / name) == value for name, value in before.items()}
    if not all(result["input_bytes_unchanged"].values()) or not result["subtitles_bytes_unchanged"]:
        raise ValueError("INPUT_OR_SUBTITLE_MODIFIED")
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
    (directory / "sample-result.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
    print(json.dumps(evidence, ensure_ascii=False), flush=True)
    raise SystemExit(0 if evidence["status"] == "VERIFIED_LOCAL_SAMPLE" else 1)

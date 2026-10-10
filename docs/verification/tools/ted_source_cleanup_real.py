"""在项目媒体沙盒中复现真实首尾检测、Daniel 整片与首末讲话证据。

输入为已复制的本地原片，不下载、不发布，不用模板参考条目证明泛化准确率。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-10 | Codex | 逐片重新检测与整片编码、缓存、原片摘要及离线 ASR 对照。 |
"""
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from video_processing.core import ffmpeg_slot
from video_processing.processors import ted_source_cleanup as cleanup


def waveform(source, start, seconds):
    raw = subprocess.run([cleanup.media.resolve_ffmpeg_cmd(), "-v", "error", "-ss", str(start),
        "-i", str(source), "-t", str(seconds), "-vn", "-ar", "16000", "-ac", "1", "-f", "f32le", "pipe:1"],
        check=True, capture_output=True, timeout=60).stdout
    return np.frombuffer(raw, dtype="<f4").copy()


def run(root):
    ffmpeg_slot._DIRECTORY = root / "ffmpeg-slot"
    cases = json.loads((root / "cases.json").read_text())
    results = []
    for case in cases:
        source = root / (case["id"] + ".mp4")
        started = time.monotonic()
        before = cleanup.media.sha256(source)
        info = cleanup.media.media_info(source)
        decision = cleanup.detect_packaging(source, info)
        expected_end = case.get("expected_end", info["duration"])
        passed = (abs(decision["offset_seconds"] - case["expected_offset"]) < .001
                  and abs(decision["end_seconds"] - expected_end) < .001)
        results.append({"id": case["id"], "scenario": case["scenario"],
                        "source_sha256": before, "source_duration": info["duration"],
                        "expected_interval": [case["expected_offset"], expected_end],
                        "decision": decision, "matches_expected": passed,
                        "seconds": round(time.monotonic() - started, 3)})
        print(case["id"], decision["offset_seconds"], decision["end_seconds"], passed, flush=True)
    source = root / "NRkHdspgnI8.mp4"
    selected, receipt = cleanup.prepare_source(source, root / "speech_opening/NRkHdspgnI8")
    if selected == source:
        raise ValueError(f"DANIEL_NOT_CLEANED: {receipt}")
    assert cleanup.prepare_source(source, selected.parent) == (selected, receipt)
    import torch
    import whisper
    torch.set_num_threads(2)
    model = whisper.load_model("base", device="cpu", download_root=str(root.parents[1] / "cache/whisper"))
    speech = {}
    for edge, original_start, output_start, seconds in [
            ("opening", 18, 0, 14), ("ending", 906, 885, 8)]:
        texts = {}
        for kind, path, start in (("original", source, original_start), ("prepared", selected, output_start)):
            result = model.transcribe(waveform(path, start, seconds), language="en", fp16=False,
                                      temperature=0, word_timestamps=True)
            texts[kind] = {"text": result["text"], "words": [
                {"word": w["word"], "start": start + w["start"], "end": start + w["end"]}
                for segment in result["segments"] for w in segment.get("words", [])]}
        speech[edge] = texts
    alignment = []
    for stamp, seconds in ((0, 10), (60, 7), (889, 4)):
        original = waveform(source, receipt["offset_seconds"] + stamp, seconds)
        prepared = waveform(selected, stamp, seconds)
        correlation = float(np.corrcoef(original, prepared)[0, 1])
        assert correlation > .98
        alignment.append({"output_start": stamp, "source_start": receipt["offset_seconds"] + stamp,
                          "seconds": seconds, "correlation": correlation})
    unchanged = {case["id"]: cleanup.media.sha256(root / (case["id"] + ".mp4")) == result["source_sha256"]
                 for case, result in zip(cases, results)}
    import cv2
    visual = []
    for stamp in (0, 1, 7, 60, 600, 890.44, 894.08):
        frames = []
        for path, seconds in ((source, receipt["offset_seconds"] + stamp), (selected, stamp)):
            capture = cv2.VideoCapture(str(path))
            capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
            ok, frame = capture.read()
            capture.release()
            assert ok
            frames.append(frame)
        psnr = float(cv2.PSNR(*frames))
        assert psnr > 30
        visual.append({"output_seconds": stamp, "psnr_db": min(psnr, 100)})
    import copy
    import pysubs2
    subtitles = pysubs2.load(str(source.with_suffix(".ass")))
    shifted = copy.deepcopy(subtitles)
    shifted.events = []
    for event in subtitles:
        if event.end <= receipt["offset_seconds"] * 1000 or event.start >= receipt["end_seconds"] * 1000:
            continue
        mapped = copy.deepcopy(event)
        mapped.start = max(0, event.start - round(receipt["offset_seconds"] * 1000))
        mapped.end = min(round(receipt["end_seconds"] * 1000), event.end) - round(receipt["offset_seconds"] * 1000)
        shifted.events.append(mapped)
    assert len(shifted) == len(subtitles)
    assert [e.text for e in shifted] == [e.text for e in subtitles]
    shifted.save(str(selected.with_suffix(".ass")))
    for start, length, name in ((0, 15, "opening-preview.mp4"), (886.16, 8, "ending-preview.mp4")):
        subprocess.run([cleanup.media.resolve_ffmpeg_cmd(), "-v", "error", "-y", "-ss", str(start),
            "-i", str(selected), "-t", str(length), "-c:v", "libx264", "-threads", "2", "-c:a", "aac", str(root / name)],
            check=True, capture_output=True, timeout=60)
    evidence = {"kind": "real_local_sources_not_accuracy_estimate", "cases": results,
                "daniel": {"receipt": receipt, "cache_reused": True, "speech": speech,
                           "audio_alignment": alignment, "visual_alignment": visual,
                           "existing_subtitle_mapping": {"events": len(shifted), "texts_unchanged": True,
                               "last_end_seconds": max(e.end for e in shifted) / 1000,
                               "kind": "real_existing_subtitle_timeline_not_new_transcription"}},
                "original_bytes_unchanged": unchanged}
    (root / "results.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    assert all(c["matches_expected"] for c in results) and all(unchanged.values())
    print("REAL_SOURCE_VERIFICATION_COMPLETE", flush=True)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())

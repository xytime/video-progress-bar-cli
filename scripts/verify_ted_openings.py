"""在隔离测试快照中复现真实开场验证；不下载、不发布、不读取生产数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 本地真实样本决策、字节保护、解码及整片成本收据。 |
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from video_processing.core import ffmpeg_slot
from video_processing.processors import speech_opening as opening


def verify(source, destination):
    before = opening.sha256(source)
    start = time.monotonic()
    chosen, receipt = opening.prepare_opening(source, destination)
    elapsed = time.monotonic() - start
    assert opening.sha256(source) == before, "原片变化"
    decode_seconds = 0
    if chosen != source:
        start = time.monotonic()
        subprocess.run([opening.resolve_ffmpeg_cmd(), "-v", "error", "-xerror", "-i", str(chosen),
                        "-f", "null", "-"], check=True, capture_output=True, timeout=1200)
        decode_seconds = time.monotonic() - start
    return {"source": str(source), "source_sha256": before, "selected": str(chosen),
            "source_bytes": source.stat().st_size, "selected_bytes": chosen.stat().st_size,
            "elapsed_seconds": round(elapsed, 3), "decode_seconds": round(decode_seconds, 3),
            "receipt": receipt, "source_unchanged": True}


def audio_integrity(rows, marker):
    """只比较原片保留区间与副本；ASR一致性不冒充人工首字标注。"""
    import numpy as np
    import torch
    import whisper
    torch.set_num_threads(2)
    model = whisper.load_model(marker["media"]["models"]["base"]["snapshot"], device="cpu")
    results = []
    for row in rows:
        offset = row["receipt"]["offset_seconds"]
        if not offset:
            continue
        signals = []
        for path, start in [(row["source"], offset), (row["selected"], 0)]:
            raw = subprocess.run([opening.resolve_ffmpeg_cmd(), "-v", "error", "-i", path,
                                  "-ss", str(start), "-t", "15", "-vn", "-ar", "16000", "-ac", "1",
                                  "-f", "f32le", "pipe:1"], check=True, capture_output=True, timeout=60).stdout
            signals.append(np.frombuffer(raw, dtype="<f4").copy())
        words = [re.findall(r"[a-z]+", model.transcribe(signal, language="en", fp16=False,
                 temperature=0)["text"].lower()) for signal in signals]
        # 对齐误差只在±16毫秒内搜索；AAC重编码不要求波形字节相等。
        correlations = []
        for lag in range(-256, 257, 16):
            first = signals[0][256:80256:4]
            second = signals[1][256 + lag:80256 + lag:4]
            correlations.append((float(np.dot(first, second) /
                max(float(np.linalg.norm(first) * np.linalg.norm(second)), 1e-12)), lag))
        correlation, lag = max(correlations)
        results.append({"id": row["id"], "source_first_words": words[0][:5],
                        "prepared_first_words": words[1][:5], "first_words_agree": words[0][:5] == words[1][:5],
                        "waveform_correlation": round(correlation, 6), "audio_lag_ms": lag / 16})
        print("audio-integrity", results[-1], flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--full-case", default="")
    parser.add_argument("--audio-integrity", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    marker = json.loads((repo / ".test-sandbox.json").read_text())
    run_root = Path(marker["run_root"]).resolve()
    assert marker["schema"] == 1 and Path(marker["repo"]) == repo
    assert all(path.resolve().is_relative_to(run_root)
               for path in (args.cases, args.media_root, args.output_root))
    args.output_root.mkdir(parents=True, exist_ok=True)
    ffmpeg_slot._DIRECTORY = args.output_root / "ffmpeg-slot"
    rows = []
    report = args.output_root / "results.json"
    for case in json.loads(args.cases.read_text())["cases"]:
        row = verify(args.media_root / f"{case['id']}.mp4", args.output_root / case["id"])
        assert row["source_sha256"] == case["sample_sha256"], "真实样本摘要变化"
        row.update(id=case["id"], scenario=case["scenario"], expected_offset=case["expected_offset"])
        assert row["receipt"]["offset_seconds"] == case["expected_offset"], row
        assert row["receipt"]["reason"] == case["expected_reason"], row
        rows.append(row)
        report.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        print(case["id"], row["receipt"]["offset_seconds"], row["receipt"]["reason"], row["elapsed_seconds"], flush=True)
    if args.full_case:
        row = verify(args.media_root / f"{args.full_case}.full.mp4", args.output_root / "full-cost")
        (args.output_root / "full-cost.json").write_text(json.dumps(row, ensure_ascii=False, indent=2))
        print("full-cost", row["elapsed_seconds"], row["source_bytes"], row["selected_bytes"], flush=True)
    if args.audio_integrity:
        (args.output_root / "audio-integrity.json").write_text(json.dumps(audio_integrity(rows, marker), indent=2))


if __name__ == "__main__":
    main()

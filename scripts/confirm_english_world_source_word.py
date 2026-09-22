#!/usr/bin/env python3
"""对唯一转录疑点作一次无提示本地复听，保存模型、原声与逐词结果。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 已下载模型的有界原声复核，不调用 API 或修改审校预算。 |
"""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_processing.study_cards.language_qa import atomic_json, file_digest, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--word-index", type=int, required=True)
    args = parser.parse_args()
    timeline = args.timeline.resolve()
    payload = read_json(timeline)
    evidence = read_json(timeline.parent / "qa/source_evidence.json")
    source = timeline.parent / payload["source_provenance"]["source_video"]
    model = args.model.expanduser().resolve()
    if not model.is_file() or file_digest(source) != evidence["source_sha256"]:
        raise ValueError("模型缺失或来源已变化")
    model_hash = file_digest(model)
    if model_hash == evidence["model_sha256"]:
        raise ValueError("复核必须使用不同的已下载模型")
    index = args.word_index
    word = payload["words"][index]
    start = max(0, word["start"] - 2.4) + evidence["source_start"]
    end = min(evidence["source_end"], word["end"] + 2.4 + evidence["source_start"])
    report = timeline.parent / "qa/source_word_confirmation.json"
    if report.exists():
        raise ValueError("本任务已有一次复听记录，不覆盖、不重复猜测")
    # 启动前占位：中断也保留一次执行事实。
    binding = {"version": 1, "engine": "whisper-local-unprompted", "state": "STARTED",
               "model_sha256": model_hash, "source_sha256": evidence["source_sha256"],
               "timeline_sha256": file_digest(timeline), "word_index": index,
               "source_start": start, "source_end": end, "sample_rate": 16000, "channels": 1}
    atomic_json(report, binding)
    import imageio_ffmpeg
    import torch
    import whisper
    torch.set_num_threads(4)
    audio = report.with_suffix(".wav")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-ss", str(start),
                    "-i", str(source), "-t", str(end - start), "-vn", "-ar", "16000",
                    "-ac", "1", str(audio)], check=True)
    result = whisper.load_model(str(model), device="cpu").transcribe(
        str(audio), language="en", word_timestamps=True, fp16=False, temperature=0,
        condition_on_previous_text=False)
    if file_digest(source) != binding["source_sha256"] or file_digest(timeline) != binding["timeline_sha256"]:
        raise ValueError("复听期间输入变化")
    binding.update(state="COMPLETE", audio_sha256=file_digest(audio), text=result["text"],
                   words=[w for s in result["segments"] for w in s.get("words", [])])
    atomic_json(report, binding)
    print(binding["text"])


if __name__ == "__main__":
    main()

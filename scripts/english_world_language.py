#!/usr/bin/env python3
"""英语世界来源证据、展示冻结与独立 AGY 审校入口。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | source/prepare/review/validate 阶段独立执行，不接触投稿账本。 |
| 1.0.1 | 2026-09-09 | Codex | 以来源+字幕+自然片段隔离布局和审校预算。 |
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_processing.study_cards.language_qa import (
    VERSION, atomic_json, digest, file_digest, read_json, task_identity, validate_language_qa,
)
from video_processing.study_cards.caption_evidence import parse_json3, transcript_differences, align_json3


def source_evidence(timeline, model_path):
    import imageio_ffmpeg
    import whisper
    root = timeline.parent
    payload = read_json(timeline)
    p = payload["source_provenance"]
    source = Path(p.get("source_video", root / "source/source.mp4"))
    if not source.is_absolute():
        source = root / source
    caption = root / p["caption_artifact"]
    start, end = p["source_start_seconds"], p["source_end_seconds"]
    parsed = parse_json3(read_json(caption), start, end)
    if not model_path.is_file():
        raise ValueError("Whisper 模型必须是已下载的本地文件；不自动下载")
    binding = {"source_sha256": file_digest(source), "caption_sha256": file_digest(caption),
               "model_sha256": file_digest(model_path), "source_start": start, "source_end": end}
    cached_path = root / "qa/source_evidence.json"
    if cached_path.exists():
        old = read_json(cached_path)
        if all(old.get(k) == v for k, v in binding.items()):
            old["timeline_differences"] = transcript_differences(payload["english_text"], old["asr_text"])
            atomic_json(cached_path, old)
            return
    with tempfile.TemporaryDirectory(prefix="english_source_asr_") as d:
        audio = Path(d) / "source.wav"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-ss", str(start),
                        "-i", str(source), "-t", str(end - start), "-vn", "-ar", "16000", "-ac", "1",
                        str(audio)], check=True, capture_output=True)
        result = whisper.load_model(str(model_path)).transcribe(str(audio), language="en", word_timestamps=True, fp16=False)
    if file_digest(source) != binding["source_sha256"] or file_digest(caption) != binding["caption_sha256"]:
        raise ValueError("转写期间来源改变")
    words = [w for segment in result["segments"] for w in segment.get("words", [])]
    evidence = {"version": VERSION, **binding, "parsed": parsed, "asr_text": result["text"],
                "asr_words": words, "sample_rate": 16000, "channels": 1,
                "caption_differences": transcript_differences(parsed["english_text"], result["text"]),
                "timeline_differences": transcript_differences(payload["english_text"], result["text"])}
    if parsed["requires_alignment"]:
        try:
            evidence["aligned_words"] = align_json3(parsed, words)
            evidence["alignment_status"] = "PASS"
        except ValueError as exc:
            evidence["alignment_status"] = "UNCERTAIN"
            evidence["alignment_error"] = str(exc)
    atomic_json(cached_path, evidence)


def prepare(timeline, wordlist_dir=None):
    from video_processing.study_cards.display_plan import build_plan
    from video_processing.study_cards.timeline_guard import validate_source_caption_boundary
    payload = read_json(timeline)
    if payload.get("language_contract") != VERSION:
        raise ValueError(f"新输入必须声明 language_contract={VERSION}")
    validate_source_caption_boundary(payload, timeline_path=timeline)
    evidence = read_json(timeline.parent / "qa/source_evidence.json")
    if evidence.get("sample_rate") != 16000 or evidence.get("channels") != 1 or not evidence.get("asr_words"):
        raise ValueError("缺少完整片段 ASR 证据")
    if evidence.get("parsed", {}).get("requires_alignment"):
        if evidence.get("alignment_status") != "PASS" or payload["words"] != evidence.get("aligned_words"):
            raise ValueError("多词字幕必须以核对后的真实 ASR 锚点生成时间线；当前不确定")
    p = payload["source_provenance"]
    source = Path(p.get("source_video", "source/source.mp4"))
    source = source if source.is_absolute() else timeline.parent / source
    if (file_digest(source) != evidence.get("source_sha256")
            or file_digest(timeline.parent / p["caption_artifact"]) != evidence.get("caption_sha256")
            or p["source_start_seconds"] != evidence.get("source_start")
            or p["source_end_seconds"] != evidence.get("source_end")):
        raise ValueError("来源证据过期，必须重新执行 source")
    if evidence.get("timeline_differences") != transcript_differences(payload["english_text"], evidence["asr_text"]):
        raise ValueError("原文已修改，必须重新绑定 ASR 差异")
    from copy import deepcopy
    from video_processing.study_cards.learning_dictionary import attach_evidence
    verified = attach_evidence(deepcopy(payload), wordlist_dir or Path.home() / "Downloads/hermes-wordlists")
    if (verified["learning_points"] != payload["learning_points"]
            or verified["dictionary_sha256"] != payload.get("dictionary_sha256")):
        raise ValueError("词典证据缺失或过期，必须重新执行 lexicon")
    changes = read_json(timeline.parent / "editorial_changes.json")
    if changes.get("version") != VERSION or changes.get("revision") not in (0, 1):
        raise ValueError("编辑证据版本或修订次数非法")
    for change in changes.get("changes", []):
        if any(not change.get(k) for k in ("kind", "before", "after", "evidence")):
            raise ValueError("编辑修改必须有前后文本和来源依据")
    from video_processing.study_cards.language_review_service import locked
    layout_ledger = ROOT / "output/english_world_language/tasks" / task_identity(evidence) / "layout_attempts.json"
    with locked(layout_ledger.with_suffix(".lock")):
        state = read_json(layout_ledger) if layout_ledger.exists() else {"failed_layouts": []}
        if state.get("terminal"):
            raise ValueError("一次重新分屏后仍未通过，本任务停止")
        try:
            plan = build_plan(payload, file_digest(timeline))
        except ValueError as exc:
            if "个学习点，要求" in str(exc):
                key = digest({"paragraphs": payload["paragraphs"], "points": payload["learning_points"]})
                if key not in state["failed_layouts"]:
                    state["failed_layouts"].append(key)
                state["terminal"] = len(state["failed_layouts"]) >= 2
                atomic_json(layout_ledger, state)
            raise
    atomic_json(timeline.parent / "display_plan.json", plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("source", "lexicon", "prepare", "review", "publication", "validate"))
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--publication-file", type=Path)
    parser.add_argument("--whisper-model", type=Path, default=Path.home() / ".cache/whisper/small.pt")
    parser.add_argument("--wordlist-dir", type=Path, default=Path.home() / "Downloads/hermes-wordlists")
    args = parser.parse_args()
    timeline = args.timeline.resolve()
    try:
        if args.stage == "source":
            source_evidence(timeline, args.whisper_model.expanduser())
        elif args.stage == "lexicon":
            from video_processing.study_cards.learning_dictionary import attach_evidence
            atomic_json(timeline, attach_evidence(read_json(timeline), args.wordlist_dir.expanduser()))
        elif args.stage == "prepare":
            prepare(timeline, args.wordlist_dir.expanduser())
        elif args.stage in ("review", "publication"):
            from config.settings import settings
            from video_processing.study_cards.language_review_service import review
            if args.stage == "review":
                prepare(timeline, args.wordlist_dir.expanduser())  # 本地检查失败时不消耗模型额度
            evidence = read_json(timeline.parent / "qa/source_evidence.json")
            task_key = task_identity(evidence)
            kwargs = {}
            if args.stage == "publication":
                from video_processing.study_cards.publication_qa import review_publication
                if not args.publication_file:
                    raise ValueError("publication 阶段需要 --publication-file")
                review = review_publication
                kwargs["publication"] = read_json(args.publication_file)
            report = review(timeline, **kwargs, cache_dir=ROOT / "output/english_world_language/cache",
                            task_dir=ROOT / "output/english_world_language/tasks" / task_key,
                            model=settings.english_world_language_model, command=settings.agy_command,
                            timeout=settings.english_world_language_timeout_seconds)
            print(f"language QA: {report['state']}; cache_hit={report['cache_hit']}; attempts={report['attempts']}")
            return 0 if report["state"] == "PASS" else 2
        else:
            from video_processing.study_cards.language_qa import validate_display
            print(validate_display(timeline, args.manifest))
        return 0
    except Exception as exc:
        # 保留失败收据；绝不覆盖已有语言 PASS 来掩盖内容改变，验证器仍核对绑定。
        atomic_json(timeline.parent / "qa/language_execution_error.json",
                    {"stage": args.stage, "state": "FAIL", "error_type": type(exc).__name__, "message": str(exc)})
        print(f"english_world_language: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

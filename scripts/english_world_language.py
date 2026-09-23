#!/usr/bin/env python3
"""英语世界来源证据、展示冻结与独立 AGY 审校入口。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.8 | 2026-09-23 | Codex | 保存一次 medium 复核及原始证据，跨目录复用已通过模型，区分内容失败与运行失败回执。 |
| 1.0.7 | 2026-09-23 | Antigravity | Whisper ASR 原始证据先落盘至 source_asr_raw.json 再校验修复。 |
| 1.0.6 | 2026-09-22 | Codex | 提供显式启动故障恢复理由入口，不清除次数或绕过语言检查。 |
| 1.0.0 | 2026-09-09 | Codex | source/prepare/review/validate 阶段独立执行，不接触投稿账本。 |
| 1.0.1 | 2026-09-09 | Codex | 以来源+字幕+自然片段隔离布局和审校预算。 |
| 1.0.2 | 2026-09-09 | Codex | 保存边界跨越字幕的 ASR 对齐文本，禁止静默丢词。 |
| 1.0.3 | 2026-09-09 | Codex | 将 JSON3/ASR 对齐器版本纳入来源证据缓存绑定。 |
| 1.0.4 | 2026-09-09 | Codex | 保存零宽 Whisper 词时间的确定性修复依据，不接受未锚定时间线。 |
| 1.0.5 | 2026-09-11 | Codex | 留存有限文本归一化审计，不把同值数字和连字符拆分当作实义差异。 |
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_processing.study_cards.language_qa import (
    VERSION, atomic_json, digest, file_digest, read_json, task_identity, validate_language_qa,
)
from video_processing.study_cards.caption_evidence import (
    PARSER_VERSION, align_json3, parse_json3, repair_asr_word_timestamps, transcript_differences,
    transcript_normalizations,
)


def _is_placeholder(payload):
    p = payload["source_provenance"]
    return (p.get("caption_format") == "local_whisper_bootstrap"
            and Path(p["caption_artifact"]).name == "local_whisper_placeholder.json3"
            and p["source_start_seconds"] == 0)


def _raw_evidence(payload, raw, parsed, *, bootstrap=False):
    from video_processing.study_cards.asr_window import validate_window
    raw_words = raw["raw_words"]
    if bootstrap:
        words, repairs, window = validate_window(raw_words, raw["source_end"])
        text = " ".join(str(w.get("word") or w.get("text") or "").strip() for w in words)
    else:
        words, repairs = repair_asr_word_timestamps(raw_words, raw["source_end"] - raw["source_start"])
        text, window = raw["asr_text"], None
    evidence = {k: v for k, v in raw.items() if k not in ("raw_words", "asr_text")}
    evidence.update(parsed=parsed, asr_text=text, asr_words_raw=raw_words,
                    asr_words=words, asr_timing_repairs=repairs,
                    caption_differences=transcript_differences(parsed["english_text"], text),
                    caption_normalizations=transcript_normalizations(parsed["english_text"], text),
                    timeline_differences=transcript_differences(payload["english_text"], text),
                    timeline_normalizations=transcript_normalizations(payload["english_text"], text))
    if window:
        evidence["bootstrap_window"] = window
        evidence["asr_context_text"] = raw["asr_text"]
    if parsed["requires_alignment"]:
        try:
            evidence["aligned_words"] = align_json3(parsed, words)
            evidence["alignment_status"] = "PASS"
            evidence["aligned_caption_text"] = " ".join(w["text"] for w in evidence["aligned_words"])
            evidence["caption_boundary_trim"] = transcript_differences(parsed["english_text"], evidence["aligned_caption_text"])
        except ValueError as exc:
            evidence.update(alignment_status="UNCERTAIN", alignment_error=str(exc))
    return evidence


def bind_bootstrap_evidence(timeline, *, parent=None):
    """从保留的完整 ASR 重新计算固定窗口，绑定派生 JSON3；后续缓存也重新验证。"""
    root = timeline.parent
    payload = read_json(timeline)
    p = payload["source_provenance"]
    scope_path = root / "qa/bootstrap_scope.json"
    scope = parent if parent is not None else read_json(scope_path)
    raw = scope["raw"]
    source = root / p["source_video"]
    caption = root / p["caption_artifact"]
    if (file_digest(source) != raw.get("source_sha256") or raw.get("source_start") != 0
            or raw.get("caption_parser_version") != PARSER_VERSION
            or raw.get("sample_rate") != 16000 or raw.get("channels") != 1
            or file_digest(root / scope["parent_caption"]) != raw.get("caption_sha256")
            or p.get("caption_format") != "local_whisper_bootstrap"):
        raise ValueError("ASR 窗口来源绑定过期")
    parsed = parse_json3(read_json(caption), p["source_start_seconds"], p["source_end_seconds"])
    evidence = _raw_evidence(payload, raw, parsed, bootstrap=True)
    window = evidence["bootstrap_window"]
    if (p["source_start_seconds"] != 0 or p["source_end_seconds"] != window["source_end"]
            or evidence["caption_differences"]):
        raise ValueError("禁止改变已选自然句窗口或遗漏原词")
    expected = {"events": [{"tStartMs": round(w["start"] * 1000),
                            "dDurationMs": round((w["end"] - w["start"]) * 1000),
                            "segs": [{"utf8": str(w.get("word") or w.get("text") or "").strip()}]}
                           for w in evidence["asr_words"]]}
    if read_json(caption) != expected:
        raise ValueError("派生字幕未逐词保留已验证 ASR 锚点")
    if evidence.get("alignment_status") not in (None, "PASS"):
        raise ValueError("UNCERTAIN: 派生字幕无法与固定窗口对齐")
    evidence.update(source_end=window["source_end"], caption_sha256=file_digest(caption),
                    bootstrap_parent_binding={k: raw[k] for k in
                        ("source_sha256", "caption_sha256", "source_start", "source_end", "model_sha256")})
    if parent is not None:
        atomic_json(scope_path, scope)
    atomic_json(root / "qa/source_evidence.json", evidence)
    atomic_json(root / "qa/source_asr_raw.json", raw)
    return evidence


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
               "model_sha256": file_digest(model_path), "caption_parser_version": PARSER_VERSION,
               "source_start": start, "source_end": end}
    cached_path = root / "qa/source_evidence.json"
    raw_path = root / "qa/source_asr_raw.json"
    if cached_path.exists():
        old = read_json(cached_path)
        if (all(old.get(k) == v for k, v in binding.items())
                and (not _is_placeholder(payload) or old.get("bootstrap_window"))):
            old["timeline_differences"] = transcript_differences(payload["english_text"], old["asr_text"])
            atomic_json(cached_path, old)
            if "asr_words_raw" in old:
                atomic_json(raw_path, {
                    "version": VERSION, **binding, "asr_text": old.get("asr_context_text", old.get("asr_text", "")),
                    "raw_words": old.get("asr_words_raw", []), "sample_rate": 16000, "channels": 1,
                })
            return
    with tempfile.TemporaryDirectory(prefix="english_source_asr_") as d:
        audio = Path(d) / "source.wav"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-ss", str(start),
                        "-i", str(source), "-t", str(end - start), "-vn", "-ar", "16000", "-ac", "1",
                        str(audio)], check=True, capture_output=True)
        result = whisper.load_model(str(model_path)).transcribe(str(audio), language="en", word_timestamps=True, fp16=False)
    if file_digest(source) != binding["source_sha256"] or file_digest(caption) != binding["caption_sha256"]:
        raise ValueError("转写期间来源改变")
    raw_words = [w for segment in result["segments"] for w in segment.get("words", [])]
    atomic_json(raw_path, {
        "version": VERSION, **binding, "asr_text": result.get("text", ""),
        "raw_words": raw_words, "sample_rate": 16000, "channels": 1,
    })
    evidence = _raw_evidence(payload, read_json(raw_path), parsed, bootstrap=_is_placeholder(payload))
    atomic_json(cached_path, evidence)


def source_evidence_with_recheck(timeline, small_model, medium_model, task_root):
    """small 的时间/对齐不确定时，保留原始证据，对同源片段最多做一次本地 medium 复核。"""
    from video_processing.study_cards.language_review_service import locked
    root = timeline.parent
    payload = read_json(timeline)
    p = payload["source_provenance"]
    if (root / "qa/bootstrap_scope.json").exists():
        raw = read_json(root / "qa/bootstrap_scope.json")["raw"]
        if not any(model.is_file() and raw.get("model_sha256") == file_digest(model)
                   for model in (small_model, medium_model)):
            raise ValueError("ASR 窗口模型证据过期")
        bind_bootstrap_evidence(timeline)
        return
    source = Path(p.get("source_video", "source/source.mp4"))
    source = source if source.is_absolute() else root / source
    binding = {"source_sha256": file_digest(source), "caption_sha256": file_digest(root / p["caption_artifact"]),
               "source_start": p["source_start_seconds"], "source_end": p["source_end_seconds"],
               "caption_parser_version": PARSER_VERSION}
    task_dir = Path(task_root) / task_identity(binding)
    receipt_path = task_dir / "source_recheck.json"
    evidence_path, raw_path = root / "qa/source_evidence.json", root / "qa/source_asr_raw.json"

    def bound(value, model):
        return (all(value.get(k) == v for k, v in binding.items())
                and model.is_file() and value.get("model_sha256") == file_digest(model))

    def require_alignment():
        evidence = read_json(evidence_path)
        if (evidence.get("alignment_status") not in (None, "PASS") or not evidence.get("asr_words")
                or evidence.get("sample_rate") != 16000 or evidence.get("channels") != 1):
            raise ValueError("UNCERTAIN: 来源字幕/ASR 对齐不确定")
        return evidence

    with locked(task_dir / "source_recheck.lock"):
        bootstrap_path = task_dir / "bootstrap_source.json"
        if _is_placeholder(payload) and bootstrap_path.exists():
            frozen = read_json(bootstrap_path)
            raw = frozen["raw"]
            if not any(bound(raw, model) for model in (small_model, medium_model)):
                raise ValueError("已冻结自然句窗口来源过期；禁止重新转写换区间")
            evidence = _raw_evidence(payload, raw,
                parse_json3(read_json(root / p["caption_artifact"]), binding["source_start"], binding["source_end"]),
                bootstrap=True)
            if evidence["bootstrap_window"] != frozen["window"]:
                raise ValueError("已冻结自然句窗口发生变化")
            atomic_json(evidence_path, evidence)
            atomic_json(raw_path, raw)
            require_alignment()
            return

        def freeze_bootstrap(evidence, raw):
            if _is_placeholder(payload):
                atomic_json(bootstrap_path, {"raw": raw, "window": evidence["bootstrap_window"]})

        if receipt_path.exists():
            receipt = read_json(receipt_path)
            evidence, raw = receipt.get("medium_evidence", {}), receipt.get("medium_raw", {})
            if _is_placeholder(payload) and receipt.get("status") in ("PASS", "FAIL") and bound(raw, medium_model):
                # 历史全段 FAIL 保持原样；仅用同一 medium 原始证据复算固定窗口。
                evidence = _raw_evidence(payload, raw,
                    parse_json3(read_json(root / p["caption_artifact"]), binding["source_start"], binding["source_end"]),
                    bootstrap=True)
                atomic_json(evidence_path, evidence)
                atomic_json(raw_path, raw)
                require_alignment()
                atomic_json(task_dir / "bootstrap_scope_recheck.json", {
                    "original_receipt_sha256": file_digest(receipt_path), "raw_sha256": digest(raw),
                    "window": evidence["bootstrap_window"], "status": "PASS", "additional_model_calls": 0})
                freeze_bootstrap(evidence, raw)
                return
            if (receipt.get("status") != "PASS" or not bound(evidence, medium_model)
                    or not bound(raw, medium_model)):
                raise ValueError("来源 medium 复核已尝试或证据过期；禁止换目录重复复核")
            # 后续 source/prepare/review 继续使用通过的模型，保留 small 失败记录。
            evidence["timeline_differences"] = transcript_differences(payload["english_text"], evidence["asr_text"])
            evidence["timeline_normalizations"] = transcript_normalizations(payload["english_text"], evidence["asr_text"])
            atomic_json(evidence_path, evidence)
            atomic_json(raw_path, raw)
            require_alignment()
            return
        try:
            source_evidence(timeline, small_model)
            evidence = require_alignment()
            if _is_placeholder(payload):
                freeze_bootstrap(evidence, read_json(raw_path))
            return
        except ValueError as exc:
            if not str(exc).startswith("UNCERTAIN:"):
                raise
            small_error = str(exc)
        # 没有绑定当前来源的原始 ASR 时，不把其他错误误判为可复核的对齐问题。
        small_raw = read_json(raw_path)
        if not bound(small_raw, small_model):
            raise ValueError("small 失败缺少绑定当前来源的原始 ASR")
        if not medium_model.is_file():
            raise ValueError("UNCERTAIN: medium 模型未下载，保留 small 原始证据并停止")
        if file_digest(medium_model) == file_digest(small_model):
            raise ValueError("medium 复核必须使用不同的本地模型")
        receipt = {"version": VERSION, "binding": binding, "status": "STARTED", "attempts": 1,
                   "small_error": small_error, "small_raw": small_raw}
        if evidence_path.exists():
            failed_evidence = read_json(evidence_path)
            if bound(failed_evidence, small_model):
                receipt["small_evidence"] = failed_evidence
        atomic_json(receipt_path, receipt)  # 崩溃也不能重新领取复核。
        try:
            source_evidence(timeline, medium_model)
            evidence, raw = require_alignment(), read_json(raw_path)
            if not bound(evidence, medium_model) or not bound(raw, medium_model):
                raise ValueError("medium 复核来源绑定发生变化")
            receipt.update(status="PASS", medium_evidence=evidence, medium_raw=raw)
        except Exception as exc:
            receipt.update(status="FAIL", medium_error=str(exc))
            if raw_path.exists():
                raw = read_json(raw_path)
                if bound(raw, medium_model):
                    receipt["medium_raw"] = raw
            atomic_json(receipt_path, receipt)
            raise
        atomic_json(receipt_path, receipt)
        freeze_bootstrap(evidence, raw)


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
    parser.add_argument("stage", choices=("source", "bootstrap-bind", "lexicon", "prepare", "review", "publication", "validate"))
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--publication-file", type=Path)
    parser.add_argument("--recover-startup-failure", metavar="REASON",
                        help="已确认本地启动故障并修复环境后，保留原预算进行一次受控恢复")
    parser.add_argument("--recover-rate-limit", metavar="REASON", help="确认额度已恢复后，动用原输入剩余第三次审校")
    parser.add_argument("--rate-limit-reset-at", type=float, help="操作员从供应商回执确认的额度恢复 Unix 时间")
    parser.add_argument("--whisper-model", type=Path, default=Path.home() / ".cache/whisper/small.pt")
    parser.add_argument("--allow-medium-recheck", action="store_true", help="small 对齐不确定时复核同源片段一次")
    parser.add_argument("--wordlist-dir", type=Path, default=Path.home() / "Downloads/hermes-wordlists")
    args = parser.parse_args()
    timeline = args.timeline.resolve()
    review_execution = {"status": "STARTED", "started_ns": time.time_ns()}
    if args.stage == "review":
        atomic_json(timeline.parent / "qa/review_execution.json", review_execution)
    try:
        if args.recover_startup_failure is not None and args.stage != "review":
            raise ValueError("启动恢复仅支持 review 阶段")
        if ((args.recover_rate_limit is not None or args.rate_limit_reset_at is not None)
                and (args.stage != "review" or args.recover_rate_limit is None
                     or args.rate_limit_reset_at is None)):
            raise ValueError("额度恢复仅支持 review，必须同时提供恢复原因和时间")
        if args.stage == "bootstrap-bind":
            caption = Path(read_json(timeline)["source_provenance"]["caption_artifact"])
            bind_bootstrap_evidence(timeline, parent={
                "raw": read_json(timeline.parent / "qa/source_asr_raw.json"),
                "parent_caption": str(caption.with_name("local_whisper_placeholder.json3")),
            })
        elif args.stage == "source":
            if args.allow_medium_recheck:
                source_evidence_with_recheck(timeline, args.whisper_model.expanduser(),
                                            Path.home() / ".cache/whisper/medium.pt",
                                            ROOT / "output/english_world_language/tasks")
            else:
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
            if args.recover_startup_failure is not None:
                kwargs["recover_startup_reason"] = args.recover_startup_failure
            if args.recover_rate_limit is not None:
                kwargs["recover_rate_limit"] = {"reason": args.recover_rate_limit,
                                                "not_before": args.rate_limit_reset_at}
            if args.stage == "publication":
                from video_processing.study_cards.publication_qa import review_publication
                if not args.publication_file:
                    raise ValueError("publication 阶段需要 --publication-file")
                review = review_publication
                kwargs["publication"] = read_json(args.publication_file)
            report = review(timeline, **kwargs, cache_dir=ROOT / "output/english_world_language/cache",
                            task_dir=ROOT / "output/english_world_language/tasks" / task_key,
                            model=settings.english_world_language_model, command=settings.agy_command,
                            timeout=settings.english_world_language_timeout_seconds,
                            effort=settings.english_world_language_effort)
            if args.stage == "review":
                atomic_json(timeline.parent / "qa/review_execution.json",
                            {**review_execution, "status": "COMPLETED", "report_sha256": digest(read_json(timeline.parent / "qa/language_qa.json"))})
            print(f"language QA: {report['state']}; cache_hit={report['cache_hit']}; attempts={report['attempts']}")
            return 0 if report["state"] == "PASS" else 2
        else:
            from video_processing.study_cards.language_qa import validate_display
            print(validate_display(timeline, args.manifest))
        return 0
    except Exception as exc:
        if args.stage == "review":
            atomic_json(timeline.parent / "qa/review_execution.json",
                        {**review_execution, "status": "ERROR", "error_type": type(exc).__name__})
        # 保留失败收据；绝不覆盖已有语言 PASS 来掩盖内容改变，验证器仍核对绑定。
        atomic_json(timeline.parent / "qa/language_execution_error.json",
                    {"stage": args.stage, "state": "FAIL", "error_type": type(exc).__name__, "message": str(exc)})
        print(f"english_world_language: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

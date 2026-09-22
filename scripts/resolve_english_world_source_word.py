#!/usr/bin/env python3
"""唯一 P2 原声疑点的有界恢复；保留原报告、调用预算和所有发布门禁。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-22 | Codex | 原始快照与准备回执先落盘；逐文件中断可续跑，未知改动拒绝覆盖。 |
| 1.0.0 | 2026-09-22 | Codex | 双本地模型证据恢复单词，原始资料不覆盖。 |
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from video_processing.study_cards.language_protocol import (
    atomic_json, digest, file_digest, read_json, task_identity,
)
from video_processing.study_cards.language_review_service import locked
from video_processing.study_cards.display_plan import build_plan, verify_plan
from video_processing.study_cards.source_resolution import (
    RESOLUTION_VERSION, check_resolution, corrected_payload, validate_resolution,
)
from video_processing.study_cards.timeline_guard import validate_source_caption_boundary


def _preserve_file(source, target, expected, *, canonical=False):
    """原始字节先原子归档；已有快照只核验，不能用当前文件覆盖它。"""
    def fingerprint(path):
        return digest(read_json(path)) if canonical else file_digest(path)
    if target.exists():
        if fingerprint(target) != expected:
            raise ValueError(f"原始快照已变化: {target.name}")
        return
    fd, name = tempfile.mkstemp(prefix=target.name, suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        if fingerprint(Path(name)) != expected:
            raise ValueError(f"归档期间原始输入已变化: {source.name}")
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def _stage_json_once(path, value):
    """准备产物不可变；中断后仅补齐缺失文件，不重新解释旧证据。"""
    if path.exists():
        if digest(read_json(path)) != digest(value):
            raise ValueError(f"原声恢复准备记录已变化: {path.name}")
    else:
        atomic_json(path, value)


def resolve(timeline, *, word_index, task_dir, cache_dir):
    root = timeline.parent
    receipt_path = root / "qa/source_resolution.json"
    with locked(task_dir / "language.lock"):
        if receipt_path.exists():
            return validate_resolution(timeline)
        archive = root / "qa/source_resolution"
        original_timeline = archive / "timeline.before.json"
        original_plan = archive / "display_plan.before.json"
        before_path = original_timeline if original_timeline.exists() else timeline
        plan_path = original_plan if original_plan.exists() else root / "display_plan.json"
        before = read_json(before_path)
        plan = read_json(plan_path)
        report = read_json(root / "qa/language_qa.json")
        evidence = read_json(root / "qa/source_evidence.json")
        if file_digest(before_path) != report["timeline_sha256"]:
            raise ValueError("原时间线不再匹配独立审校")
        ledger = task_dir / "language_attempts.json"
        state = read_json(ledger)
        cache = cache_dir / (report["input_key"] + ".json")
        if (state.get("inflight") or not state["keys"] or state["keys"][-1] != report["input_key"]
                or read_json(cache)["result"] != report["result"]):
            raise ValueError("必须使用最新已完成的实际审校缓存，不得重放旧结果")
        verify_plan(before, plan, report["timeline_sha256"])
        after = corrected_payload(before, word_index, "and")
        confirmation = read_json(root / "qa/source_word_confirmation.json")
        target = check_resolution(before, after, plan, report, evidence,
                                  read_json(root / "editorial_changes.json"),
                                  confirmation, index=word_index)
        provenance = before["source_provenance"]
        if (file_digest(root / provenance["source_video"]) != evidence["source_sha256"]
                or file_digest(root / provenance["caption_artifact"]) != evidence["caption_sha256"]
                or provenance["source_start_seconds"] != evidence["source_start"]
                or provenance["source_end_seconds"] != evidence["source_end"]
                or file_digest(root / "qa/source_word_confirmation.wav") != confirmation["audio_sha256"]):
            raise ValueError("原声恢复来源或复听音频绑定失效")
        validate_source_caption_boundary(after, timeline_path=timeline)
        archive.mkdir(parents=True, exist_ok=True)
        _preserve_file(timeline, original_timeline, report["timeline_sha256"])
        _preserve_file(root / "display_plan.json", original_plan, report["plan_sha256"], canonical=True)
        # 原报告和来源证据保持原样，新增裁决单独绑定前后差异。
        names = ["qa/language_qa.json", "qa/source_evidence.json", "editorial_changes.json",
                 "qa/source_word_confirmation.json", "qa/source_word_confirmation.wav",
                 "qa/source_resolution/timeline.before.json", "qa/source_resolution/display_plan.before.json"]
        bindings = {name: file_digest(root / name) for name in names}
        staged = archive / "timeline.after.json"
        _stage_json_once(staged, after)
        new_plan = build_plan(after, file_digest(staged))
        _stage_json_once(archive / "display_plan.after.json", new_plan)
        receipt = {"version": RESOLUTION_VERSION, "state": "SOURCE_RESOLVED", "word_index": word_index,
                   "target": target, "before": "at", "after": "and", "bindings": bindings,
                   "timeline_sha256": file_digest(staged), "plan_sha256": digest(new_plan),
                   "ledger_path": str(ledger.resolve()), "ledger_sha256": file_digest(ledger),
                   "cache_path": str(cache.resolve()), "cache_sha256": file_digest(cache),
                   "original_review_state": report["state"], "preserved_attempts": state["attempts"],
                   "new_agy_calls": 0, "human_intervention_required": False}
        _stage_json_once(archive / "prepared_receipt.json", {"state": "PREPARED", "receipt": receipt})
        # 只接受已验证的修订前/后状态；不能把其他会话的修改当作中断恢复覆盖。
        if (file_digest(timeline) not in {report["timeline_sha256"], receipt["timeline_sha256"]}
                or digest(read_json(root / "display_plan.json")) not in {report["plan_sha256"], receipt["plan_sha256"]}):
            raise ValueError("原声恢复当前文件含未知改动，拒绝覆盖")
        atomic_json(timeline, after)
        atomic_json(root / "display_plan.json", new_plan)
        atomic_json(receipt_path, receipt)
        return validate_resolution(timeline)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--word-index", type=int, required=True)
    args = parser.parse_args()
    timeline = args.timeline.resolve()
    task = task_identity(read_json(timeline.parent / "qa/source_evidence.json"))
    result = resolve(timeline, word_index=args.word_index,
                     task_dir=ROOT / "output/english_world_language/tasks" / task,
                     cache_dir=ROOT / "output/english_world_language/cache")
    print(result["state"])


if __name__ == "__main__":
    main()

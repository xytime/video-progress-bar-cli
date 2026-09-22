#!/usr/bin/env python3
"""唯一 P2 原声疑点的有界恢复；保留原报告、调用预算和所有发布门禁。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 双本地模型证据恢复单词，原始资料不覆盖。 |
"""
import argparse
from pathlib import Path
import shutil
import sys

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


def resolve(timeline, *, word_index, task_dir, cache_dir):
    root = timeline.parent
    receipt_path = root / "qa/source_resolution.json"
    with locked(task_dir / "language.lock"):
        if receipt_path.exists():
            return validate_resolution(timeline)
        before = read_json(timeline)
        plan = read_json(root / "display_plan.json")
        report = read_json(root / "qa/language_qa.json")
        evidence = read_json(root / "qa/source_evidence.json")
        if file_digest(timeline) != report["timeline_sha256"]:
            raise ValueError("原时间线不再匹配独立审校")
        ledger = task_dir / "language_attempts.json"
        state = read_json(ledger)
        cache = cache_dir / (report["input_key"] + ".json")
        if (state.get("inflight") or not state["keys"] or state["keys"][-1] != report["input_key"]
                or read_json(cache)["result"] != report["result"]):
            raise ValueError("必须使用最新已完成的实际审校缓存，不得重放旧结果")
        verify_plan(before, plan, file_digest(timeline))
        after = corrected_payload(before, word_index, "and")
        target = check_resolution(before, after, plan, report, evidence,
                                  read_json(root / "editorial_changes.json"),
                                  read_json(root / "qa/source_word_confirmation.json"), index=word_index)
        archive = root / "qa/source_resolution"
        archive.mkdir(exist_ok=False)
        shutil.copyfile(timeline, archive / "timeline.before.json")
        shutil.copyfile(root / "display_plan.json", archive / "display_plan.before.json")
        # 原报告和来源证据保持原样，新增裁决单独绑定前后差异。
        names = ["qa/language_qa.json", "qa/source_evidence.json", "editorial_changes.json",
                 "qa/source_word_confirmation.json", "qa/source_word_confirmation.wav",
                 "qa/source_resolution/timeline.before.json", "qa/source_resolution/display_plan.before.json"]
        bindings = {name: file_digest(root / name) for name in names}
        staged = archive / "timeline.after.json"
        atomic_json(staged, after)
        new_plan = build_plan(after, file_digest(staged))
        # 在两份候选产物均通过生成后才替换当前输入，中断仍由文件绑定阻断。
        atomic_json(timeline, after)
        atomic_json(root / "display_plan.json", new_plan)
        receipt = {"version": RESOLUTION_VERSION, "state": "SOURCE_RESOLVED", "word_index": word_index,
                   "target": target, "before": "at", "after": "and", "bindings": bindings,
                   "timeline_sha256": file_digest(timeline), "plan_sha256": digest(new_plan),
                   "ledger_path": str(ledger.resolve()), "ledger_sha256": file_digest(ledger),
                   "cache_path": str(cache.resolve()), "cache_sha256": file_digest(cache),
                   "original_review_state": report["state"], "preserved_attempts": state["attempts"],
                   "new_agy_calls": 0, "human_intervention_required": False}
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

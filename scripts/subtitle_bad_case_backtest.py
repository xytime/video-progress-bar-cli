#!/usr/bin/env python3
"""离线回放字幕 bad case 与固定反例；不调用模型，不把告警放行当成错误修复。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 固定回归/留出集、旧硬门对照、人工标注真值与可比较的周报。 |
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from video_processing.utils.subtitle_bad_cases import _safe_path, iter_bad_cases  # noqa: E402
from video_processing.utils.subtitle_translation_provider import SubtitleTranslationCandidate  # noqa: E402
from video_processing.utils.subtitle_translation_quality import evaluate_subtitle_translation_candidate  # noqa: E402

FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "subtitle_bad_case_benchmark.json"
_ACCEPTED = {"clean", "accepted_with_warnings"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _source_hashes() -> dict:
    names = ("subtitle_sparse_policy.py", "translation_quality_guard.py", "translation_fluency_guard.py",
             "translation_consistency_guard.py", "subtitle_content_contract.py", "subtitle_translation_provider.py")
    paths = [_PROJECT_ROOT / "src" / "video_processing" / "utils" / name for name in names]
    paths.append(Path(__file__))
    return {str(path.relative_to(_PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def rate(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None,
            "state": "measured" if denominator else "unknown"}


def expand_fixture(case: dict) -> dict:
    """紧凑冻结样本展开为真实整片段数/时间，不能逐批绕过门槛。"""
    recipe = case["recipe"]
    count = recipe.get("count", 100)
    segments = [{"text": recipe.get("source", "Oil demand remained steady."),
                 "start": i * 2.0, "end": (i + 1) * 2.0} for i in range(count)]
    translations = [recipe.get("translation", "石油需求保持稳定。") for _ in range(count)]
    for change in recipe.get("overrides", []):
        index = change["segment_number"] - 1
        for field in ("text", "start", "end"):
            if field in change:
                segments[index][field] = change[field]
        if "translation" in change:
            translations[index] = change["translation"]
    if recipe.get("drop_last_translation"):
        translations.pop()
    repaired = recipe.get("repaired_segments", [])
    return {"segments": segments, "translations": translations,
            "context_text": recipe.get("context_text", ""),
            "repair_history": [{"strategy": recipe.get("repair_strategy", "isolated_source_repair"),
                                "executed": True, "segment_numbers": repaired}] if repaired else []}


def _legacy_status(payload: dict) -> str:
    segments, translations = payload["segments"], payload["translations"]
    if SubtitleTranslationCandidate("backtest", translations).contract_error_for(len(segments)):
        return "invalid_structure"
    decision = evaluate_subtitle_translation_candidate(
        [row["text"] for row in segments], translations, provider="backtest", final_provider=True,
        context_text=payload.get("context_text", ""), require_amount_coverage=True)
    if decision.blocking_issues:
        return "needs_repair"
    return "accepted_with_warnings" if decision.warning_issues else "clean"


def _current_report(payload: dict) -> dict:
    from video_processing.utils.subtitle_sparse_policy import build_sparse_quality_report
    return build_sparse_quality_report(
        payload["segments"], payload["translations"], context_text=payload.get("context_text", ""),
        vocabs=payload.get("vocabs"), repair_history=payload.get("repair_history"))


def _labelled_metrics(rows: list[dict]) -> dict:
    labelled = [row for row in rows if row.get("label") and row["status"] != "unreplayable"]
    repairable = [row for row in labelled if row.get("repair_attempted") and row["label"].get("input_has_error") is True
                  and isinstance(row["label"].get("output_has_error"), bool)]
    clean = [row for row in labelled if row["label"].get("output_has_error") is False]
    wrong = [row for row in labelled if row["label"].get("output_has_error") is True]
    return {
        "labelled_cases": len(labelled),
        "unreviewed_cases": sum(not row.get("label") for row in rows),
        "unreplayable_cases": sum(row["status"] == "unreplayable" for row in rows),
        "repair_rate": rate(sum(not row["label"]["output_has_error"] for row in repairable), len(repairable)),
        "false_block_rate": rate(sum(row["status"] not in _ACCEPTED for row in clean), len(clean)),
        "incorrect_output_acceptance_rate": rate(sum(row["status"] in _ACCEPTED for row in wrong), len(wrong)),
        "warning_tolerated_incorrect_outputs": sum(row["status"] == "accepted_with_warnings" for row in wrong),
        "silent_incorrect_output_acceptance_rate": rate(sum(row["status"] == "clean" for row in wrong), len(wrong)),
        "note": "repair_rate 仅统计独立人工确认的输入/最终输出；未标注检测旗标不是真值。告警容错不计入修复。",
    }


def load_labels(path: Path | None) -> tuple[dict, str | None]:
    if path is None:
        return {}, None
    data = path.read_bytes()
    value = json.loads(data)
    if (value.get("schema_version") != "subtitle-bad-case-labels-v1"
            or value.get("source") != "human" or not value.get("reviewer")
            or not value.get("reviewed_at") or not isinstance(value.get("cases"), dict)):
        raise ValueError("bad_case_labels_require_explicit_human_provenance")
    for label in value["cases"].values():
        if not isinstance(label, dict):
            raise ValueError("bad_case_label_not_object")
        for key in ("input_has_error", "output_has_error"):
            if key in label and type(label[key]) is not bool:
                raise ValueError("bad_case_label_error_value_not_boolean")
    return value["cases"], hashlib.sha256(data).hexdigest()


def compare_reports(previous: dict, current: dict) -> dict:
    """版本比较必须使用相同冻结输入与标签；不能用换题后的百分比冒充进步。"""
    if previous.get("corpus_sha256") != current.get("corpus_sha256"):
        return {"comparable": False, "reason": "corpus_or_labels_changed"}
    deltas = {}
    for group in ("fixture_metrics", "human_label_metrics"):
        for name, value in current[group].items():
            before = previous.get(group, {}).get(name)
            if isinstance(value, dict) and isinstance(before, dict):
                if value.get("denominator") == before.get("denominator") and value.get("value") is not None and before.get("value") is not None:
                    deltas[group + "." + name] = value["value"] - before["value"]
    return {"comparable": True, "previous_policy": previous.get("policy_version"),
            "current_policy": current.get("policy_version"), "rate_deltas": deltas,
            "note": "门禁放行率变化与语义修复率分别统计；无人工样本时不推断翻译质量提升。"}


def build_report(*, fixtures: Path = FIXTURES, store: Path | None = None,
                 labels_path: Path | None = None, evaluator=None) -> dict:
    """仅回放冻结候选；可注入纯策略函数作故障测试，不执行模型或发布。"""
    fixture_bytes = fixtures.read_bytes()
    corpus = json.loads(fixture_bytes)
    if (corpus.get("schema_version") != "subtitle-bad-case-benchmark-v1"
            or not isinstance(corpus.get("cases"), list) or not corpus["cases"]
            or len({case["case_id"] for case in corpus["cases"]}) != len(corpus["cases"])):
        raise ValueError("invalid_or_duplicate_benchmark_cases")
    labels, labels_sha = load_labels(labels_path)
    evaluate = evaluator or _current_report
    fixture_rows = []
    for case in corpus["cases"]:
        payload = expand_fixture(case)
        current = evaluate(payload)
        fixture_rows.append({"case_id": case["case_id"], "split": case["split"],
                             "kind": case["kind"], "expected": case["expected_status"],
                             "status": current["status"], "baseline_status": _legacy_status(payload),
                             "policy_version": current.get("policy_version"),
                             "matched": current["status"] == case["expected_status"]})
    actual_rows = []
    if store is not None:
        for envelope in iter_bad_cases(store):
            payload = envelope["payload"]
            case_id = envelope["case_id"]
            if not isinstance(payload.get("segments"), list) or not isinstance(payload.get("translations"), list):
                actual_rows.append({"case_id": case_id, "status": "unreplayable",
                                    "reason": "missing_segments_or_translations", "label": labels.get(case_id)})
                continue
            current = evaluate(payload)
            actual_rows.append({"case_id": case_id, "status": current["status"],
                                "original_status": (payload.get("report") or {}).get("status"),
                                "summary_sha256": current.get("summary_sha256"),
                                "repair_attempted": any(event.get("executed") is True and event.get("strategy")
                                                        in {"host_vocab_sanitization", "targeted_singleton", "isolated_source_repair"}
                                                        and event.get("segment_numbers")
                                                        for event in (payload.get("repair_history") or []) if isinstance(event, dict)),
                                "label": labels.get(case_id)})
    clean = [row for row in fixture_rows if row["kind"] == "clean"]
    hard = [row for row in fixture_rows if row["expected"] in {"needs_repair", "invalid_structure"}]
    sparse = [row for row in fixture_rows if row["kind"] == "intentional_sparse_error"]
    report = {
        "schema_version": "subtitle-bad-case-backtest-v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "offline_host_policy_replay_no_model_calls", "semantic_accuracy": "unknown_without_human_labels",
        "policy_version": next((row["policy_version"] for row in fixture_rows if row["policy_version"]), None),
        "source_files_sha256": _source_hashes(),
        "corpus_sha256": digest({"fixtures": hashlib.sha256(fixture_bytes).hexdigest(),
                                 "case_ids": [row["case_id"] for row in actual_rows], "labels_sha256": labels_sha}),
        "fixture_metrics": {
            "cases": len(fixture_rows), "regression_cases": sum(row["split"] == "regression" for row in fixture_rows),
            "holdout_cases": sum(row["split"] == "holdout" for row in fixture_rows),
            "policy_agreement_rate": rate(sum(row["matched"] for row in fixture_rows), len(fixture_rows)),
            "false_block_rate": rate(sum(row["status"] not in _ACCEPTED for row in clean), len(clean)),
            "unauthorized_error_acceptance_rate": rate(sum(row["status"] in _ACCEPTED for row in hard), len(hard)),
            "intentional_sparse_warning_rate": rate(sum(row["status"] == "accepted_with_warnings" for row in sparse), len(sparse)),
            "baseline_blocked_sparse_cases": sum(row["baseline_status"] not in _ACCEPTED for row in sparse),
            "note": "冻结样本用于主机策略回放；稀疏错误告警放行不是已修复，也不是语义正确率。"},
        "human_label_metrics": _labelled_metrics(actual_rows),
        "orphan_label_ids": sorted(set(labels) - {row["case_id"] for row in actual_rows}),
        "fixture_results": fixture_rows, "stored_case_results": actual_rows,
        "state": "PASS" if all(row["matched"] for row in fixture_rows) else "FAIL",
    }
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, help="只读不可变案例库；不提供则只跑固定回归集")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--labels", type=Path, help="独立人工真值文件，不能由检测结果自动生成")
    parser.add_argument("--compare", type=Path, help="上一版 report.json；只在同一语料与标签时比较")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(fixtures=args.fixtures, store=args.store, labels_path=args.labels)
    if args.compare:
        report["comparison"] = compare_reports(json.loads(args.compare.read_text()), report)
    parent = _safe_path(args.output.parent, make_directory=True)
    output = _safe_path(parent / args.output.name)
    if output.exists():
        raise ValueError("backtest_output_must_be_new_immutable_report")
    fd, temporary_name = tempfile.mkstemp(prefix=".backtest-", suffix=".tmp", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temporary, output, follow_symlinks=False)
        except FileExistsError as exc:
            raise ValueError("backtest_output_must_be_new_immutable_report") from exc
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"state": report["state"], "report": str(args.output),
                      "fixture_metrics": report["fixture_metrics"],
                      "human_label_metrics": report["human_label_metrics"]}, ensure_ascii=False))
    return 0 if report["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

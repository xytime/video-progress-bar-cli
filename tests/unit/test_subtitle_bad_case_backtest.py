"""离线坏例回放量化必须区分策略容错、真实错误和人工修复真值。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 固定回归/留出集、未标注unknown、人工指标分母与同语料比较。 |
"""

import importlib.util
import json
from pathlib import Path

import pytest

from video_processing.utils.subtitle_bad_cases import save_bad_case


_PATH = Path(__file__).resolve().parents[2] / "scripts" / "subtitle_bad_case_backtest.py"
_SPEC = importlib.util.spec_from_file_location("subtitle_bad_case_backtest", _PATH)
backtest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backtest)


def _payload(**extra):
    return {"segments": [{"text": "Oil costs $115.", "start": 0, "end": 2}],
            "translations": ["油价为115美元。"],
            "repair_history": [{"strategy": "isolated_source_repair", "executed": True,
                                "segment_numbers": [1]}], **extra}


def test_actual_policy_replays_all_frozen_guard_examples():
    report = backtest.build_report()
    assert report["state"] == "PASS", [row for row in report["fixture_results"] if not row["matched"]]
    metrics = report["fixture_metrics"]
    assert metrics["cases"] >= 15 and metrics["holdout_cases"] >= 5
    assert metrics["policy_agreement_rate"]["value"] == 1
    assert metrics["false_block_rate"]["value"] == 0
    assert metrics["unauthorized_error_acceptance_rate"]["value"] == 0
    assert metrics["intentional_sparse_warning_rate"]["value"] == 1
    assert metrics["baseline_blocked_sparse_cases"] == 3
    assert report["human_label_metrics"]["repair_rate"]["value"] is None


def test_unreviewed_flags_never_count_as_semantic_ground_truth(tmp_path):
    save_bad_case(tmp_path, _payload(report={"status": "accepted_with_warnings"},
                                  detector_claim="correct after fix", repair_history=[{"executed": True}]))
    report = backtest.build_report(store=tmp_path)
    metrics = report["human_label_metrics"]
    assert metrics["unreviewed_cases"] == 1 and metrics["labelled_cases"] == 0
    for name in ("repair_rate", "false_block_rate", "incorrect_output_acceptance_rate"):
        assert metrics[name] == {"numerator": 0, "denominator": 0, "value": None, "state": "unknown"}


def test_separates_tolerated_known_error_from_fixed_translation(tmp_path):
    # 注入策略结果只为检查指标分母；真实策略另外在完整fixture中回放。
    root = tmp_path / "memory"
    fixed = save_bad_case(root, _payload(case="fixed"))
    tolerated = save_bad_case(root, _payload(case="tolerated"))
    silent = save_bad_case(root, _payload(case="silent"))
    blocked_clean = save_bad_case(root, _payload(case="blocked_clean"))
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"schema_version": "subtitle-bad-case-labels-v1", "source": "human",
        "reviewer": "unit-test-curator", "reviewed_at": "2026-10-27", "cases": {
            fixed["case_id"]: {"input_has_error": True, "output_has_error": False},
            tolerated["case_id"]: {"input_has_error": True, "output_has_error": True},
            silent["case_id"]: {"input_has_error": True, "output_has_error": True},
            blocked_clean["case_id"]: {"input_has_error": False, "output_has_error": False}}}))
    def evaluator(payload):
        value = {"fixed": "clean", "tolerated": "accepted_with_warnings", "silent": "clean",
                 "blocked_clean": "needs_repair"}.get(payload.get("case"), "clean")
        return {"status": value, "policy_version": "test"}
    report = backtest.build_report(store=root, labels_path=labels, evaluator=evaluator)
    metrics = report["human_label_metrics"]
    assert metrics["repair_rate"]["value"] == pytest.approx(1 / 3)
    assert metrics["false_block_rate"]["value"] == .5
    assert metrics["incorrect_output_acceptance_rate"]["value"] == 1
    assert metrics["silent_incorrect_output_acceptance_rate"]["value"] == .5
    assert metrics["warning_tolerated_incorrect_outputs"] == 1


def test_incompatible_corpus_cannot_prove_improvement():
    before = backtest.build_report()
    after = dict(before, corpus_sha256="new-cases-or-labels")
    assert backtest.compare_reports(before, after) == {"comparable": False, "reason": "corpus_or_labels_changed"}
    comparison = backtest.compare_reports(before, before)
    assert comparison["comparable"]
    assert all(value == 0 for value in comparison["rate_deltas"].values())


def test_fixture_gate_regression_is_reported_not_hidden():
    report = backtest.build_report(evaluator=lambda payload: {"status": "clean", "policy_version": "broken"})
    assert report["state"] == "FAIL"
    assert report["fixture_metrics"]["unauthorized_error_acceptance_rate"]["value"] == 1


def test_labels_require_explicit_human_provenance(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"schema_version": "subtitle-bad-case-labels-v1", "source": "detector",
                              "reviewer": "model", "reviewed_at": "2026-10-27", "cases": {}}))
    with pytest.raises(ValueError, match="human_provenance"):
        backtest.load_labels(path)


def test_missing_replay_inputs_reported_with_unknown_semantics(tmp_path):
    save_bad_case(tmp_path, {"legacy_issue_only": {"code": "NUMBER_MAGNITUDE_MISMATCH"}})
    report = backtest.build_report(store=tmp_path)
    assert report["stored_case_results"][0]["status"] == "unreplayable"
    assert report["human_label_metrics"]["repair_rate"]["state"] == "unknown"


def test_command_writes_new_report_and_refuses_overwrite(tmp_path):
    output = tmp_path / "reports" / "week.json"
    assert backtest.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["state"] == "PASS"
    previous = output.read_bytes()
    with pytest.raises(ValueError, match="new_immutable_report"):
        backtest.main(["--output", str(output)])
    assert output.read_bytes() == previous

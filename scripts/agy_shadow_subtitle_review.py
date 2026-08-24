#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AGY 字幕影子评估：读取已渲染 ASS，比对候选但绝不修改生产结果。

本工具不读取或更新 PipelineDB，不调用上传器，不改动成片、字幕、文案、队列和
任何平台状态。每个报告仅保存哈希、数量与质量问题码；字幕正文和 prompt 不落盘。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-08-24 | Codex | 递归发现 output 下的已渲染 ASS，避免漏掉 original_video 子目录。 |
| 1.0.0 | 2026-08-24 | Codex | 新增三天 AGY 字幕影子评估与可累积的无正文比较报告。 |
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _PROJECT_ROOT / "src"
for _path in (_PROJECT_ROOT, _SRC_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from config.settings import settings  # noqa: E402
from scripts.translation_ab_review import build_quality_context, default_info_path, load_ass_pairs, load_metadata  # noqa: E402
from video_processing.processors.caption_processor import AutoCaptionProcessor  # noqa: E402
from video_processing.utils.translation_context import build_translation_context  # noqa: E402
from video_processing.utils.translation_quality_evaluator import TranslationQualityDecision, evaluate_translation_candidate  # noqa: E402


_ROLL_OUT_HOURS = 72


def _sha256_texts(values: Sequence[str]) -> str:
    payload = json.dumps(list(values), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("时间必须带 UTC 时区，例如 2026-08-24T06:00:00Z")
    return parsed.astimezone(timezone.utc)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_json(path: Path) -> Dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _decision_summary(decision: TranslationQualityDecision) -> Dict[str, Any]:
    warnings = [issue.code for issue in decision.warning_issues]
    blocking = [issue.code for issue in decision.blocking_issues]
    return {
        "status": decision.status,
        "accepted": decision.accepted,
        "warning_count": len(warnings),
        "blocking_count": len(blocking),
        "warning_codes": sorted(warnings),
        "blocking_codes": sorted(blocking),
        "quality_penalty": len(warnings) * 8 + len(blocking) * 30,
    }


def _comparison_signal(baseline: Dict[str, Any], shadow: Dict[str, Any]) -> str:
    if shadow["blocking_count"]:
        return "SHADOW_BLOCKED"
    if baseline["blocking_count"] and not shadow["blocking_count"]:
        return "SHADOW_LOWER_PENALTY"
    if shadow["quality_penalty"] < baseline["quality_penalty"]:
        return "SHADOW_LOWER_PENALTY"
    if shadow["quality_penalty"] > baseline["quality_penalty"]:
        return "SHADOW_HIGHER_PENALTY"
    return "SHADOW_EQUIVALENT_SIGNAL"


def _run_agy_candidate(source_texts: Sequence[str], prompt_context: str) -> List[str]:
    """复用生产 AGY provider 的结构、ID 与 vocabulary 约束，但不应用它的结果。"""
    processor = AutoCaptionProcessor.__new__(AutoCaptionProcessor)
    processor._last_provider_error = ""
    candidate = processor._build_agy_candidate(list(source_texts), prompt_context)
    if candidate is None or not candidate.is_usable_for(len(source_texts)):
        raise RuntimeError("AGY_SHADOW_CANDIDATE_UNUSABLE")
    return [str(value) for value in candidate.translations]


def _review_ass(
    ass_path: Path,
    *,
    max_segments: int,
    candidate_runner: Callable[[Sequence[str], str], List[str]] = _run_agy_candidate,
) -> Dict[str, Any]:
    """对一个已成片的 ASS 生成无正文影子比较记录。"""
    pairs = load_ass_pairs(ass_path)
    eligible_pairs = [pair for pair in pairs if str(pair.get("source") or "").strip()]
    selected_pairs = eligible_pairs[:max(1, max_segments)]
    source_texts = [str(pair["source"]) for pair in selected_pairs]
    baseline_texts = [str(pair.get("current") or "") for pair in selected_pairs]
    source_title, description = load_metadata(default_info_path(ass_path), fallback_title=ass_path.stem)
    report: Dict[str, Any] = {
        "scope": "shadow_only_no_output_or_publication_mutation",
        "source_ass_path": str(ass_path),
        "source_ass_sha256": _sha256_file(ass_path),
        "source_segment_count": len(eligible_pairs),
        "evaluated_segment_count": len(selected_pairs),
        "sampled": len(selected_pairs) < len(eligible_pairs),
        "source_text_sha256": _sha256_texts(source_texts),
        "baseline_text_sha256": _sha256_texts(baseline_texts),
        "baseline_provider": "rendered_ass",
        "shadow_provider": "agy",
        "shadow_model": settings.agy_subtitle_model,
        "promotion": "MANUAL_REVIEW_REQUIRED",
    }
    if not selected_pairs:
        report.update({"shadow_status": "NO_ELIGIBLE_SEGMENTS", "comparison_signal": "NO_COMPARISON"})
        return report

    context = build_translation_context(source_texts, title=source_title, description=description)
    quality_context = build_quality_context(source_texts, title=source_title, description=description)
    baseline = evaluate_translation_candidate(
        source_texts,
        baseline_texts,
        provider="rendered_ass",
        final_provider=True,
        quality_context=quality_context,
    )
    report["baseline"] = _decision_summary(baseline)
    try:
        shadow_texts = candidate_runner(source_texts, context.to_prompt_context())
        if len(shadow_texts) != len(source_texts):
            raise RuntimeError("AGY_SHADOW_ID_ALIGNMENT_FAILED")
        shadow = evaluate_translation_candidate(
            source_texts,
            shadow_texts,
            provider="agy",
            final_provider=True,
            quality_context=quality_context,
        )
    except Exception as exc:
        report.update({
            "shadow_status": "PROVIDER_FAILED",
            "shadow_error_class": type(exc).__name__,
            "comparison_signal": "NO_COMPARISON",
        })
        return report

    report.update({
        "shadow_status": "SUCCEEDED",
        "shadow_text_sha256": _sha256_texts(shadow_texts),
        "changed_segment_count": sum(left != right for left, right in zip(baseline_texts, shadow_texts)),
        "shadow": _decision_summary(shadow),
        "comparison_signal": _comparison_signal(report["baseline"], _decision_summary(shadow)),
    })
    return report


def _collect_reports(report_dir: Path, rollout_started_at: datetime) -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for path in sorted((report_dir / "samples").glob("*.json")):
        report = _load_json(path)
        if report and str(report.get("rollout_started_at") or "") == _iso(rollout_started_at):
            reports.append(report)
    return reports


def _build_summary(report_dir: Path, rollout_started_at: datetime, reports: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    statuses = Counter(str(report.get("shadow_status") or "UNKNOWN") for report in reports)
    signals = Counter(str(report.get("comparison_signal") or "UNKNOWN") for report in reports)
    shadow_blocked = sum(int((report.get("shadow") or {}).get("blocking_count") or 0) > 0 for report in reports)
    baseline_blocked = sum(int((report.get("baseline") or {}).get("blocking_count") or 0) > 0 for report in reports)
    now = _now()
    ends_at = rollout_started_at + timedelta(hours=_ROLL_OUT_HOURS)
    recommendation = "CONTINUE_SHADOW"
    if now >= ends_at:
        recommendation = "MANUAL_EVALUATION_REQUIRED"
    if statuses.get("PROVIDER_FAILED", 0) or shadow_blocked or signals.get("SHADOW_HIGHER_PENALTY", 0):
        recommendation = "HOLD_BASELINE_AND_MANUAL_REVIEW"
    return {
        "scope": "shadow_only_no_output_or_publication_mutation",
        "rollout_started_at": _iso(rollout_started_at),
        "rollout_ends_at": _iso(ends_at),
        "generated_at": _iso(now),
        "report_dir": str(report_dir),
        "unique_inputs_compared": len(reports),
        "shadow_status_counts": dict(sorted(statuses.items())),
        "comparison_signal_counts": dict(sorted(signals.items())),
        "baseline_blocked_count": baseline_blocked,
        "shadow_blocked_count": shadow_blocked,
        "recommendation": recommendation,
        "auto_promote": False,
        "manual_decision_required": True,
    }


def run_shadow_rollout(
    *,
    input_dir: Path,
    report_dir: Path,
    max_segments: int,
    start_if_missing: bool,
    candidate_runner: Callable[[Sequence[str], str], List[str]] = _run_agy_candidate,
) -> Dict[str, Any]:
    """增量处理影子期开始后的 ASS；同一输入哈希仅比较一次。"""
    manifest_path = report_dir / "rollout.json"
    manifest = _load_json(manifest_path)
    if manifest is None:
        if not start_if_missing:
            raise RuntimeError("AGY shadow rollout has not been initialized")
        started_at = _now()
        manifest = {
            "scope": "shadow_only_no_output_or_publication_mutation",
            "rollout_started_at": _iso(started_at),
            "rollout_ends_at": _iso(started_at + timedelta(hours=_ROLL_OUT_HOURS)),
            "production_subtitle_provider_order": settings.subtitle_translation_provider_order_list,
            "production_dubbing_provider_order": settings.dubbing_script_refinement_provider_order_list,
            "auto_promote": False,
        }
        _write_json(manifest_path, manifest)
    started_at = _parse_utc(str(manifest["rollout_started_at"]))

    evaluated = 0
    skipped = 0
    # 成片任务会将 ASS 放在 output/original_video 等子目录；只扫描根目录会
    # 漏掉已完成的真实候选。仍只读取固定 output 根目录下的常规文件。
    for ass_path in sorted(path for path in input_dir.rglob("*.ass") if path.is_file()):
        if ass_path.stat().st_mtime < started_at.timestamp():
            continue
        file_hash = _sha256_file(ass_path)
        report_path = report_dir / "samples" / f"{ass_path.stem}.{file_hash[:16]}.json"
        if report_path.is_file():
            skipped += 1
            continue
        report = _review_ass(ass_path, max_segments=max_segments, candidate_runner=candidate_runner)
        report["rollout_started_at"] = _iso(started_at)
        report["evaluated_at"] = _iso(_now())
        _write_json(report_path, report)
        evaluated += 1

    reports = _collect_reports(report_dir, started_at)
    summary = _build_summary(report_dir, started_at, reports)
    summary.update({"new_inputs_evaluated": evaluated, "already_compared_inputs": skipped})
    _write_json(report_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=_PROJECT_ROOT / "output")
    parser.add_argument("--report-dir", type=Path, default=_PROJECT_ROOT / settings.agy_shadow_report_dir)
    parser.add_argument("--max-segments", type=int, default=settings.agy_shadow_max_segments)
    parser.add_argument("--start-if-missing", action="store_true", help="首次执行时创建 72 小时影子期清单")
    parser.add_argument("--execute", action="store_true", help="允许调用 AGY；默认只拒绝执行，避免误触发外部模型")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Shadow review is dry by default; pass --execute after explicit approval.")
    if not settings.enable_agy_subtitle_shadow_review:
        raise SystemExit("ENABLE_AGY_SUBTITLE_SHADOW_REVIEW is false; refusing to run AGY shadow calls.")
    summary = run_shadow_rollout(
        input_dir=args.input_dir,
        report_dir=args.report_dir,
        max_segments=max(1, int(args.max_segments)),
        start_if_missing=args.start_if_missing,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

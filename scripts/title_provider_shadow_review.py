#!/usr/bin/env python3
"""离线比较当前标题与 AGY 标题候选，不改动 pipeline 产物或发布状态。

输入是 JSON 数组；每项至少包含 ``youtube_id``、``title``、``description``
和当前 ``short_title``。可选提供 ``display_title``、``hook_subtitle``。输出
供人工盲评使用，脚本本身不会修改 ``output/``、数据库或任何平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 新增 AGY 标题影子评测入口；仅产出可审计候选报告。 |
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from config.settings import settings  # noqa: E402
from video_processing.title_provider import TitleProviderError, generate_agy_title_bundle  # noqa: E402
from video_processing.utils.title_contract import TitleContractError, validate_title_bundle  # noqa: E402
from video_processing.utils.translation_quality_evaluator import evaluate_translation_candidate  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, required=True, help="历史样本 JSON 数组")
    parser.add_argument("--output-json", type=Path, required=True, help="评测报告输出路径")
    parser.add_argument("--limit", type=int, default=50, help="最多处理样本数，默认 50")
    parser.add_argument("--model", default=settings.copywriter_agy_model)
    parser.add_argument("--agy-bin", default=settings.copywriter_agy_bin)
    parser.add_argument("--timeout-seconds", type=int, default=settings.copywriter_agy_timeout_seconds)
    return parser.parse_args()


def _current_titles(case: dict[str, Any]) -> dict[str, str]:
    """规范化历史标题；历史条目允许没有 display_title。"""
    return {
        "platform_title": str(
            case.get("platform_title") or case.get("short_title") or case.get("old_short_title") or ""
        ).strip(),
        "display_title": str(case.get("display_title") or "").strip(),
        "hook_subtitle": str(case.get("hook_subtitle") or case.get("old_sub") or "").strip(),
    }


def _evaluate_titles(title: str, description: str, titles: dict[str, str], *, provider: str) -> dict[str, Any]:
    source_text = "\n".join(part for part in (title, description) if part)
    translated_text = "\n".join(value for value in titles.values() if value)
    quality = evaluate_translation_candidate(
        [source_text],
        [translated_text],
        provider=provider,
        final_provider=True,
        context_text=source_text,
    )
    try:
        validate_title_bundle(
            platform_title=titles["platform_title"],
            display_title=titles["display_title"],
            hook_subtitle=titles["hook_subtitle"],
            require_display_title=bool(titles["display_title"]),
        )
        contract_error = ""
    except TitleContractError as exc:
        contract_error = str(exc)
    return {
        "titles": titles,
        "contract_error": contract_error,
        "warning_codes": [issue.code for issue in quality.warning_issues],
        "blocking_codes": [issue.code for issue in quality.blocking_issues],
    }


def build_shadow_report(
    cases: list[dict[str, Any]],
    *,
    model: str,
    agy_bin: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """执行 AGY 影子生成；单条失败只记录，不影响其他样本。"""
    rows: list[dict[str, Any]] = []
    for case in cases:
        youtube_id = str(case.get("youtube_id") or "")
        title = str(case.get("title") or case.get("yt_title") or "")
        description = str(case.get("description") or case.get("desc") or "")
        current = _current_titles(case)
        row: dict[str, Any] = {
            "youtube_id": youtube_id,
            "source_title": title,
            "current": _evaluate_titles(title, description, current, provider="current"),
            "agy": None,
            "manual_review": {"winner": "", "reason": "", "fact_checked": False},
        }
        try:
            generated = generate_agy_title_bundle(
                agy_bin=agy_bin,
                model=model,
                timeout_seconds=timeout_seconds,
                title=title,
                description=description,
            )
            row["agy"] = _evaluate_titles(
                title,
                description,
                {
                    "platform_title": generated.platform_title,
                    "display_title": generated.display_title,
                    "hook_subtitle": generated.hook_subtitle,
                },
                provider=f"agy:{model}",
            )
        except TitleProviderError as exc:
            row["agy"] = {"provider_error": type(exc).__name__}
        rows.append(row)

    agy_failures = sum(1 for row in rows if "provider_error" in (row.get("agy") or {}))
    return {
        "scope": "shadow_only_no_output_or_publication_mutation",
        "model": model,
        "sample_count": len(rows),
        "agy_provider_failures": agy_failures,
        "current_contract_failures": sum(bool(row["current"]["contract_error"]) for row in rows),
        "agy_contract_failures": sum(bool((row.get("agy") or {}).get("contract_error")) for row in rows),
        "agy_blocking_issue_counts": dict(Counter(
            code for row in rows for code in (row.get("agy") or {}).get("blocking_codes", [])
        )),
        "manual_decision_required": "请对每条填写 manual_review；报告本身不构成生产切换批准。",
        "rows": rows,
    }


def main() -> int:
    args = _parse_args()
    if not 1 <= args.limit <= 50:
        raise ValueError("--limit 必须在 1 到 50 之间")
    raw_cases = json.loads(args.input_json.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise ValueError("--input-json 必须为 JSON 数组")
    cases = [case for case in raw_cases if isinstance(case, dict)][:args.limit]
    report = build_shadow_report(
        cases,
        model=args.model,
        agy_bin=args.agy_bin,
        timeout_seconds=args.timeout_seconds,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

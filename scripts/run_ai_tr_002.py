#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行 AI-TR-002 的受限离线 DeepSeek thinking A/B 实验。

样本、顺序和硬上限来自 docs/guides/ai_tr_002_experiment_spec.md。该脚本
不访问 PipelineDB、不启动发布流程；默认 dry-run，只有 --execute 才会调用 API。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-07-28 | Codex | 实现 AI-TR-002 九样本交叉顺序、请求字节、输出 token 与预算预留闸门 |
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _PROJECT_ROOT / "src"
for _path in (str(_PROJECT_ROOT), str(_SRC_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from config.settings import settings  # noqa: E402
from scripts.deepseek_thinking_ab_review import (  # noqa: E402
    DEFAULT_INPUT_CACHE_HIT_PRICE_PER_MILLION,
    DEFAULT_INPUT_PRICE_PER_MILLION,
    DEFAULT_OUTPUT_PRICE_PER_MILLION,
    OfflineVariantError,
    run_review,
)


EXPERIMENT_ID = "AI-TR-002"
MAX_SAMPLES = 9
MAX_SEGMENTS = 12
MAX_SOURCE_CHARS = 2400
MAX_CONTEXT_CHARS = 1800
MAX_OUTPUT_TOKENS = 1200
MAX_REQUEST_BYTES = 10_000
MAX_REQUESTS = 18
MAX_BUDGET_USD = 0.05
SAMPLES = (
    ("finance", "75yVZjvfdTo", "production_baseline,disabled"),
    ("finance", "LLNCelqS7PM", "disabled,production_baseline"),
    ("finance", "d57IXaxhZzo", "production_baseline,disabled"),
    ("technology", "xHr18GEJqck", "production_baseline,disabled"),
    ("technology", "w24zeYdwnXU", "disabled,production_baseline"),
    ("technology", "aqyZ87euzz0", "production_baseline,disabled"),
    ("speech_education", "QBgpMFIlkx8", "disabled,production_baseline"),
    ("speech_education", "cbiyPOn-__M", "production_baseline,disabled"),
    ("speech_education", "Bz_iIA3kaLI", "disabled,production_baseline"),
)


def maximum_reserved_cost_usd(*, request_count: int, max_request_bytes: int, max_output_tokens: int,
                              input_price_per_million: float, output_price_per_million: float) -> float:
    """以 1 byte=1 token 的保守上界预留费用，避免实际请求越过批准预算。"""
    return round(
        request_count * (
            max_request_bytes * input_price_per_million / 1_000_000
            + max_output_tokens * output_price_per_million / 1_000_000
        ),
        8,
    )


def _percentile(values: Iterable[int], percentile: float) -> int | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))
    return ordered[index]


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按模式和领域汇总 usage、延迟与质量守门结果，保留顺序字段供人工复核。"""
    buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for result in results:
        for variant in result.get("summary", {}).get("variants", []):
            item = dict(variant)
            item["domain"] = result["domain"]
            buckets[item["thinking_mode"]][result["domain"]].append(item)

    def metrics(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        usage_keys = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
        return {
            "samples": len(items),
            "latency_p50_ms": _percentile([item["latency_ms"] for item in items], 0.50),
            "latency_p95_ms": _percentile([item["latency_ms"] for item in items], 0.95),
            "estimated_cost_usd": round(sum(item.get("estimated_cost_usd") or 0 for item in items), 8),
            "usage": {key: sum(item.get("usage", {}).get(key, 0) for item in items) for key in usage_keys},
            "warning_count": sum(item.get("quality", {}).get("warning_count", 0) for item in items),
            "blocking_count": sum(item.get("quality", {}).get("blocking_count", 0) for item in items),
        }

    return {
        mode: {
            "all": metrics([item for domain_items in domains.values() for item in domain_items]),
            "by_domain": {domain: metrics(items) for domain, items in sorted(domains.items())},
        }
        for mode, domains in sorted(buckets.items())
    }


def run_experiment(*, execute: bool, max_budget_usd: float = MAX_BUDGET_USD) -> Dict[str, Any]:
    """运行固定九样本计划；预留费用超过预算时在任何 API 调用前拒绝执行。"""
    request_count = len(SAMPLES) * 2
    if len(SAMPLES) != MAX_SAMPLES or request_count != MAX_REQUESTS:
        raise RuntimeError("AI-TR-002 sample plan no longer matches its approved limits")
    max_reserved_cost = maximum_reserved_cost_usd(
        request_count=request_count, max_request_bytes=MAX_REQUEST_BYTES,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        input_price_per_million=DEFAULT_INPUT_PRICE_PER_MILLION,
        output_price_per_million=DEFAULT_OUTPUT_PRICE_PER_MILLION,
    )
    if max_reserved_cost > max_budget_usd:
        raise RuntimeError(
            f"Approved budget is insufficient for reserved worst case: {max_reserved_cost} > {max_budget_usd}"
        )

    results: List[Dict[str, Any]] = []
    failure: Dict[str, Any] | None = None
    attempted_requests = 0
    for domain, youtube_id, thinking_order in SAMPLES:
        order = [item.strip() for item in thinking_order.split(",")]
        try:
            report = run_review(
                _PROJECT_ROOT / "output" / "original_video" / f"{youtube_id}.ass",
                info_json=None,
                output_path=_PROJECT_ROOT / "output" / "research" / EXPERIMENT_ID / f"{youtube_id}.json",
                max_segments=MAX_SEGMENTS, max_source_chars=MAX_SOURCE_CHARS,
                model=settings.deepseek_model or "deepseek-v4-flash", execute=execute,
                input_price_per_million=DEFAULT_INPUT_PRICE_PER_MILLION,
                input_cache_hit_price_per_million=DEFAULT_INPUT_CACHE_HIT_PRICE_PER_MILLION,
                output_price_per_million=DEFAULT_OUTPUT_PRICE_PER_MILLION,
                thinking_order=thinking_order, max_context_chars=MAX_CONTEXT_CHARS,
                max_output_tokens=MAX_OUTPUT_TOKENS, max_request_bytes=MAX_REQUEST_BYTES,
            )
        except OfflineVariantError as exc:
            attempted_requests += order.index(exc.thinking_mode) + 1
            failure = {
                "domain": domain, "youtube_id": youtube_id, "error_type": type(exc).__name__,
                "error": str(exc), "thinking_mode": exc.thinking_mode, "latency_ms": exc.latency_ms,
                "usage": exc.usage, "estimated_cost_usd": exc.estimated_cost_usd,
            }
            break
        except Exception as exc:
            attempted_requests += 1
            failure = {
                "domain": domain, "youtube_id": youtube_id, "error_type": type(exc).__name__,
                "error": str(exc),
            }
            break
        report["domain"] = domain
        report["youtube_id"] = youtube_id
        results.append(report)
        attempted_requests += 2

    return {
        "experiment_id": EXPERIMENT_ID,
        "mode": "executed_offline_ab" if execute else "dry_run",
        "limits": {
            "samples": MAX_SAMPLES, "requests": MAX_REQUESTS, "max_budget_usd": max_budget_usd,
            "max_reserved_cost_usd": max_reserved_cost, "max_segments": MAX_SEGMENTS,
            "max_source_chars": MAX_SOURCE_CHARS, "max_context_chars": MAX_CONTEXT_CHARS,
            "max_output_tokens": MAX_OUTPUT_TOKENS, "max_request_bytes": MAX_REQUEST_BYTES,
        },
        "results": results,
        "attempted_requests": attempted_requests,
        "aggregate": summarize(results) if execute else {},
        "failure": failure,
        "decision": "REPEAT" if failure else ("NEEDS_HUMAN_REVIEW" if execute else "DRY_RUN_ONLY"),
        "side_effects": "No PipelineDB write, no publish-state change, no browser uploader call.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the approved bounded AI-TR-002 offline experiment.")
    parser.add_argument("--execute", action="store_true", help="Send the approved 18 bounded DeepSeek requests")
    parser.add_argument("--max-budget-usd", type=float, default=MAX_BUDGET_USD)
    parser.add_argument("--output", type=Path, default=_PROJECT_ROOT / "output" / "research" / EXPERIMENT_ID / "report.json")
    args = parser.parse_args()
    report = run_experiment(execute=args.execute, max_budget_usd=args.max_budget_usd)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"experiment_id": EXPERIMENT_ID, "mode": report["mode"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行 AI-TR-003 的受限 JSON 输出契约诊断。

本脚本只读取既有字幕和元数据，默认 dry-run。只有在负责人已按
docs/guides/ai_tr_003_experiment_spec.md 批准后，显式传入 ``--execute`` 才会
发送最多四次 API 请求。它不访问 PipelineDB，不创建发布任务。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-07-29 | Codex | 实现 AI-TR-003 的 JSON 契约对照、请求/预算闸门与无正文审计报告 |
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
    OfflineRequestError,
    OfflineVariantError,
    build_output_contract_payload,
    execute_output_contract_variant,
    normalize_output_contract_order,
    select_pairs,
)
from scripts.translation_ab_review import (  # noqa: E402
    build_quality_context,
    default_info_path,
    load_ass_pairs,
    load_metadata,
    summarize_event,
)
from video_processing.utils.translation_context import build_translation_context  # noqa: E402
from video_processing.utils.translation_quality_evaluator import evaluate_translation_candidate  # noqa: E402


EXPERIMENT_ID = "AI-TR-003"
MAX_SAMPLES = 2
MAX_SEGMENTS = 6
MAX_SOURCE_CHARS = 1200
MAX_CONTEXT_CHARS = 800
MAX_OUTPUT_TOKENS = 1200
MAX_REQUEST_BYTES = 6000
MAX_REQUESTS = 4
MAX_BUDGET_USD = 0.01
SAMPLES = (
    ("finance", "75yVZjvfdTo", "baseline,json_object"),
    ("technology", "xHr18GEJqck", "json_object,baseline"),
)


def maximum_reserved_cost_usd(*, request_count: int, max_request_bytes: int, max_output_tokens: int,
                              input_price_per_million: float, output_price_per_million: float) -> float:
    """以 1 byte=1 token 的保守上界预留费用，防止外发越过批准预算。"""
    return round(
        request_count * (
            max_request_bytes * input_price_per_million / 1_000_000
            + max_output_tokens * output_price_per_million / 1_000_000
        ),
        8,
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_sample(domain: str, youtube_id: str, output_order: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """冻结单个样本的输入 hash 与两份 payload，报告中不保留字幕正文。"""
    ass_path = _PROJECT_ROOT / "output" / "original_video" / f"{youtube_id}.ass"
    pairs = load_ass_pairs(ass_path)
    selected_pairs = select_pairs(
        pairs, max_segments=MAX_SEGMENTS, max_source_chars=MAX_SOURCE_CHARS,
    )
    if not selected_pairs:
        raise ValueError(f"No subtitle sample fits the AI-TR-003 limits: {ass_path}")
    info_path = default_info_path(ass_path)
    title, description = load_metadata(info_path, fallback_title=ass_path.stem)
    source_texts = [pair["source"] for pair in selected_pairs]
    context = build_translation_context(source_texts, title=title, description=description)
    contracts = normalize_output_contract_order(output_order)
    model = settings.deepseek_model or "deepseek-v4-flash"
    payloads = [
        build_output_contract_payload(
            source_texts, context_text=context.to_prompt_context(max_chars=MAX_CONTEXT_CHARS),
            model=model, output_contract=contract, max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        for contract in contracts
    ]
    payload_bytes = [len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) for payload in payloads]
    if any(size > MAX_REQUEST_BYTES for size in payload_bytes):
        raise RuntimeError(f"AI-TR-003 request exceeds {MAX_REQUEST_BYTES} byte cap: {payload_bytes}")
    plan = {
        "domain": domain,
        "youtube_id": youtube_id,
        "input": {
            "ass_sha256": _sha256_file(ass_path),
            "metadata_sha256": _sha256_file(info_path) if info_path.exists() else None,
            "selected_segment_count": len(selected_pairs),
            "selected_source_chars": sum(len(item["source"]) for item in selected_pairs),
        },
        "variants": [
            {
                "output_contract": contract,
                "request_bytes": size,
                "request_sha256": hashlib.sha256(
                    json.dumps(payload, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
            }
            for contract, payload, size in zip(contracts, payloads, payload_bytes)
        ],
    }
    execution = {
        "source_texts": source_texts,
        "context_text": context.to_prompt_context(max_chars=MAX_CONTEXT_CHARS),
        "quality_context": build_quality_context(source_texts, title=title, description=description),
        "model": model,
        "contracts": contracts,
    }
    return plan, execution


def _failure_record(exc: Exception, *, domain: str, youtube_id: str, output_contract: str) -> Dict[str, Any]:
    """将失败压缩到 JSON 可审阅的非敏感字段。"""
    record: Dict[str, Any] = {
        "domain": domain,
        "youtube_id": youtube_id,
        "output_contract": output_contract,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    if isinstance(exc, OfflineVariantError):
        record.update({
            "latency_ms": exc.latency_ms,
            "usage": exc.usage,
            "estimated_cost_usd": exc.estimated_cost_usd,
            "audit": exc.audit,
        })
    elif isinstance(exc, OfflineRequestError):
        record["status_code"] = exc.status_code
        record["failure_classification"] = "HTTP_ERROR" if exc.status_code is not None else "UNKNOWN"
    return record


def run_experiment(*, execute: bool, max_budget_usd: float = MAX_BUDGET_USD) -> Dict[str, Any]:
    """运行或预览固定两样本计划；任意失败后停止，绝不自动补偿重试。"""
    request_count = len(SAMPLES) * 2
    if len(SAMPLES) != MAX_SAMPLES or request_count != MAX_REQUESTS:
        raise RuntimeError("AI-TR-003 sample plan no longer matches its approved limits")
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

    plans: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    failure: Dict[str, Any] | None = None
    attempted_requests = 0
    for domain, youtube_id, output_order in SAMPLES:
        plan, execution = _prepare_sample(domain, youtube_id, output_order)
        plans.append(plan)
        if not execute:
            continue
        for output_contract in execution["contracts"]:
            try:
                variant = execute_output_contract_variant(
                    source_texts=execution["source_texts"], context_text=execution["context_text"],
                    model=execution["model"], output_contract=output_contract,
                    input_price_per_million=DEFAULT_INPUT_PRICE_PER_MILLION,
                    input_cache_hit_price_per_million=DEFAULT_INPUT_CACHE_HIT_PRICE_PER_MILLION,
                    output_price_per_million=DEFAULT_OUTPUT_PRICE_PER_MILLION,
                    max_output_tokens=MAX_OUTPUT_TOKENS, max_request_bytes=MAX_REQUEST_BYTES,
                )
            except (OfflineVariantError, OfflineRequestError, RuntimeError) as exc:
                attempted_requests += 1
                failure = _failure_record(
                    exc, domain=domain, youtube_id=youtube_id, output_contract=output_contract,
                )
                break
            decision = evaluate_translation_candidate(
                execution["source_texts"], variant["translations"],
                provider=f"DeepSeek:{output_contract}", final_provider=True,
                quality_context=execution["quality_context"],
            )
            results.append({
                "domain": domain,
                "youtube_id": youtube_id,
                "output_contract": output_contract,
                "model": variant["model"],
                "latency_ms": variant["latency_ms"],
                "usage": variant["usage"],
                "estimated_cost_usd": variant["estimated_cost_usd"],
                "audit": variant["audit"],
                "quality": summarize_event(decision.to_audit_event(final_provider=True)),
            })
            attempted_requests += 1
        if failure:
            break

    return {
        "experiment_id": EXPERIMENT_ID,
        "mode": "executed_offline_contract" if execute else "dry_run",
        "limits": {
            "samples": MAX_SAMPLES,
            "requests": MAX_REQUESTS,
            "max_budget_usd": max_budget_usd,
            "max_reserved_cost_usd": max_reserved_cost,
            "max_segments": MAX_SEGMENTS,
            "max_source_chars": MAX_SOURCE_CHARS,
            "max_context_chars": MAX_CONTEXT_CHARS,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_request_bytes": MAX_REQUEST_BYTES,
        },
        "plans": plans,
        "results": results,
        "attempted_requests": attempted_requests,
        "failure": failure,
        "decision": "REPEAT" if failure else ("NEEDS_HUMAN_REVIEW" if execute else "DRY_RUN_ONLY"),
        "side_effects": "No PipelineDB write, no publish-state change, no browser uploader call.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the approved bounded AI-TR-003 contract diagnostic.")
    parser.add_argument("--execute", action="store_true", help="Send the separately approved four bounded API requests")
    parser.add_argument("--max-budget-usd", type=float, default=MAX_BUDGET_USD)
    parser.add_argument(
        "--output", type=Path,
        default=_PROJECT_ROOT / "output" / "research" / EXPERIMENT_ID / "report.json",
    )
    args = parser.parse_args()
    report = run_experiment(execute=args.execute, max_budget_usd=args.max_budget_usd)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"experiment_id": EXPERIMENT_ID, "mode": report["mode"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

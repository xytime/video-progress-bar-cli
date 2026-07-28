#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek thinking 开关的离线字幕 A/B 评估。

本脚本只读取既有双语 ASS 和项目配置，不连接 PipelineDB、不触发状态机、
不创建发布任务。默认 dry-run；只有显式传入 ``--execute`` 才会对同一小样本
最多各发起一次“保持生产请求形态”和“thinking=disabled”的 API 请求。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-07-28 | Codex | 新增受限离线 A/B：比较 DeepSeek 当前请求形态与显式关闭 thinking 的质量、延迟、token 和价格估算 |
| 1.1.0 | 2026-07-28 | Codex | 支持固定输出、请求字节和顺序上限，供 AI-TR-002 交叉顺序实验使用 |
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from config.settings import settings  # noqa: E402
from scripts.translation_ab_review import (  # noqa: E402
    build_diff_samples,
    build_quality_context,
    default_info_path,
    load_ass_pairs,
    load_metadata,
    summarize_event,
)
from video_processing.utils.deepseek_translation import (  # noqa: E402
    _build_payload,
    _extract_message_content,
    _parse_translation_json,
)
from video_processing.utils.translation_context import build_translation_context  # noqa: E402
from video_processing.utils.translation_quality_evaluator import evaluate_translation_candidate  # noqa: E402


# 2026-07-28 DeepSeek V4 Flash 官网标准价快照；运行时可通过 CLI 覆盖。
DEFAULT_INPUT_PRICE_PER_MILLION = 0.14
DEFAULT_INPUT_CACHE_HIT_PRICE_PER_MILLION = 0.0028
DEFAULT_OUTPUT_PRICE_PER_MILLION = 0.28
_VALID_THINKING_MODES = {"production_baseline", "disabled"}


class OfflineVariantError(RuntimeError):
    """单次离线候选不可用时保留最小审计信息，不保留模型原始响应。"""

    def __init__(self, message: str, *, thinking_mode: str, latency_ms: int, usage: Dict[str, int],
                 estimated_cost_usd: float | None):
        super().__init__(message)
        self.thinking_mode = thinking_mode
        self.latency_ms = latency_ms
        self.usage = usage
        self.estimated_cost_usd = estimated_cost_usd


def select_pairs(
    pairs: Sequence[Dict[str, str]], *, max_segments: int, max_source_chars: int
) -> List[Dict[str, str]]:
    """顺序选取小样本，严格限制外发字幕量与单次实验成本。"""
    selected: List[Dict[str, str]] = []
    source_chars = 0
    for pair in pairs:
        source = str(pair.get("source") or "")
        if not source:
            continue
        if len(selected) >= max_segments:
            break
        if selected and source_chars + len(source) > max_source_chars:
            break
        selected.append(pair)
        source_chars += len(source)
    return selected


def normalize_thinking_order(thinking_order: str | Sequence[str]) -> List[str]:
    """校验两个候选必须各出现一次，避免 A/B 请求偷偷改变变量数量。"""
    if isinstance(thinking_order, str):
        modes = [item.strip() for item in thinking_order.split(",") if item.strip()]
    else:
        modes = [str(item).strip() for item in thinking_order if str(item).strip()]
    if len(modes) != 2 or set(modes) != _VALID_THINKING_MODES:
        raise ValueError("thinking order must contain production_baseline and disabled exactly once")
    return modes


def build_variant_payload(
    source_texts: Sequence[str], *, context_text: str, model: str, thinking_mode: str,
    max_output_tokens: int | None = None,
) -> Dict[str, Any]:
    """构造与生产翻译相同的请求，仅允许在 thinking 字段上产生差异。"""
    payload = _build_payload(list(source_texts), context_text=context_text, model=model)
    if thinking_mode == "disabled":
        payload["thinking"] = {"type": "disabled"}
    elif thinking_mode != "production_baseline":
        raise ValueError(f"Unsupported thinking mode: {thinking_mode}")
    if max_output_tokens is not None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        payload["max_tokens"] = max_output_tokens
    return payload


def reported_usage(data: Dict[str, Any]) -> Dict[str, int]:
    """仅保留供应商响应中的可计数 usage 字段，不保存内容或推理文本。"""
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {}
    return {str(key): int(value) for key, value in usage.items() if isinstance(value, int)}


def estimate_cost_usd(
    usage: Dict[str, int], *, input_price_per_million: float,
    input_cache_hit_price_per_million: float, output_price_per_million: float,
) -> float | None:
    """按响应 token 和缓存拆分价格计算估算值；未知 usage 时不猜测。"""
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if prompt_tokens is None or completion_tokens is None:
        return None
    cache_hit_tokens = usage.get("prompt_cache_hit_tokens", 0)
    cache_miss_tokens = usage.get("prompt_cache_miss_tokens", prompt_tokens - cache_hit_tokens)
    if cache_hit_tokens < 0 or cache_miss_tokens < 0 or cache_hit_tokens + cache_miss_tokens != prompt_tokens:
        cache_hit_tokens = 0
        cache_miss_tokens = prompt_tokens
    return round(
        cache_miss_tokens * input_price_per_million / 1_000_000
        + cache_hit_tokens * input_cache_hit_price_per_million / 1_000_000
        + completion_tokens * output_price_per_million / 1_000_000,
        8,
    )


def execute_variant(
    *,
    source_texts: Sequence[str],
    context_text: str,
    model: str,
    thinking_mode: str,
    input_price_per_million: float,
    input_cache_hit_price_per_million: float,
    output_price_per_million: float,
    max_output_tokens: int | None = None,
    max_request_bytes: int | None = None,
) -> Dict[str, Any]:
    """执行一次离线请求。异常上抛，避免把失败伪装成可比较的质量结果。"""
    api_key = settings.deepseek_api_key or ""
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured; dry-run remains available.")
    base_url = (settings.deepseek_base_url or "https://api.deepseek.com").rstrip("/")
    payload = build_variant_payload(
        source_texts, context_text=context_text, model=model, thinking_mode=thinking_mode,
        max_output_tokens=max_output_tokens,
    )
    request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if max_request_bytes is not None and len(request_body) > max_request_bytes:
        raise RuntimeError(
            f"Offline request exceeds byte cap: {len(request_body)} > {max_request_bytes}"
        )
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=request_body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"DeepSeek offline experiment request failed: {type(exc).__name__}: {exc}") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    content = _extract_message_content(data)
    translations = _parse_translation_json(content, expected_count=len(source_texts)) if content else None
    usage = reported_usage(data)
    estimated_cost = estimate_cost_usd(
        usage,
        input_price_per_million=input_price_per_million,
        input_cache_hit_price_per_million=input_cache_hit_price_per_million,
        output_price_per_million=output_price_per_million,
    )
    if translations is None:
        raise OfflineVariantError(
            "DeepSeek returned no parseable aligned translation candidate.",
            thinking_mode=thinking_mode, latency_ms=elapsed_ms, usage=usage,
            estimated_cost_usd=estimated_cost,
        )
    return {
        "thinking_mode": thinking_mode,
        "model": model,
        "latency_ms": elapsed_ms,
        "usage": usage,
        "estimated_cost_usd": estimated_cost,
        "translations": translations,
    }


def build_dry_run_report(
    *, ass_path: Path, selected_pairs: Sequence[Dict[str, str]], model: str, output_path: Path,
    thinking_order: Sequence[str] = ("production_baseline", "disabled"),
    max_context_chars: int = 1800, max_output_tokens: int | None = None,
    max_request_bytes: int | None = None,
) -> Dict[str, Any]:
    """生成可审阅的调用计划，不向任何 API 外发文本。"""
    return {
        "mode": "dry_run",
        "input": str(ass_path),
        "output": str(output_path),
        "model": model,
        "selected_segment_count": len(selected_pairs),
        "selected_source_chars": sum(len(pair["source"]) for pair in selected_pairs),
        "request_count": len(thinking_order),
        "thinking_order": list(thinking_order),
        "max_context_chars": max_context_chars,
        "max_output_tokens": max_output_tokens,
        "max_request_bytes": max_request_bytes,
        "side_effects": "No API call, no PipelineDB write, no publish-state change.",
    }


def run_review(
    ass_path: Path,
    *,
    info_json: Path | None,
    output_path: Path,
    max_segments: int,
    max_source_chars: int,
    model: str,
    execute: bool,
    input_price_per_million: float,
    input_cache_hit_price_per_million: float,
    output_price_per_million: float,
    thinking_order: str | Sequence[str] = ("production_baseline", "disabled"),
    max_context_chars: int = 1800,
    max_output_tokens: int | None = None,
    max_request_bytes: int | None = None,
) -> Dict[str, Any]:
    """执行或预览一轮受限 A/B。"""
    pairs = load_ass_pairs(ass_path)
    if not pairs:
        raise ValueError(f"No Default subtitle pairs found in {ass_path}")
    selected_pairs = select_pairs(
        pairs, max_segments=max(1, max_segments), max_source_chars=max(1, max_source_chars)
    )
    if not selected_pairs:
        raise ValueError("No subtitle sample fits the requested limits.")
    order = normalize_thinking_order(thinking_order)
    if not execute:
        return build_dry_run_report(
            ass_path=ass_path, selected_pairs=selected_pairs, model=model, output_path=output_path,
            thinking_order=order, max_context_chars=max_context_chars,
            max_output_tokens=max_output_tokens, max_request_bytes=max_request_bytes,
        )

    title, description = load_metadata(info_json or default_info_path(ass_path), fallback_title=ass_path.stem)
    source_texts = [pair["source"] for pair in selected_pairs]
    current_translations = [pair.get("current", "") for pair in selected_pairs]
    context = build_translation_context(source_texts, title=title, description=description)
    quality_context = build_quality_context(source_texts, title=title, description=description)
    variant_results = [
        execute_variant(
            source_texts=source_texts, context_text=context.to_prompt_context(max_chars=max_context_chars), model=model,
            thinking_mode=thinking_mode, input_price_per_million=input_price_per_million,
            input_cache_hit_price_per_million=input_cache_hit_price_per_million,
            max_output_tokens=max_output_tokens, max_request_bytes=max_request_bytes,
            output_price_per_million=output_price_per_million,
        )
        for thinking_mode in order
    ]
    events = []
    for variant in variant_results:
        decision = evaluate_translation_candidate(
            source_texts, variant["translations"], provider=f"DeepSeek:{variant['thinking_mode']}",
            final_provider=True, quality_context=quality_context,
        )
        event = decision.to_audit_event(final_provider=True)
        variant["quality"] = summarize_event(event)
        events.append(event)
    current_event = evaluate_translation_candidate(
        source_texts, current_translations, provider="CurrentASS", final_provider=True,
        quality_context=quality_context,
    ).to_audit_event(final_provider=True)
    return {
        "mode": "executed_offline_ab",
        "input": str(ass_path),
        "output": str(output_path),
        "source_title": title,
        "model": model,
        "selected_segment_count": len(selected_pairs),
        "selected_source_chars": sum(len(text) for text in source_texts),
        "thinking_order": order,
        "max_context_chars": max_context_chars,
        "max_output_tokens": max_output_tokens,
        "max_request_bytes": max_request_bytes,
        "pricing_snapshot": {
            "input_price_per_million_usd": input_price_per_million,
            "input_cache_hit_price_per_million_usd": input_cache_hit_price_per_million,
            "output_price_per_million_usd": output_price_per_million,
            "basis": "Provider response usage; includes reported prompt-cache split, excludes discounts and tax.",
        },
        "summary": {
            "current": summarize_event(current_event),
            "variants": [
                {key: value for key, value in item.items() if key != "translations"}
                for item in variant_results
            ],
        },
        "events": [current_event, *events],
        "diff_samples": {
            variant["thinking_mode"]: build_diff_samples(
                selected_pairs, variant["translations"], limit=8
            )
            for variant in variant_results
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded offline DeepSeek thinking A/B for existing subtitles.")
    parser.add_argument("ass_path", type=Path, help="Existing bilingual ASS path")
    parser.add_argument("--info-json", type=Path, default=None, help="Optional yt-dlp metadata JSON")
    parser.add_argument("--output", type=Path, default=None, help="Result JSON path (default: output/research)")
    parser.add_argument("--max-segments", type=int, default=12, help="Hard cap for sampled subtitle segments")
    parser.add_argument("--max-source-chars", type=int, default=2400, help="Hard cap for source characters sent per variant")
    parser.add_argument("--model", default=None, help="DeepSeek model (default: configured model)")
    parser.add_argument("--thinking-order", default="production_baseline,disabled", help="Comma-separated A/B order")
    parser.add_argument("--max-context-chars", type=int, default=1800)
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--max-request-bytes", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Actually send two bounded API requests")
    parser.add_argument("--input-price-per-million", type=float, default=DEFAULT_INPUT_PRICE_PER_MILLION)
    parser.add_argument("--input-cache-hit-price-per-million", type=float, default=DEFAULT_INPUT_CACHE_HIT_PRICE_PER_MILLION)
    parser.add_argument("--output-price-per-million", type=float, default=DEFAULT_OUTPUT_PRICE_PER_MILLION)
    args = parser.parse_args()

    model = args.model or settings.deepseek_model or "deepseek-v4-flash"
    output_path = args.output or (_PROJECT_ROOT / "output" / "research" / f"{args.ass_path.stem}_deepseek_thinking_ab.json")
    report = run_review(
        args.ass_path, info_json=args.info_json, output_path=output_path,
        max_segments=args.max_segments, max_source_chars=args.max_source_chars,
        model=model, execute=args.execute,
        input_price_per_million=args.input_price_per_million,
        input_cache_hit_price_per_million=args.input_cache_hit_price_per_million,
        output_price_per_million=args.output_price_per_million,
        thinking_order=args.thinking_order, max_context_chars=max(1, args.max_context_chars),
        max_output_tokens=args.max_output_tokens, max_request_bytes=args.max_request_bytes,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "input", "output", "model") if key in report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

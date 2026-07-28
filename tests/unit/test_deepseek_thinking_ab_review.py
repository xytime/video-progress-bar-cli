# -*- coding: utf-8 -*-
"""Unit tests for the bounded offline DeepSeek thinking A/B experiment.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-07-28 | Codex | 覆盖样本成本上限、thinking 对照请求与价格估算的离线契约 |
"""

import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.deepseek_thinking_ab_review import (  # noqa: E402
    build_dry_run_report,
    build_variant_payload,
    estimate_cost_usd,
    OfflineVariantError,
    normalize_thinking_order,
    reported_usage,
    select_pairs,
)


def test_select_pairs_respects_segment_and_character_caps():
    pairs = [
        {"source": "one", "current": "一"},
        {"source": "two", "current": "二"},
        {"source": "three", "current": "三"},
    ]

    selected = select_pairs(pairs, max_segments=3, max_source_chars=6)

    assert [item["source"] for item in selected] == ["one", "two"]


def test_variant_payload_only_adds_explicit_disabled_thinking():
    baseline = build_variant_payload(["Hello"], context_text="", model="test", thinking_mode="production_baseline")
    disabled = build_variant_payload(["Hello"], context_text="", model="test", thinking_mode="disabled")

    assert "thinking" not in baseline
    assert disabled["thinking"] == {"type": "disabled"}
    for key in ("model", "messages", "stream", "temperature"):
        assert disabled[key] == baseline[key]


def test_variant_payload_can_apply_the_same_output_cap_to_both_modes():
    baseline = build_variant_payload(
        ["Hello"], context_text="", model="test", thinking_mode="production_baseline", max_output_tokens=1200
    )
    disabled = build_variant_payload(
        ["Hello"], context_text="", model="test", thinking_mode="disabled", max_output_tokens=1200
    )

    assert baseline["max_tokens"] == disabled["max_tokens"] == 1200
    assert normalize_thinking_order("disabled,production_baseline") == ["disabled", "production_baseline"]


def test_usage_and_cost_are_based_only_on_provider_token_counts():
    usage = reported_usage({"usage": {"prompt_tokens": 8_000, "completion_tokens": 600, "ignored": "no"}})

    assert usage == {"prompt_tokens": 8_000, "completion_tokens": 600}
    assert estimate_cost_usd(
        usage, input_price_per_million=0.14, input_cache_hit_price_per_million=0.0028,
        output_price_per_million=0.28,
    ) == 0.001288
    assert estimate_cost_usd(
        {"prompt_tokens": 500, "completion_tokens": 232, "prompt_cache_hit_tokens": 384, "prompt_cache_miss_tokens": 116},
        input_price_per_million=0.14, input_cache_hit_price_per_million=0.0028,
        output_price_per_million=0.28,
    ) == 0.00008228
    assert estimate_cost_usd(
        {}, input_price_per_million=0.14, input_cache_hit_price_per_million=0.0028,
        output_price_per_million=0.28,
    ) is None


def test_dry_run_declares_no_external_or_pipeline_side_effects(tmp_path):
    report = build_dry_run_report(
        ass_path=Path("sample.ass"),
        selected_pairs=[{"source": "Hello", "current": "你好"}],
        model="deepseek-v4-flash",
        output_path=tmp_path / "report.json",
    )

    assert report["mode"] == "dry_run"
    assert report["request_count"] == 2
    assert "No API call" in report["side_effects"]


def test_offline_variant_error_keeps_auditable_metadata_without_response_body():
    error = OfflineVariantError(
        "invalid aligned JSON", thinking_mode="production_baseline", latency_ms=123,
        usage={"prompt_tokens": 20}, estimated_cost_usd=0.0001,
    )

    assert error.thinking_mode == "production_baseline"
    assert error.usage == {"prompt_tokens": 20}
    assert "response" not in error.__dict__

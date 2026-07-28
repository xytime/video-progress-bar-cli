# -*- coding: utf-8 -*-
"""Unit tests for the fixed-scope AI-TR-002 experiment runner.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-07-28 | Codex | 验证实验计划的请求数和预算预留在 API 调用前可计算 |
"""

import sys
from pathlib import Path
from unittest.mock import patch

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.run_ai_tr_002 import (  # noqa: E402
    MAX_BUDGET_USD,
    MAX_OUTPUT_TOKENS,
    MAX_REQUEST_BYTES,
    MAX_REQUESTS,
    OfflineVariantError,
    SAMPLES,
    maximum_reserved_cost_usd,
    run_experiment,
)


def test_ai_tr_002_has_exactly_the_approved_request_count():
    assert len(SAMPLES) == 9
    assert len(SAMPLES) * 2 == MAX_REQUESTS == 18


def test_ai_tr_002_worst_case_reservation_fits_approved_budget():
    reserved = maximum_reserved_cost_usd(
        request_count=MAX_REQUESTS,
        max_request_bytes=MAX_REQUEST_BYTES,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        input_price_per_million=0.14,
        output_price_per_million=0.28,
    )

    assert reserved == 0.031248
    assert reserved <= MAX_BUDGET_USD


def test_ai_tr_002_records_first_variant_failure_without_continuing():
    failure = OfflineVariantError(
        "invalid aligned JSON", thinking_mode="production_baseline", latency_ms=123,
        usage={"prompt_tokens": 50}, estimated_cost_usd=0.00001,
    )
    with patch("scripts.run_ai_tr_002.run_review", side_effect=failure) as mocked:
        report = run_experiment(execute=True)

    assert mocked.call_count == 1
    assert report["attempted_requests"] == 1
    assert report["decision"] == "REPEAT"
    assert report["failure"]["thinking_mode"] == "production_baseline"

# -*- coding: utf-8 -*-
"""Unit tests for the fixed-scope AI-TR-003 contract diagnostic.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-07-29 | Codex | 验证 JSON 契约诊断的预算预留和 dry-run 无网络边界 |
"""

import sys
from pathlib import Path
from unittest.mock import patch

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.run_ai_tr_003 import (  # noqa: E402
    MAX_BUDGET_USD,
    MAX_OUTPUT_TOKENS,
    MAX_REQUEST_BYTES,
    MAX_REQUESTS,
    SAMPLES,
    maximum_reserved_cost_usd,
    run_experiment,
)
from scripts.deepseek_thinking_ab_review import OfflineRequestError  # noqa: E402
from scripts.run_ai_tr_003 import _failure_record  # noqa: E402


def test_ai_tr_003_has_exactly_the_approved_request_count_and_budget():
    reserved = maximum_reserved_cost_usd(
        request_count=MAX_REQUESTS,
        max_request_bytes=MAX_REQUEST_BYTES,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        input_price_per_million=0.14,
        output_price_per_million=0.28,
    )

    assert len(SAMPLES) == 2
    assert len(SAMPLES) * 2 == MAX_REQUESTS == 4
    assert reserved == 0.004704
    assert reserved <= MAX_BUDGET_USD


def test_ai_tr_003_dry_run_never_calls_api_variant_executor():
    prepared = (
        {"youtube_id": "test", "variants": []},
        {
            "source_texts": ["Hello"],
            "context_text": "",
            "quality_context": None,
            "model": "test",
            "contracts": ["baseline", "json_object"],
        },
    )
    with patch("scripts.run_ai_tr_003._prepare_sample", return_value=prepared) as prepare, patch(
        "scripts.run_ai_tr_003.execute_output_contract_variant"
    ) as execute_variant:
        report = run_experiment(execute=False)

    assert prepare.call_count == 2
    execute_variant.assert_not_called()
    assert report["mode"] == "dry_run"
    assert report["attempted_requests"] == 0
    assert report["decision"] == "DRY_RUN_ONLY"


def test_ai_tr_003_does_not_mislabel_network_failure_as_http_error():
    failure = _failure_record(
        OfflineRequestError("network unavailable"),
        domain="finance", youtube_id="sample", output_contract="baseline",
    )

    assert failure["status_code"] is None
    assert failure["failure_classification"] == "UNKNOWN"

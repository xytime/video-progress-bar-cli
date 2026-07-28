# -*- coding: utf-8 -*-
"""AI-SF-001 黄金样本 schema 和冻结规则测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-07-29 | Codex | 覆盖无敏感正文模板、标签枚举和冻结配额验证 |
"""

import copy
import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.validate_ai_sf_manifest import load_json, validate_manifest  # noqa: E402


SCHEMA_PATH = _repo_root / "docs" / "schemas" / "ai_safety_golden_manifest.schema.json"
EXAMPLE_PATH = _repo_root / "docs" / "schemas" / "ai_safety_golden_manifest.example.json"


def _sample(sample_id: str, bucket: str, domain: str, decision: str = "ALLOW") -> dict:
    return {
        "sample_id": sample_id,
        "bucket": bucket,
        "domain": domain,
        "source_ref": {
            "source_type": "MANUAL_CASE",
            "local_reference": f"local/{sample_id}",
            "input_sha256": "a" * 64,
            "selection_reason": "Local-only test reference without raw content.",
        },
        "rule_snapshot": {"rules_fingerprint": "b" * 16, "existing_rule_decision": "NO_MATCH"},
        "human_label": {
            "decision": decision,
            "labeler_id": "test-reviewer",
            "reviewed_at": "2026-07-29",
            "rationale_summary": "Test-only label without raw content.",
            "evidence_spans": [] if decision == "ALLOW" else [
                {"field": "subtitle", "start_char": 3, "end_char": 8, "text_sha256": "c" * 64}
            ],
        },
    }


def test_ai_sf_template_schema_is_valid_without_sensitive_samples():
    assert validate_manifest(load_json(EXAMPLE_PATH), load_json(SCHEMA_PATH)) == []


def test_ai_sf_schema_rejects_raw_content_and_block_without_evidence():
    manifest = load_json(EXAMPLE_PATH)
    sample = _sample("SF-0001", "RULE_HIT", "mixed", decision="BLOCK")
    sample["human_label"]["evidence_spans"] = []
    sample["raw_text"] = "must never appear in a manifest"
    manifest["samples"] = [sample]

    errors = validate_manifest(manifest, load_json(SCHEMA_PATH))

    assert any("raw_text" in error for error in errors)
    assert any("evidence_spans" in error for error in errors)


def test_ai_sf_frozen_manifest_requires_all_buckets_and_allow_domains():
    manifest = load_json(EXAMPLE_PATH)
    manifest["state"] = "FROZEN"
    manifest["samples"] = [_sample("SF-0001", "RULE_HIT", "mixed", decision="BLOCK")]

    errors = validate_manifest(manifest, load_json(SCHEMA_PATH))

    assert any("RULE_HIT_HUMAN_ALLOW" in error for error in errors)
    assert any("PUBLISHED_ALLOW ALLOW samples missing domains" in error for error in errors)


def test_ai_sf_frozen_manifest_accepts_required_buckets_and_domains():
    manifest = copy.deepcopy(load_json(EXAMPLE_PATH))
    manifest["state"] = "FROZEN"
    manifest["samples"] = [
        _sample("SF-0001", "RULE_HIT", "mixed", decision="BLOCK"),
        _sample("SF-0002", "PUBLISHED_ALLOW", "finance"),
        _sample("SF-0003", "PUBLISHED_ALLOW", "technology"),
        _sample("SF-0004", "PUBLISHED_ALLOW", "education"),
        _sample("SF-0005", "RULE_HIT_HUMAN_ALLOW", "mixed"),
        _sample("SF-0006", "CONTEXTUAL_VARIANT", "mixed", decision="REVIEW"),
    ]

    assert validate_manifest(manifest, load_json(SCHEMA_PATH)) == []

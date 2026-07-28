#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 AI-SF-001 本地黄金样本 manifest。

该工具只读取 JSON schema 与本地 manifest，不访问 PipelineDB、模型、浏览器或发布流程。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-07-29 | Codex | 校验 AI-SF-001 schema、冻结配额和证据定位的本地数据合同 |
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft202012Validator, FormatChecker


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_PATH = _PROJECT_ROOT / "docs" / "schemas" / "ai_safety_golden_manifest.schema.json"
_REQUIRED_BUCKETS = {"RULE_HIT", "PUBLISHED_ALLOW", "RULE_HIT_HUMAN_ALLOW", "CONTEXTUAL_VARIANT"}
_REQUIRED_PUBLISHED_ALLOW_DOMAINS = {"finance", "technology", "education"}


def load_json(path: Path) -> Dict[str, Any]:
    """读取 JSON 对象；损坏或非对象输入由调用方作为验证错误处理。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def validate_manifest(manifest: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    """返回稳定排序的结构与冻结语义错误，不修改输入或外部状态。"""
    errors = [
        f"schema:{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest)
    ]
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        return sorted(errors)

    sample_ids = [sample.get("sample_id") for sample in samples if isinstance(sample, dict)]
    duplicates = sorted({sample_id for sample_id in sample_ids if sample_id and sample_ids.count(sample_id) > 1})
    errors.extend(f"semantic:duplicate sample_id: {sample_id}" for sample_id in duplicates)

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        label = sample.get("human_label")
        if not isinstance(label, dict):
            continue
        for span in label.get("evidence_spans", []):
            if isinstance(span, dict) and span.get("end_char", 0) <= span.get("start_char", 0):
                errors.append(f"semantic:{sample.get('sample_id', '<unknown>')}: evidence span end_char must exceed start_char")

    if manifest.get("state") == "FROZEN":
        requirements = manifest.get("required_buckets")
        minimums = {
            item.get("bucket"): item.get("minimum_samples")
            for item in requirements if isinstance(item, dict)
        } if isinstance(requirements, list) else {}
        if set(minimums) != _REQUIRED_BUCKETS or len(minimums) != len(_REQUIRED_BUCKETS):
            errors.append("semantic:FROZEN required_buckets must declare each of the four source buckets exactly once")
        buckets = Counter(sample.get("bucket") for sample in samples if isinstance(sample, dict))
        for bucket, minimum in sorted(minimums.items()):
            if buckets.get(bucket, 0) < minimum:
                errors.append(f"semantic:FROZEN requires {minimum} {bucket} samples; found {buckets.get(bucket, 0)}")
        published_allow_domains = {
            sample.get("domain") for sample in samples
            if isinstance(sample, dict)
            and sample.get("bucket") == "PUBLISHED_ALLOW"
            and isinstance(sample.get("human_label"), dict)
            and sample["human_label"].get("decision") == "ALLOW"
        }
        missing_domains = sorted(_REQUIRED_PUBLISHED_ALLOW_DOMAINS - published_allow_domains)
        if missing_domains:
            errors.append(f"semantic:FROZEN PUBLISHED_ALLOW ALLOW samples missing domains: {', '.join(missing_domains)}")
    return sorted(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an AI-SF-001 local golden sample manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    args = parser.parse_args()
    errors = validate_manifest(load_json(args.manifest), load_json(args.schema))
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

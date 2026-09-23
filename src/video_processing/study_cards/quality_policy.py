"""语言质量提示与内容安全分开；策略随新时间线冻结，不追认历史产物。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-24 | Codex | 按用户授权将语言质量降为提示，安全审核仍由独立安全门决定。 |
"""

ADVISORY_POLICY = "english-world-quality-advisory-v1"


def advisory_quality(value):
    policy = value.get("quality_policy")
    if policy not in (None, ADVISORY_POLICY):
        raise ValueError("未知英语世界质量策略")
    return policy == ADVISORY_POLICY


def quality_findings(result):
    return [finding for finding in result["findings"]
            if finding["status"] != "PASS" or finding["severity"] in {"P0", "P1"}]


def quality_receipt(result, plan):
    """宿主放行不等于模型无异议；原始问题、严重度和数量均如实保留。"""
    if not advisory_quality(plan):
        return {}
    findings = quality_findings(result)
    return {"quality_policy": ADVISORY_POLICY,
            "review_state": "FAIL" if findings else "PASS",
            "quality_warnings": findings}

"""语言审校的纯协议与指纹；供审校器及证据验证器单向依赖。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 从 language_qa 原样提取协议，避免验证分支反向依赖。 |
"""
import hashlib
import json
from pathlib import Path
from .quality_policy import advisory_quality, quality_findings

CHECKS = ("TRANSCRIPT_ACCURACY", "TRANSLATION_ACCURACY", "VOCAB_POS",
          "VOCAB_CONTEXT_MEANING", "PROPER_NOUNS_NUMBERS", "SEMANTIC_CONSISTENCY",
          "VOCAB_PRONUNCIATION")
VERSION = "english-world-language-v1"
MODEL = "gemini-3.8-flash-high"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    import os
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def review_schema():
    item = {"type": "object", "additionalProperties": False,
            "required": ["check", "target", "status", "severity", "evidence", "suggestion"],
            "properties": {"check": {"type": "string", "enum": list(CHECKS)},
                           "target": {"type": "string"},
                           "status": {"type": "string", "enum": ["PASS", "FAIL", "UNCERTAIN"]},
                           "severity": {"type": "string", "enum": ["NONE", "P0", "P1", "P2"]},
                           "evidence": {"type": "string", "minLength": 1},
                           "suggestion": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["findings"],
            "properties": {"findings": {"type": "array", "items": item}}}


def task_identity(evidence):
    """同一来源的不同自然片段不能共享修订和尝试预算。"""
    fields = ("source_sha256", "caption_sha256", "source_start", "source_end")
    if not isinstance(evidence, dict) or any(not evidence.get(field) for field in fields[:2]):
        raise ValueError("任务身份缺少来源或字幕指纹")
    start, end = evidence["source_start"], evidence["source_end"]
    if isinstance(start, bool) or isinstance(end, bool) or not all(isinstance(value, (int, float)) for value in (start, end)) or end <= start:
        raise ValueError("任务身份缺少有效来源区间")
    return digest({"contract": VERSION, "source_sha256": evidence["source_sha256"],
                   "caption_sha256": evidence["caption_sha256"],
                   "source_start": start, "source_end": end})


def expected_checks(plan, evidence=None, editorial=None):
    expected = set() if plan.get("scope") == "publication" else {(check, "document") for check in CHECKS}
    for index, _ in enumerate(plan["content"]["paragraphs"]):
        expected |= {(check, f"paragraph:{index}") for check in CHECKS[:2] + (CHECKS[4],)}
    for item in plan["content"]["vocabulary"]:
        expected |= {(check, item["item_id"]) for check in (CHECKS[2], CHECKS[3], CHECKS[6])}
    for field in plan.get("publication_text", {}):
        expected |= {(check, f"publication:{field}") for check in (CHECKS[1], CHECKS[4], CHECKS[5])}
    if "presentation_text" in plan:
        expected.add((CHECKS[5], "presentation_text"))
    for i, _ in enumerate(plan.get("publication_text", {}).get("cover_payload", {}).get("vocab_items", [])):
        expected |= {(check, f"cover_word:{i}") for check in (CHECKS[2], CHECKS[3], CHECKS[6])}
    if plan.get("scope") != "publication" and isinstance(evidence, dict):
        for family in ("caption_differences", "timeline_differences"):
            differences = evidence.get(family, [])
            if not isinstance(differences, list):
                raise ValueError(f"{family} 必须是差异列表")
            expected |= {(CHECKS[0], f"{family}:{index}") for index, _ in enumerate(differences)}
        timing_repairs = evidence.get("asr_timing_repairs", [])
        if not isinstance(timing_repairs, list):
            raise ValueError("asr_timing_repairs 必须是列表")
        expected |= {(CHECKS[0], f"asr_timing_repair:{index}") for index, _ in enumerate(timing_repairs)}
    if plan.get("scope") != "publication" and isinstance(editorial, dict):
        changes = editorial.get("changes", [])
        if not isinstance(changes, list):
            raise ValueError("editorial_changes.changes 必须是列表")
        expected |= {(CHECKS[5], f"editorial_change:{index}") for index, _ in enumerate(changes)}
    return expected


def evaluate(result, plan, *, evidence=None, editorial=None):
    import jsonschema
    jsonschema.validate(result, review_schema())
    required = expected_checks(plan, evidence, editorial)
    found = [(x["check"], x["target"]) for x in result["findings"]]
    if set(found) != required or len(found) != len(required):
        raise ValueError("语言审校覆盖缺失、重复或目标不匹配")
    for x in result["findings"]:
        if not x["evidence"].strip():
            raise ValueError("语言审校缺少证据")
    # 只改变完整语言报告的生产判定；敏感内容仍须经过独立安全门。
    if advisory_quality(plan):
        return "PASS"
    return "FAIL" if quality_findings(result) else "PASS"


def apply_adjudications(result, adjudications):
    """只允许有证据的 P1 误报裁决；P0 或内容失败不可人工改成通过。"""
    if not isinstance(adjudications, list) or not adjudications:
        raise ValueError("语言裁决必须是非空列表")
    from copy import deepcopy
    effective = deepcopy(result)
    seen = set()
    findings = {(item["check"], item["target"]): item for item in effective["findings"]}
    if len(findings) != len(effective["findings"]):
        raise ValueError("语言审校结果存在重复目标，不能裁决")
    for adjudication in adjudications:
        required = ("check", "target", "from_status", "from_severity", "decision", "reason", "source_url")
        if any(not adjudication.get(field) for field in required):
            raise ValueError("语言裁决缺少完整证据字段")
        key = (adjudication["check"], adjudication["target"])
        if key in seen or key not in findings:
            raise ValueError("语言裁决目标重复或不存在")
        seen.add(key)
        finding = findings[key]
        if (adjudication["decision"] != "OVERRULE_P1_FALSE_POSITIVE"
                or adjudication["from_status"] != "FAIL" or adjudication["from_severity"] != "P1"
                or finding["status"] != "FAIL" or finding["severity"] != "P1"):
            raise ValueError("仅可裁决独立审校明确标记的 P1 误报")
        if not adjudication["source_url"].startswith(("https://", "http://")):
            raise ValueError("语言裁决必须提供可追溯来源 URL")
        finding["status"], finding["severity"] = "PASS", "NONE"
    return effective


def review_input(plan, evidence, editorial, *, projection="compact-v1"):
    """排除路径、原始大候选池和生成器自评；保留所有实际展示内容。"""
    semantic_plan = {k: v for k, v in plan.items() if k != "timeline_sha256"}
    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if k not in {"confidence", "self_score", "self_review"}}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value
    value = {"audience": "A2-B1 family learners", "plan": scrub(semantic_plan),
             "source_evidence": evidence, "editorial_changes": editorial,
             "required_checks": [list(x) for x in sorted(expected_checks(plan, evidence, editorial))]}
    if projection == "legacy":
        return value
    if projection != "compact-v1":
        raise ValueError("未知审校输入版本")
    from copy import deepcopy
    value = deepcopy(value)
    value["projection"] = projection
    value["evidence_sha256"] = digest(evidence)
    value["semantic_plan_sha256"] = digest(value["plan"])
    content = value["plan"]["content"]
    for key in ("english_text", "translation_zh", "vocabulary_candidates"):
        content.pop(key, None)  # 本地已验证全文与逐段完全相同
    if "words" in content:
        content["words"] = [[w["text"], w["start"], w["end"]] for w in content["words"]]
    for point in value["plan"].get("learning_evidence", []):
        for field in ("word", "pos", "context_meaning_zh", "phonetic", "level"):
            point.pop(field, None)  # 同一 item 已在最终 vocabulary 中提供
    source = value["source_evidence"]
    source.pop("asr_words", None)  # 留存本地；审校收到全文、差异、修复依据与完整证据指纹
    source.pop("asr_words_raw", None)
    for key in ("words", "segments"):
        source.get("parsed", {}).pop(key, None)
    return value


def cache_key(inputs, model=MODEL, effort=None):
    payload = {"inputs": inputs, "model": model, "prompt": VERSION,
               "schema": review_schema(), "rules": VERSION}
    if effort is not None:
        payload["effort"] = effort
    return digest(payload)

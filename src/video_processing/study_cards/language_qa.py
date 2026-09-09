"""独立审校协议、内容指纹与失败关闭判定；不依赖外层脚本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 七项覆盖门禁、路径无关缓存键和绑定校验。 |
"""
import hashlib
import json
from pathlib import Path

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


def expected_checks(plan):
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
    return expected


def evaluate(result, plan):
    import jsonschema
    jsonschema.validate(result, review_schema())
    required = expected_checks(plan)
    found = [(x["check"], x["target"]) for x in result["findings"]]
    if set(found) != required or len(found) != len(required):
        raise ValueError("语言审校覆盖缺失、重复或目标不匹配")
    for x in result["findings"]:
        if not x["evidence"].strip():
            raise ValueError("语言审校缺少证据")
        if x["status"] != "PASS" or x["severity"] in {"P0", "P1"}:
            return "FAIL"
    return "PASS"


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
             "required_checks": [list(x) for x in sorted(expected_checks(plan))]}
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
    for key in ("words", "segments"):
        source.get("parsed", {}).pop(key, None)
    return value


def cache_key(inputs, model=MODEL):
    return digest({"inputs": inputs, "model": model, "prompt": VERSION,
                   "schema": review_schema(), "rules": VERSION})


def validate_language_qa(timeline, *, manifest=None, required=True):
    """绝不把旧产物自动盖章；所有 v2 输入即使影子期开关关闭也验证。"""
    timeline = Path(timeline).expanduser().resolve()
    payload = read_json(timeline)
    if not required and payload.get("language_contract") != VERSION:
        return None
    root = timeline.parent
    report = read_json(root / "qa/language_qa.json")
    plan = read_json(root / "display_plan.json")
    if report.get("version") != VERSION or report.get("state") != "PASS":
        raise ValueError("语言审校未通过")
    if report.get("timeline_sha256") != file_digest(timeline) or report.get("plan_sha256") != digest(plan):
        raise ValueError("语言审校文件绑定失效")
    evidence = read_json(root / "qa/source_evidence.json")
    editorial = read_json(root / "editorial_changes.json")
    if report.get("input_key") != cache_key(review_input(plan, evidence, editorial, projection=report.get("input_projection", "legacy")), report["model"]):
        raise ValueError("来源或编辑证据已经变化")
    if evaluate(report["result"], plan) != "PASS":
        raise ValueError("语言审校存在未解决问题")
    provenance = payload["source_provenance"]
    if evidence.get("source_start") != provenance["source_start_seconds"] or evidence.get("source_end") != provenance["source_end_seconds"]:
        raise ValueError("来源证据区间与时间线不一致")
    source = Path(provenance.get("source_video", root / "source/source.mp4"))
    if not source.is_absolute():
        source = root / source
    caption = root / provenance["caption_artifact"]
    if file_digest(source) != evidence["source_sha256"] or file_digest(caption) != evidence["caption_sha256"]:
        raise ValueError("源视频或字幕已经变化")
    if manifest is not None:
        value = read_json(manifest)
        if value.get("display_plan_sha256") != digest(plan):
            raise ValueError("成片与已审校展示计划不匹配")
        if value.get("language_qa_sha256") != file_digest(root / "qa/language_qa.json"):
            raise ValueError("成片与语言审校报告不匹配")
    return report


def validate_publication(item):
    """封装/提交复用相同文本；新文本必须重审，不继承正文 PASS。"""
    from config.settings import settings
    manifest = read_json(item["manifest_path"])
    if not settings.enable_english_world_language_qa and manifest.get("language_contract") != VERSION:
        return
    timeline = Path(manifest["timeline"])
    validate_language_qa(timeline, manifest=Path(item["manifest_path"]))
    from .publication_qa import approved_publication
    approved, supplement = approved_publication(timeline)
    for key in ("title", "copy"):
        if Path(item[key + "_path"]).read_text(encoding="utf-8") != approved[key]:
            raise ValueError(f"投稿 {key} 与独立审校文本不一致，需要重新审校")
    cover_payload = Path(item["cover_path"]).parent / "cover_payload.json"
    if digest(read_json(cover_payload)) != digest(approved["cover_payload"]):
        raise ValueError("实际封面载荷与审校内容不一致")
    if supplement:
        provenance = read_json(item["cover_provenance_path"])
        if provenance.get("language_supplement_sha256") != supplement:
            raise ValueError("投稿包未绑定当前增量文案审校")


def validate_display(timeline, manifest=None):
    """结构检查复算同一计划；不重新选词。音频/关键帧证据仍须另行完成。"""
    from .display_plan import verify_plan
    from .template_a import RecordUnderlineTemplate
    timeline = Path(timeline).expanduser().resolve()
    report = validate_language_qa(timeline, manifest=manifest)
    plan = read_json(timeline.parent / "display_plan.json")
    content = verify_plan(read_json(timeline), plan, file_digest(timeline), RecordUnderlineTemplate())
    if manifest is not None:
        value = read_json(manifest)
        if value.get("word_count") != len(content.words) or digest(value.get("display_screens")) != digest(plan["screens"]):
            raise ValueError("成片逐词或学习屏与计划不同")
        if not 30 < value.get("duration", 0) <= 300 or value.get("speech_end", 0) > value["duration"]:
            raise ValueError("成片时长或语音收尾非法")
    return {"state": report["state"], "screens": plan["screens"], "word_count": len(content.words)}

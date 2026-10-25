"""主机端制作清单合同；仅依赖标准库和 JSON Schema。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 结构、语义、路径和模型字段边界校验 |
"""
from __future__ import annotations
import math
import re
from pathlib import Path
from typing import Any, Dict
from jsonschema import Draft202012Validator

REMIX_MANIFEST_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "id",
        "title",
        "description",
        "cover_title",
        "cover_subtitle",
        "cover_label",
        "category",
        "badge_text",
        "keywords",
        "content_hints",
        "chapters",
        "cards",
        "comparison_table",
    ],
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "cover_title": {"type": "string"},
        "cover_subtitle": {"type": "string"},
        "cover_label": {"type": "string"},
        "category": {"type": "string"},
        "badge_text": {"type": "string"},
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
        },
        "content_hints": {
            "type": "array",
            "items": {"type": "string"},
        },
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "text", "clauses"],
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                    "clauses": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": ["string", "number"]},
                        },
                    },
                },
            },
        },
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "filename",
                    "tag",
                    "title",
                    "col1_lbl",
                    "col1_val",
                    "col2_lbl",
                    "col2_val",
                    "note",
                    "start_time",
                    "end_time",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "filename": {"type": "string"},
                    "tag": {"type": "string"},
                    "title": {"type": "string"},
                    "col1_lbl": {"type": "string"},
                    "col1_val": {"type": "string"},
                    "col2_lbl": {"type": "string"},
                    "col2_val": {"type": "string"},
                    "note": {"type": "string"},
                    "start_time": {"type": "number"},
                    "end_time": {"type": "number"},
                },
            },
        },
        "comparison_table": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "timestamp_range",
                    "source_english_gist",
                    "remix_chinese_commentary",
                    "reframing_rationale",
                ],
                "properties": {
                    "timestamp_range": {"type": "string"},
                    "source_english_gist": {"type": "string"},
                    "remix_chinese_commentary": {"type": "string"},
                    "reframing_rationale": {"type": "string"},
                },
            },
        },
    },
}


# 模型只输出这些字段；服务可以在验证后添加可信审批/来源扩展。
REMIX_MANIFEST_SCHEMA["required"].append("raw_shots")
REMIX_MANIFEST_SCHEMA["properties"]["raw_shots"] = {"type": "array", "minItems": 1, "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"}}}
def _close_objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "string":
            schema["maxLength"] = 4000
        if schema.get("type") == "array":
            schema.setdefault("maxItems", 64)
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
        for value in list(schema.values()):
            _close_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            _close_objects(value)

_close_objects(REMIX_MANIFEST_SCHEMA)
REMIX_MANIFEST_SCHEMA["properties"]["cover_title"].update(minLength=6, maxLength=16)
REMIX_MANIFEST_SCHEMA["properties"]["chapters"]["maxItems"] = 16
REMIX_MANIFEST_SCHEMA["properties"]["cards"]["maxItems"] = 16
REMIX_MANIFEST_SCHEMA["properties"]["chapters"]["items"]["properties"]["clauses"]["maxItems"] = 32
MODEL_FIELDS = frozenset(REMIX_MANIFEST_SCHEMA["properties"])

def validate_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("unsafe identifier")
    return value

def safe_card_path(directory, filename):
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.png", filename):
        raise ValueError("unsafe card filename")
    root = Path(directory).resolve()
    target = (root / filename).resolve()
    if target.parent != root:
        raise ValueError("card escapes output directory")
    return target

def _number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError("invalid finite duration/time")
    return value

def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be object")
    error = next(Draft202012Validator(REMIX_MANIFEST_SCHEMA).iter_errors({key: value for key, value in manifest.items() if key in MODEL_FIELDS}), None)
    if error is not None:
        raise ValueError("manifest schema: " + error.message)
    validate_identifier(manifest["id"])
    for key in ("title", "description", "cover_title", "cover_subtitle", "cover_label", "category", "badge_text"):
        if not manifest[key].strip():
            raise ValueError("empty metadata: " + key)
    for key in ("keywords", "content_hints"):
        if any(not item.strip() for item in manifest[key]):
            raise ValueError("empty metadata item")
    if not manifest["chapters"] or not manifest["comparison_table"]:
        raise ValueError("chapters and source comparison evidence required")
    indices=set(); total=0
    for chapter in manifest["chapters"]:
        index=chapter["index"]
        if isinstance(index, bool) or index <= 0 or index in indices:
            raise ValueError("chapter indices must be unique positive integers")
        indices.add(index)
        if not chapter["clauses"]:
            raise ValueError("empty clauses")
        pieces=[]
        for clause in chapter["clauses"]:
            if len(clause) != 2 or not isinstance(clause[0], str) or not clause[0].strip():
                raise ValueError("clause must be [text, duration]")
            pieces.append(clause[0]); total += _number(clause[1], True)
        if "".join(pieces) != chapter["text"]:
            raise ValueError("chapter text does not match spoken clauses")
    if total > 1800 or sum(len(c["text"]) for c in manifest["chapters"]) > 20000:
        raise ValueError("narration exceeds resource budget")
    if "".join(row["remix_chinese_commentary"] for row in manifest["comparison_table"]) != "".join(chapter["text"] for chapter in manifest["chapters"]):
        raise ValueError("comparison must cover complete narration in order")
    names=set(); ids=set()
    for card in manifest["cards"]:
        validate_identifier(card["id"]); safe_card_path(Path.cwd(), card["filename"])
        if card["id"] in ids or card["filename"] in names:
            raise ValueError("duplicate card")
        ids.add(card["id"]); names.add(card["filename"])
        if not _number(card["start_time"]) < _number(card["end_time"], True) <= total:
            raise ValueError("card timing outside narration")
    for shot in manifest["raw_shots"]:
        _number(shot[0]); _number(shot[1], True)
        if shot[0] > 86400 or shot[1] > 1800:
            raise ValueError("shot exceeds resource budget")
    for row in manifest["comparison_table"]:
        if any(not row[key].strip() for key in ("timestamp_range", "source_english_gist", "remix_chinese_commentary", "reframing_rationale")):
            raise ValueError("empty comparison evidence")
        match=re.fullmatch(r"(\d{1,3}):([0-5]\d)(?::([0-5]\d))?\s*[-–]\s*(\d{1,3}):([0-5]\d)(?::([0-5]\d))?", row["timestamp_range"])
        if not match:
            raise ValueError("comparison evidence requires timestamp range")
        a,b,c,d,e,f=match.groups()
        start=int(a)*60+int(b) if c is None else int(a)*3600+int(b)*60+int(c)
        end=int(d)*60+int(e) if f is None else int(d)*3600+int(e)*60+int(f)
        if end <= start:
            raise ValueError("invalid comparison timestamp range")
    return manifest

def validate_model_manifest(manifest):
    validate_manifest(manifest)
    if set(manifest) != MODEL_FIELDS:
        raise ValueError("model emitted trusted/unknown fields")
    return manifest

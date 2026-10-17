"""封面来源契约：生成证据、投稿快照与统一展示。

# Modification History
| Version | Date | Author | Description |
| 1.0 | 2026-10-15 | Codex | 以内容哈希绑定生成来源与投稿快照；缺证据明确未知。 |
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

LABELS = {"antigravity_ai_visual": "Antigravity", "codex_luna_ai_visual": "Codex 接力",
          "codex_ai_visual": "Codex", "deterministic_fallback": "默认封面", "unknown": "来源未核验"}

def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def canonical(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def version(value: dict) -> dict:
    value = dict(value)
    value.pop("version_id", None)
    value["version_id"] = hashlib.sha256(canonical(value).encode()).hexdigest()
    return value

def presentation(value: dict | None = None) -> dict:
    value = dict(value or {})
    source = value.get("source", "unknown")
    if source not in LABELS:
        source = "unknown"
    return {**value, "source": source, "label": LABELS[source],
            "degraded": source == "deterministic_fallback",
            "verified": source != "unknown"}

def source_path(cover: Path) -> Path:
    return cover.with_name(cover.stem + "_source.json")

def generation_record(task, resolution: dict) -> dict:
    handoff = resolution.get("luna_handoff") or {}
    result = read_json(task.finish_dir / "result.json")
    return version({"schema_version": 1, "task_id": task.task_id,
        "youtube_id": task.payload["youtube_id"], "slice_index": task.payload.get("slice_index", 0),
        "source": resolution["source"], "cover_sha256": resolution["cover_sha256"],
        "generated_at": resolution["resolved_at"], "handoff_reason": handoff.get("reason"),
        "fallback_reason": resolution.get("fallback_reason"),
        "agy_error": read_json(task.finish_dir / "antigravity_attempt.json").get("error"),
        "codex_error": read_json(task.finish_dir / "luna_attempt.json").get("error"),
        "quality_review": result.get("quality_review"), "generated_by": result.get("generated_by"),
        "image_model": result.get("image_model"), "orchestrator_model": result.get("model")})

def freeze_submission(cover: Path, evidence: Path) -> Path:
    """上传冻结后的字节；相同 evidence 目录重入也不能改写历史版本。"""
    evidence.mkdir(parents=True, exist_ok=True)
    receipt = evidence / "cover_binding.json"
    target = evidence / "submitted_cover.jpg"
    if receipt.exists():
        old = read_json(receipt)
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != old.get("cover_sha256"):
            raise ValueError("Frozen submission cover integrity failure")
        if hashlib.sha256(cover.read_bytes()).hexdigest() != old.get("cover_sha256"):
            raise ValueError("Submission evidence already belongs to a different cover")
        return target
    data = cover.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    value = read_json(source_path(cover))
    if value.get("cover_sha256") != digest or version(value).get("version_id") != value.get("version_id"):
        value = version({"schema_version": 1, "source": "unknown", "cover_sha256": digest})
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    temporary = receipt.with_suffix(".tmp")
    temporary.write_text(canonical(value), encoding="utf-8")
    temporary.replace(receipt)
    return target

def notification_text(value: dict) -> str:
    value = presentation(value)
    parts = ["封面来源：" + value["label"], "退化：" + ("是" if value["degraded"] else ("否" if value["verified"] else "未核验"))]
    if value.get("submission_binding") == "UNKNOWN":
        parts.append("封面投稿绑定：未取得平台提交证明；以上仅为生成来源")
    for key, label in (("handoff_reason", "接力原因"), ("fallback_reason", "兜底原因"), ("agy_error", "AGY 失败"), ("codex_error", "Codex 失败"), ("cover_sha256", "封面 SHA256"), ("version_id", "封面版本")):
        if value.get(key):
            parts.append(label + "：" + str(value[key]))
    return "\n".join(parts)

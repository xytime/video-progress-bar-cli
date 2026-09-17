"""英语世界短视频的独立安全门。

本模块只检查已固定的文本与视觉审核回执，不下载媒体、不调用模型，也不接触
账本或平台。它刻意不复用 ``CensorshipService``：后者包含通用流水线的账本、
人工复核和受信频道路径；英语世界交付必须由无旁路的纯规则检查决定。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-09-17 | Antigravity | 排除词典全量定义非展示字段，并按中英语言分流成片待审文本，消除英文子串误触发中文 CIA 及未选中义项误杀。 |
| 1.2.0 | 2026-09-17 | Codex | 复用研究域来源硬排除词表，在候选安全门双重拒绝政治、冲突与成人等题材。 |
| 1.1.0 | 2026-09-17 | Codex | 将视觉联系表文件与哈希一并绑定到当前时间线，拒绝伪造或遗留图片回执。 |
| 1.0.0 | 2026-09-17 | Codex | 新增英语世界候选与成片双阶段、fail-closed 的文本/频道策略安全门及可绑定回执。 |
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from video_processing.censor_engine import (
    CensorResult,
    check_channel_policy,
    check_text,
    current_rules_fingerprint,
    scan_all_matches,
)
from video_processing.english_world.research import HARD_BLOCKED_TERMS
from video_processing.english_world.package_integrity import sha256_file


VERSION = "english-world-safety-v1"
VISUAL_REVIEW_VERSION = "english-world-visual-safety-v1"
AGY_HIGH_EFFORT_MODEL = "gemini-3.8-flash-high"


class EnglishWorldSafetyGateError(ValueError):
    """安全门未通过、输入不完整或回执不再绑定时抛出。"""


@dataclass(frozen=True)
class SafetyDocument:
    """一个必须独立留痕的双语检查面。"""

    name: str
    zh_text: str = ""
    en_text: str = ""


def _result_payload(result: CensorResult) -> dict[str, Any]:
    return asdict(result)


def _source_policy_result(en_text: str) -> dict[str, Any]:
    """复用候选研究的硬排除词，作为成片前不可绕过的第二道来源门。"""
    normalized = en_text.casefold()
    matched = next((term for term in sorted(HARD_BLOCKED_TERMS)
                    if re.search(rf"\b{re.escape(term)}\b", normalized)), None)
    return {
        "hit": matched is not None,
        "level": "SOURCE_POLICY" if matched is not None else None,
        "tag": "英语世界来源题材限制" if matched is not None else None,
        "score": 0,
        "action": "SOURCE_REJECT" if matched is not None else None,
        "matched": matched,
        "channel": "en" if matched is not None else None,
    }


def _document_digest(documents: list[SafetyDocument]) -> str:
    payload = [asdict(document) for document in documents]
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _document_receipt(document: SafetyDocument) -> dict[str, Any]:
    """回执只保留文本长度与哈希，避免另存一份完整字幕/文案。"""
    return {
        "name": document.name,
        "zh_chars": len(document.zh_text),
        "en_chars": len(document.en_text),
        "zh_sha256": sha256(document.zh_text.encode("utf-8")).hexdigest(),
        "en_sha256": sha256(document.en_text.encode("utf-8")).hexdigest(),
    }


def _require_text(documents: list[SafetyDocument]) -> None:
    if not documents:
        raise EnglishWorldSafetyGateError("安全门没有任何检查输入")
    for document in documents:
        if not document.name.strip() or not (document.zh_text.strip() or document.en_text.strip()):
            raise EnglishWorldSafetyGateError("安全门缺少必需的文本证据")


def _validate_visual_review(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """验证视觉审核已绑定 contact sheet，而不是接受模型口头结论。"""
    if not isinstance(value, Mapping):
        raise EnglishWorldSafetyGateError("缺少视觉安全审核回执")
    required = (
        "version", "state", "provider", "model", "effort", "contact_sheet",
        "contact_sheet_sha256", "mp4_sha256", "risk_categories",
    )
    if any(
        field not in value
        or value.get(field) is None
        or (isinstance(value.get(field), str) and not value[field].strip())
        for field in required
    ):
        raise EnglishWorldSafetyGateError("视觉安全审核回执字段不完整")
    if str(value["state"]) != "PASS" or str(value["provider"]).lower() != "agy":
        raise EnglishWorldSafetyGateError("视觉安全审核未通过")
    if str(value["version"]) != VISUAL_REVIEW_VERSION:
        raise EnglishWorldSafetyGateError("视觉安全审核版本无效")
    if str(value["model"]) != AGY_HIGH_EFFORT_MODEL:
        raise EnglishWorldSafetyGateError("视觉安全审核模型不符合当前 high-effort 基线")
    if str(value["effort"]).lower() != "high":
        raise EnglishWorldSafetyGateError("视觉安全审核必须使用 AGY high effort")
    if not isinstance(value["risk_categories"], list) or value["risk_categories"]:
        raise EnglishWorldSafetyGateError("视觉安全审核存在风险分类或格式无效")
    for field, label in (("contact_sheet_sha256", "contact sheet"), ("mp4_sha256", "MP4")):
        digest = str(value[field]).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise EnglishWorldSafetyGateError(f"视觉安全审核缺少有效 {label} 指纹")
    normalized = {field: str(value[field]) for field in required if field != "risk_categories"}
    normalized["contact_sheet_sha256"] = normalized["contact_sheet_sha256"].lower()
    normalized["mp4_sha256"] = normalized["mp4_sha256"].lower()
    normalized["risk_categories"] = []
    return normalized


def _validate_contact_sheet_binding(visual_review: Mapping[str, Any], *, timeline: Path) -> Path:
    """联系表只能是当前时间线目录内、仍与视觉回执哈希相同的本地产物。"""
    contact_sheet = Path(visual_review["contact_sheet"]).expanduser().resolve()
    timeline_root = Path(timeline).resolve().parent
    try:
        contact_sheet.relative_to(timeline_root)
    except ValueError as exc:
        raise EnglishWorldSafetyGateError("视觉安全联系表不在当前时间线目录内") from exc
    if not contact_sheet.is_file() or contact_sheet.stat().st_size <= 0:
        raise EnglishWorldSafetyGateError("视觉安全联系表不存在或为空")
    if sha256_file(contact_sheet) != visual_review["contact_sheet_sha256"]:
        raise EnglishWorldSafetyGateError("视觉安全联系表与审核回执内容不一致")
    return contact_sheet


def evaluate(
    stage: str,
    documents: list[SafetyDocument],
    *,
    visual_review: Mapping[str, Any] | None = None,
    require_visual_review: bool = False,
) -> dict[str, Any]:
    """检查所有输入面；任何规则错误、空输入或命中均返回非 PASS 回执。

    返回回执而不立即抛出，使影子运行能够保留失败证据。正式交付方应调用
    :func:`require_pass`，从而在任何非 PASS 状态下拒绝创建交付请求。
    """
    receipt: dict[str, Any] = {
        "version": VERSION,
        "stage": str(stage).strip(),
        "state": "FAIL_CLOSED",
        "documents": [_document_receipt(document) for document in documents],
        "input_sha256": _document_digest(documents),
        "checks": [],
        "audit_matches": [],
    }
    try:
        if not receipt["stage"]:
            raise EnglishWorldSafetyGateError("安全门阶段不能为空")
        _require_text(documents)
        receipt["rules_fingerprint"] = current_rules_fingerprint()
        if require_visual_review:
            receipt["visual_review"] = _validate_visual_review(visual_review)
        elif visual_review is not None:
            receipt["visual_review"] = _validate_visual_review(visual_review)

        blocked = False
        for document in documents:
            censorship = check_text(document.zh_text, document.en_text)
            channel_policy = check_channel_policy(document.zh_text, document.en_text)
            source_policy = _source_policy_result(document.en_text)
            audit_matches = scan_all_matches(document.zh_text, document.en_text)
            receipt["checks"].append({
                "document": document.name,
                "censorship": _result_payload(censorship),
                "channel_policy": _result_payload(channel_policy),
                "source_policy": source_policy,
                "audit_matches": audit_matches,
            })
            receipt["audit_matches"].extend({"document": document.name, **match} for match in audit_matches)
            blocked = blocked or censorship.hit or channel_policy.hit or bool(source_policy["hit"])
        receipt["state"] = "BLOCKED" if blocked else "PASS"
    except Exception as exc:  # fail-closed: rule loader and malformed evidence may never pass silently
        receipt["state"] = "FAIL_CLOSED"
        receipt["failure_kind"] = type(exc).__name__
    return receipt


def require_pass(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """把非 PASS 的安全回执变成不泄露正文的稳定拒绝。"""
    if not isinstance(receipt, Mapping) or receipt.get("version") != VERSION:
        raise EnglishWorldSafetyGateError("安全门回执版本无效")
    if receipt.get("state") != "PASS":
        first_check = next((check for check in receipt.get("checks") or []
                            if check.get("censorship", {}).get("hit")
                            or check.get("channel_policy", {}).get("hit")
                            or check.get("source_policy", {}).get("hit")), {})
        result = next((first_check.get(field, {}) for field in ("censorship", "channel_policy", "source_policy")
                       if first_check.get(field, {}).get("hit")), {})
        level = str(result.get("level") or receipt.get("failure_kind") or "unknown")
        raise EnglishWorldSafetyGateError(f"英语世界安全门未通过：{level}")
    return dict(receipt)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise EnglishWorldSafetyGateError(f"安全门无法读取 JSON：{path.name}") from exc
    if not isinstance(value, dict):
        raise EnglishWorldSafetyGateError(f"安全门 JSON 必须是对象：{path.name}")
    return value


def _join_strings(*values: Any) -> str:
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            result.append(value.strip())
        elif isinstance(value, list):
            result.extend(str(item.get("text") or item.get("word") or "").strip()
                          for item in value if isinstance(item, Mapping))
    return "\n".join(item for item in result if item)


def _content_strings(value: Any, *, field: str = "") -> list[str]:
    """只递归收集用户可见文本，排除路径、hash、模型及离线词典全量定义等非展示字段。"""
    excluded_suffixes = ("_path", "_sha256")
    excluded_fields = {
        "source_video", "caption_artifact", "model", "version", "input_key",
        "dictionary_senses", "dictionary_source", "source_evidence",
    }
    if field in excluded_fields or field.endswith(excluded_suffixes):
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        return [item for key, nested in value.items() for item in _content_strings(nested, field=str(key))]
    if isinstance(value, list):
        return [item for nested in value for item in _content_strings(nested, field=field)]
    return []


def delivery_documents(*, title: str, timeline: Mapping[str, Any], source_evidence: Mapping[str, Any], display_plan: Mapping[str, Any] | None) -> list[SafetyDocument]:
    """提取源英文证据与最终可见文本；缺任一面时由 evaluate fail-closed。"""
    provenance = timeline.get("source_provenance") if isinstance(timeline.get("source_provenance"), Mapping) else {}
    parsed = source_evidence.get("parsed") if isinstance(source_evidence.get("parsed"), Mapping) else {}
    source_text = _join_strings(
        provenance.get("source_title"),
        parsed.get("english_text"),
        source_evidence.get("aligned_caption_text"),
        source_evidence.get("asr_text"),
        source_evidence.get("asr_words"),
    )
    strings = _content_strings({
        "title": title,
        "timeline": timeline,
        "display_plan": display_plan or {},
    })
    zh_text = "\n".join(s for s in strings if re.search(r"[\u4e00-\u9fff]", s))
    en_text = "\n".join(s for s in strings if not re.search(r"[\u4e00-\u9fff]", s))
    return [
        SafetyDocument(name="source_evidence", en_text=source_text),
        SafetyDocument(name="final_delivery", zh_text=zh_text, en_text=en_text),
    ]


def evaluate_delivery(
    *,
    title: str,
    timeline_path: Path,
    visual_review: Mapping[str, Any] | None = None,
    require_visual_review: bool = False,
) -> dict[str, Any]:
    """从已绑定时间线读取成片安全输入；来源证据不存在即失败关闭。"""
    try:
        timeline_path = Path(timeline_path).expanduser().resolve()
        timeline = _read_json(timeline_path)
        source_evidence = _read_json(timeline_path.parent / "qa/source_evidence.json")
        plan_path = timeline_path.parent / "display_plan.json"
        display_plan = _read_json(plan_path) if plan_path.exists() else None
        return evaluate(
            "delivery",
            delivery_documents(title=title, timeline=timeline, source_evidence=source_evidence, display_plan=display_plan),
            visual_review=visual_review,
            require_visual_review=require_visual_review,
        )
    except Exception as exc:  # 文件缺失或格式错误也要留下可判断的 fail-closed 收据
        return {
            "version": VERSION,
            "stage": "delivery",
            "state": "FAIL_CLOSED",
            "documents": [],
            "checks": [],
            "audit_matches": [],
            "failure_kind": type(exc).__name__,
        }


def attach_artifact_binding(receipt: Mapping[str, Any], *, mp4: Path, manifest: Path, timeline: Path) -> dict[str, Any]:
    """把 PASS/失败回执绑定到本次三份不可互换的交付产物。"""
    bound = dict(receipt)
    paths = {"mp4": Path(mp4).resolve(), "manifest": Path(manifest).resolve(), "timeline": Path(timeline).resolve()}
    if any(not path.is_file() or path.stat().st_size <= 0 for path in paths.values()):
        raise EnglishWorldSafetyGateError("安全门绑定产物不存在或为空")
    bound.update({key: str(path) for key, path in paths.items()})
    bound.update({f"{key}_sha256": sha256_file(path) for key, path in paths.items()})
    visual_review = bound.get("visual_review")
    if not isinstance(visual_review, Mapping):
        raise EnglishWorldSafetyGateError("安全门交付回执缺少视觉审核")
    normalized_visual = _validate_visual_review(visual_review)
    if normalized_visual["mp4_sha256"] != bound["mp4_sha256"]:
        raise EnglishWorldSafetyGateError("视觉安全审核未绑定当前 MP4")
    _validate_contact_sheet_binding(normalized_visual, timeline=paths["timeline"])
    bound["visual_review"] = normalized_visual
    evidence = paths["timeline"].parent / "qa/source_evidence.json"
    if not evidence.is_file() or evidence.stat().st_size <= 0:
        raise EnglishWorldSafetyGateError("安全门缺少来源证据文件")
    bound["source_evidence"] = str(evidence.resolve())
    bound["source_evidence_sha256"] = sha256_file(evidence)
    return bound


def validate_delivery_receipt(path: Path, *, mp4: Path, manifest: Path, timeline: Path) -> dict[str, Any]:
    """拒绝旧 PASS、其它视频或未验证视觉审核的安全回执。"""
    receipt = _read_json(Path(path).expanduser().resolve())
    require_pass(receipt)
    if receipt.get("stage") != "delivery":
        raise EnglishWorldSafetyGateError("安全门回执阶段不是 delivery")
    expected = {"mp4": Path(mp4).resolve(), "manifest": Path(manifest).resolve(), "timeline": Path(timeline).resolve()}
    for key, artifact in expected.items():
        if Path(str(receipt.get(key) or "")).resolve() != artifact:
            raise EnglishWorldSafetyGateError(f"安全门回执未绑定当前 {key}")
        if receipt.get(f"{key}_sha256") != sha256_file(artifact):
            raise EnglishWorldSafetyGateError(f"安全门回执与当前 {key} 内容不一致")
    evidence = expected["timeline"].parent / "qa/source_evidence.json"
    if (Path(str(receipt.get("source_evidence") or "")).resolve() != evidence.resolve()
            or receipt.get("source_evidence_sha256") != sha256_file(evidence)):
        raise EnglishWorldSafetyGateError("安全门回执与当前来源证据不一致")
    if not isinstance(receipt.get("visual_review"), Mapping):
        raise EnglishWorldSafetyGateError("安全门交付回执缺少视觉审核")
    visual_review = _validate_visual_review(receipt["visual_review"])
    if visual_review["mp4_sha256"] != receipt.get("mp4_sha256"):
        raise EnglishWorldSafetyGateError("视觉安全审核与当前 MP4 内容不一致")
    _validate_contact_sheet_binding(visual_review, timeline=expected["timeline"])
    return receipt

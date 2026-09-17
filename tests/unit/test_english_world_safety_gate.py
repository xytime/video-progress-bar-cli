"""英语世界独立安全门回归：所有外部规则与文件异常必须 fail-closed。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-09-17 | Codex | 覆盖研究域来源硬排除词在运行时安全门的二次拒绝。 |
| 1.1.0 | 2026-09-17 | Codex | 覆盖视觉联系表存在性、目录边界及哈希重验。 |
| 1.0.0 | 2026-09-17 | Codex | 覆盖双阶段文本/频道阻断、视觉审核绑定、旧回执拒绝和缺证据失败关闭。 |
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

import pytest

from video_processing.censor_engine import CensorResult
from video_processing.english_world import safety_gate


def _pass() -> CensorResult:
    return CensorResult(hit=False)


def _visual_receipt(
    *,
    mp4_sha256: str = "a" * 64,
    contact_sheet: str = "/tmp/contact_sheet.png",
    contact_sheet_sha256: str = "a" * 64,
) -> dict[str, Any]:
    return {
        "version": "english-world-visual-safety-v1",
        "state": "PASS",
        "provider": "agy",
        "model": "gemini-3.8-flash-high",
        "effort": "high",
        "contact_sheet": contact_sheet,
        "contact_sheet_sha256": contact_sheet_sha256,
        "mp4_sha256": mp4_sha256,
        "risk_categories": [],
    }


def _patch_clean_rules(monkeypatch) -> None:
    monkeypatch.setattr(safety_gate, "current_rules_fingerprint", lambda: "rules-test")
    monkeypatch.setattr(safety_gate, "check_text", lambda *_args: _pass())
    monkeypatch.setattr(safety_gate, "check_channel_policy", lambda *_args: _pass())
    monkeypatch.setattr(safety_gate, "scan_all_matches", lambda *_args: [])


def test_gate_blocks_any_p0_or_p2_result_and_never_uses_model_override(monkeypatch):
    _patch_clean_rules(monkeypatch)
    monkeypatch.setattr(
        safety_gate,
        "check_text",
        lambda _zh, en: CensorResult(hit=True, level="P2", tag="风险", matched="unsafe", channel="en")
        if "unsafe" in en else _pass(),
    )
    receipt = safety_gate.evaluate(
        "candidate_preflight",
        [safety_gate.SafetyDocument(name="source", en_text="an unsafe phrase")],
    )

    assert receipt["state"] == "BLOCKED"
    assert receipt["checks"][0]["censorship"]["level"] == "P2"
    assert "an unsafe phrase" not in json.dumps(receipt, ensure_ascii=False)
    with pytest.raises(safety_gate.EnglishWorldSafetyGateError, match="P2"):
        safety_gate.require_pass(receipt)


def test_gate_rechecks_research_hard_blocked_terms_even_when_general_rules_pass(monkeypatch):
    _patch_clean_rules(monkeypatch)

    receipt = safety_gate.evaluate(
        "candidate_preflight",
        [safety_gate.SafetyDocument(name="source", en_text="The tariff situation will change.")],
    )

    assert receipt["state"] == "BLOCKED"
    assert receipt["checks"][0]["source_policy"]["matched"] == "tariff"
    with pytest.raises(safety_gate.EnglishWorldSafetyGateError, match="SOURCE_POLICY"):
        safety_gate.require_pass(receipt)


def test_gate_blocks_channel_policy_and_requires_high_effort_visual_receipt(monkeypatch):
    _patch_clean_rules(monkeypatch)
    monkeypatch.setattr(
        safety_gate,
        "check_channel_policy",
        lambda *_args: CensorResult(hit=True, level="CP", tag="频道策略", matched="policy", channel="en"),
    )
    receipt = safety_gate.evaluate(
        "delivery",
        [safety_gate.SafetyDocument(name="final", en_text="safe text")],
        visual_review=_visual_receipt(),
        require_visual_review=True,
    )

    assert receipt["state"] == "BLOCKED"
    assert receipt["visual_review"]["effort"] == "high"

    _patch_clean_rules(monkeypatch)
    invalid_visual = {**_visual_receipt(), "effort": "medium"}
    invalid = safety_gate.evaluate(
        "delivery", [safety_gate.SafetyDocument(name="final", en_text="safe text")],
        visual_review=invalid_visual, require_visual_review=True,
    )
    assert invalid["state"] == "FAIL_CLOSED"

    invalid_model = {**_visual_receipt(), "model": "gemini-weak"}
    assert safety_gate.evaluate(
        "delivery", [safety_gate.SafetyDocument(name="final", en_text="safe text")],
        visual_review=invalid_model, require_visual_review=True,
    )["state"] == "FAIL_CLOSED"


def test_rule_loader_exception_is_fail_closed(monkeypatch):
    monkeypatch.setattr(safety_gate, "current_rules_fingerprint", lambda: (_ for _ in ()).throw(RuntimeError("broken")))

    receipt = safety_gate.evaluate("candidate_preflight", [safety_gate.SafetyDocument(name="source", en_text="safe")])

    assert receipt["state"] == "FAIL_CLOSED"
    assert receipt["failure_kind"] == "RuntimeError"


def test_delivery_receipt_binds_artifacts_source_evidence_and_visual_review(tmp_path, monkeypatch):
    _patch_clean_rules(monkeypatch)
    timeline = tmp_path / "timeline.json"
    timeline.write_text(json.dumps({
        "headline_en": "Clean energy", "headline_zh": "清洁能源", "english_text": "Clean energy helps.",
        "translation_zh": "清洁能源很有帮助。",
        "source_provenance": {"source_title": "Clean energy update"},
    }), encoding="utf-8")
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "source_evidence.json").write_text(json.dumps({
        "parsed": {"english_text": "Clean energy helps."}, "asr_text": "Clean energy helps.",
        "asr_words": [{"word": "Clean"}, {"word": "energy"}],
    }), encoding="utf-8")
    (tmp_path / "display_plan.json").write_text(json.dumps({"content": {"headline_zh": "清洁能源"}}), encoding="utf-8")
    mp4, manifest = tmp_path / "video.mp4", tmp_path / "video.manifest.json"
    mp4.write_bytes(b"video")
    manifest.write_text("{}", encoding="utf-8")
    contact_sheet = qa / "visual_safety_contact_sheet.png"
    contact_sheet.write_bytes(b"contact-sheet")

    receipt = safety_gate.evaluate_delivery(
        title="清洁能源", timeline_path=timeline,
        visual_review=_visual_receipt(
            mp4_sha256=sha256(mp4.read_bytes()).hexdigest(),
            contact_sheet=str(contact_sheet),
            contact_sheet_sha256=sha256(contact_sheet.read_bytes()).hexdigest(),
        ),
        require_visual_review=True,
    )
    assert receipt["state"] == "PASS"
    bound = safety_gate.attach_artifact_binding(receipt, mp4=mp4, manifest=manifest, timeline=timeline)
    receipt_path = tmp_path / "qa/safety_gate.json"
    receipt_path.write_text(json.dumps(bound), encoding="utf-8")

    assert safety_gate.validate_delivery_receipt(receipt_path, mp4=mp4, manifest=manifest, timeline=timeline)["state"] == "PASS"
    mp4.write_bytes(b"changed")
    with pytest.raises(safety_gate.EnglishWorldSafetyGateError, match="内容不一致"):
        safety_gate.validate_delivery_receipt(receipt_path, mp4=mp4, manifest=manifest, timeline=timeline)


def test_delivery_receipt_rejects_changed_contact_sheet(tmp_path, monkeypatch):
    _patch_clean_rules(monkeypatch)
    timeline = tmp_path / "timeline.json"
    timeline.write_text(json.dumps({"source_provenance": {"source_title": "Clean"}}), encoding="utf-8")
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "source_evidence.json").write_text(json.dumps({"asr_text": "Clean energy"}), encoding="utf-8")
    mp4, manifest = tmp_path / "video.mp4", tmp_path / "manifest.json"
    mp4.write_bytes(b"video")
    manifest.write_text("{}", encoding="utf-8")
    contact_sheet = qa / "contact.png"
    contact_sheet.write_bytes(b"original")
    receipt = safety_gate.evaluate_delivery(
        title="清洁能源",
        timeline_path=timeline,
        visual_review=_visual_receipt(
            mp4_sha256=sha256(mp4.read_bytes()).hexdigest(),
            contact_sheet=str(contact_sheet),
            contact_sheet_sha256=sha256(contact_sheet.read_bytes()).hexdigest(),
        ),
        require_visual_review=True,
    )
    bound = safety_gate.attach_artifact_binding(receipt, mp4=mp4, manifest=manifest, timeline=timeline)
    receipt_path = qa / "safety.json"
    receipt_path.write_text(json.dumps(bound), encoding="utf-8")
    contact_sheet.write_bytes(b"changed")

    with pytest.raises(safety_gate.EnglishWorldSafetyGateError, match="联系表"):
        safety_gate.validate_delivery_receipt(receipt_path, mp4=mp4, manifest=manifest, timeline=timeline)


def test_delivery_without_source_evidence_produces_fail_closed_receipt(tmp_path):
    timeline = tmp_path / "timeline.json"
    timeline.write_text("{}", encoding="utf-8")

    receipt = safety_gate.evaluate_delivery(title="标题", timeline_path=timeline)

    assert receipt["state"] == "FAIL_CLOSED"

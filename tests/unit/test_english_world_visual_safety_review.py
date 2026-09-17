"""最终成片视觉安全回执：AGY 只可审阅哈希绑定的九帧联系表。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-17 | Codex | 覆盖 high-effort AGY 参数、风险阻断及复核中产物变更的失败关闭。 |
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from scripts import english_world_visual_safety_review as review


def _fake_contact_sheet(_mp4, contact_sheet, **_kwargs):
    contact_sheet.parent.mkdir(parents=True, exist_ok=True)
    contact_sheet.write_bytes(b"contact-sheet")
    return 42.0, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)


def test_visual_review_uses_sandboxed_agy_high_effort_and_binds_current_mp4(monkeypatch, tmp_path):
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"video")
    contact_sheet = tmp_path / "qa/contact.png"
    monkeypatch.setattr(review, "_extract_contact_sheet", _fake_contact_sheet)
    captured = {}

    def fake_agy(**kwargs):
        captured.update(kwargs)
        assert (kwargs["work_dir"] / "contact_sheet.png").is_file()
        return {"state": "PASS", "coverage": "SUFFICIENT", "risk_categories": []}

    monkeypatch.setattr(review, "_run_agy", fake_agy)
    receipt = review.review_video(
        mp4=mp4, contact_sheet=contact_sheet, agy_bin="agy-test", model="gemini-3.8-flash-high",
        timeout_seconds=60,
    )

    assert receipt["state"] == "PASS"
    assert receipt["effort"] == "high"
    assert receipt["mp4_sha256"] == sha256(b"video").hexdigest()
    assert receipt["contact_sheet"] == str(contact_sheet.resolve())
    assert receipt["contact_sheet_sha256"] == sha256(b"contact-sheet").hexdigest()
    assert captured["agy_bin"] == "agy-test"
    assert captured["model"] == "gemini-3.8-flash-high"


def test_visual_review_blocks_any_model_reported_risk(monkeypatch, tmp_path):
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"video")
    monkeypatch.setattr(review, "_extract_contact_sheet", _fake_contact_sheet)
    monkeypatch.setattr(
        review,
        "_run_agy",
        lambda **_kwargs: {
            "state": "PASS", "coverage": "SUFFICIENT", "risk_categories": ["war_or_weapons"],
        },
    )

    receipt = review.review_video(
        mp4=mp4, contact_sheet=tmp_path / "contact.png", agy_bin="agy", model="model", timeout_seconds=60,
    )

    assert receipt["state"] == "BLOCKED"
    assert receipt["risk_categories"] == ["war_or_weapons"]


def test_visual_review_rejects_when_mp4_changes_during_review(monkeypatch, tmp_path):
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"before")
    monkeypatch.setattr(review, "_extract_contact_sheet", _fake_contact_sheet)

    def mutate_mp4(**_kwargs):
        mp4.write_bytes(b"after")
        return {"state": "PASS", "coverage": "SUFFICIENT", "risk_categories": []}

    monkeypatch.setattr(review, "_run_agy", mutate_mp4)

    with pytest.raises(review.VisualSafetyReviewError, match="MP4 发生变化"):
        review.review_video(
            mp4=mp4, contact_sheet=tmp_path / "contact.png", agy_bin="agy", model="model", timeout_seconds=60,
        )


"""P0 双重人工复核放行的回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-07 | Codex | 锁定 P0 未确认拒绝、双确认审计和管线认可三项约束。 |
"""

from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from config.settings import settings
from video_processing import censor_engine
from video_processing.censorship_service import CensorshipService
from video_processing.db.database import PipelineDB


def _p0_failed_video(db: PipelineDB, youtube_id: str) -> None:
    assert db.add_video(youtube_id, "P0 video", "channel", score=80)
    db.update_video_status(
        youtube_id,
        "FAILED",
        error_msg="Censorship P0 Reject: 🔴 政治安全违禁 (matched: 'rule')",
    )
    db.update_video_censor_status(youtube_id, "🔴 政治安全违禁", 95)
    db.add_to_blacklist(youtube_id, reason="censor_p0_rule")


def test_p0_bypass_requires_double_confirmation_and_records_audit(tmp_path, monkeypatch):
    """P0 少任一确认不写库；双确认才解黑、入队并留下可查询审计。"""
    import web.app

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    youtube_id = "p0-double-confirm"
    _p0_failed_video(db, youtube_id)
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(web.app, "_trigger_video_async", Mock())
    client = TestClient(web.app.app)

    blocked = client.post(f"/api/videos/{youtube_id}/bypass-censor")
    assert blocked.status_code == 200
    assert blocked.json() == {
        "success": False,
        "error": "P0 放行需要完成“已复核内容”与“确认恢复管线”两项确认。",
    }
    video = db.get_video_by_youtube_id(youtube_id)
    assert video["status"] == "FAILED"
    assert video["bypass_censorship"] == 0
    assert db.is_blacklisted(youtube_id) is True
    assert db.has_manual_p0_approval(youtube_id) is False

    approved = client.post(
        f"/api/videos/{youtube_id}/bypass-censor",
        json={"confirm_p0_review": True, "confirm_pipeline_resume": True},
    )
    assert approved.status_code == 200
    assert approved.json()["success"] is True
    assert db.has_manual_p0_approval(youtube_id) is True
    assert db.is_blacklisted(youtube_id) is False
    assert db.get_video_by_youtube_id(youtube_id)["bypass_censorship"] == 1


def test_censorship_service_allows_p0_only_with_audited_manual_approval(tmp_path, monkeypatch):
    """遗留 bypass 标志不够；审计台账存在时 P0 才能被人工放行。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    youtube_id = "p0-audit-required"
    assert db.add_video(youtube_id, "P0 video", "channel", score=80)
    db.set_bypass_censorship(youtube_id, True)
    db.record_censorship_incident(
        youtube_id,
        stage="manual_review",
        level="P0",
        action="MANUAL_BYPASS",
        tag="🔴 政治安全违禁",
        score=None,
        matched="rule",
        channel="operator",
        decision="MANUAL_P0_APPROVED",
    )
    hit = SimpleNamespace(
        hit=True,
        level="P0",
        tag="🔴 政治安全违禁",
        score=95,
        action=censor_engine.ACTION_REJECT_SIGTERM,
        matched="rule",
        channel="en",
    )
    monkeypatch.setattr(settings, "enable_censorship_engine", True)
    monkeypatch.setattr(settings, "enable_channel_policy_filter", False)
    monkeypatch.setattr(censor_engine, "check_text", lambda **_kwargs: hit)

    assert CensorshipService(db, Mock()).check(youtube_id, "P0 video") is False

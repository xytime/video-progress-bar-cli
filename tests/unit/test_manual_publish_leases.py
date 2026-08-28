"""单任务微信发布 lease 的 DAL、API 与窗口守卫回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-29 | Codex | 覆盖安全候选、两小时签发、一次性消费、盘中边界与单任务启动。 |
| 1.1.0 | 2026-08-29 | Codex | 覆盖内部令牌 fail-closed、精确 TTL、未消费撤销和撤销审计。 |
"""

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from config.settings import Settings
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager


def _db(tmp_path: Path) -> PipelineDB:
    return PipelineDB(str(tmp_path / "pipeline.db"))


def test_lease_candidates_exclude_discovery_review_and_existing_ledger(tmp_path: Path):
    db = _db(tmp_path)
    assert db.add_video("lease-safe1", "安全候选", "channel", score=88, source="AUTO")
    assert db.add_video("lease-disc1", "发现候选", "channel", score=99, source="DISCOVERY")
    assert db.add_video("lease-review", "人工复核", "channel", score=90, source="AUTO")
    assert db.add_video("lease-ledger", "已有账本", "channel", score=90, source="AUTO")
    assert db.set_publication_review_required("lease-review", True)
    db.record_wechat_publication_confirmation(
        "lease-ledger", evidence_path=None, state="SUBMITTED_UNBOUND",
    )

    candidates = db.list_manual_publish_lease_candidates()

    assert [item["youtube_id"] for item in candidates] == ["lease-safe1"]


def test_lease_is_bounded_and_can_only_be_claimed_once(tmp_path: Path):
    db = _db(tmp_path)
    assert db.add_video("lease-once1", "一次授权", "channel", score=80, source="AUTO")

    lease = db.issue_manual_publish_lease(
        "lease-once1", issued_by="telegram:123", issued_via="telegram", ttl_minutes=999,
    )

    issued_at = datetime.strptime(lease["issued_at"], "%Y-%m-%d %H:%M:%S")
    expires_at = datetime.strptime(lease["expires_at"], "%Y-%m-%d %H:%M:%S")
    assert (expires_at - issued_at).total_seconds() == 120 * 60
    assert db.list_active_manual_publish_leases()[0]["lease_id"] == lease["lease_id"]
    claimed = db.claim_manual_publish_lease("lease-once1")
    assert claimed and claimed["lease_id"] == lease["lease_id"]
    assert claimed["claimed_at"]
    assert db.claim_manual_publish_lease("lease-once1") is None
    assert db.list_active_manual_publish_leases() == []


def test_unclaimed_lease_can_be_revoked_once_with_audit(tmp_path: Path):
    db = _db(tmp_path)
    assert db.add_video("lease-stop1", "撤销授权", "channel", score=80, source="AUTO")
    lease = db.issue_manual_publish_lease(
        "lease-stop1", issued_by="telegram:123", issued_via="telegram",
    )

    revoked = db.revoke_manual_publish_lease(
        lease["lease_id"], revoked_by="telegram:123",
    )

    assert revoked and revoked["revoked_at"]
    assert revoked["revoked_by"] == "telegram:123"
    assert db.revoke_manual_publish_lease(
        lease["lease_id"], revoked_by="telegram:123",
    ) is None
    assert db.claim_manual_publish_lease("lease-stop1") is None
    assert db.list_active_manual_publish_leases() == []


def test_lease_http_routes_require_internal_token_and_reject_browser_origin(
    monkeypatch, tmp_path: Path,
):
    import web.app

    monkeypatch.setattr(web.app, "db", _db(tmp_path))
    monkeypatch.setattr(web.app.settings, "pipeline_internal_api_token", "s" * 32)
    client = TestClient(web.app.app)

    assert client.get("/api/publication-leases/candidates").status_code == 403
    assert client.get(
        "/api/publication-leases/candidates",
        headers={"X-Pipeline-Internal-Token": "x" * 32},
    ).status_code == 403
    assert client.get(
        "/api/publication-leases/candidates",
        headers={"X-Pipeline-Internal-Token": "s" * 32, "Origin": "https://example.invalid"},
    ).status_code == 403
    assert client.get(
        "/api/publication-leases/candidates",
        headers={"X-Pipeline-Internal-Token": "s" * 32},
    ).status_code == 200
    assert client.post(
        "/api/publication-leases",
        json={"youtube_id": "missing1", "issued_by": "telegram:123"},
    ).status_code == 403


def test_pipeline_lease_bypasses_closed_window_once(monkeypatch, tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    assert manager.db.add_video("lease-gate1", "窗口外任务", "channel", score=85, source="AUTO")
    manager.db.issue_manual_publish_lease(
        "lease-gate1", issued_by="telegram:123", issued_via="telegram",
    )
    monkeypatch.setattr(
        Settings,
        "is_public_publish_window",
        lambda self, now=None: False,
    )

    assert manager._is_public_publish_window(
        "微信", "lease-gate1", consume_manual_lease=True,
    )
    assert not manager._is_public_publish_window(
        "微信", "lease-gate1", consume_manual_lease=True,
    )


def test_web_lease_api_signs_and_starts_only_selected_task(monkeypatch, tmp_path: Path):
    import web.app

    db = _db(tmp_path)
    assert db.add_video("lease-api01", "手机任务", "channel", score=86, source="AUTO")
    assert db.add_video("lease-api02", "其他任务", "channel", score=84, source="AUTO")
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(
        Settings,
        "is_us_market_guard_window",
        lambda self, now=None: False,
    )
    started: list[dict] = []
    monkeypatch.setattr(web.app, "_trigger_video_async", started.append)

    result = web.app.create_manual_publish_lease(web.app.CreateManualPublishLeaseRequest(
        youtube_id="lease-api01", issued_by="telegram:123",
    ))

    assert result["success"] is True
    assert result["lease"]["youtube_id"] == "lease-api01"
    assert [item["youtube_id"] for item in started] == ["lease-api01"]
    assert db.get_video_by_youtube_id("lease-api01")["status"] == "DOWNLOADING"
    assert db.get_video_by_youtube_id("lease-api02")["status"] == "PENDING"


def test_web_lease_api_keeps_unprepared_work_out_of_market_hours(monkeypatch, tmp_path: Path):
    import web.app

    db = _db(tmp_path)
    assert db.add_video("lease-heavy", "盘中重任务", "channel", score=90, source="AUTO")
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(
        Settings,
        "is_us_market_guard_window",
        lambda self, now=None: True,
    )

    result = web.app.create_manual_publish_lease(web.app.CreateManualPublishLeaseRequest(
        youtube_id="lease-heavy", issued_by="telegram:123",
    ))

    assert result["success"] is False
    assert "盘中" in result["error"]
    assert db.list_active_manual_publish_leases() == []

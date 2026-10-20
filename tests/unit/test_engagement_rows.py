"""高互动阶段、分页筛选和操作资格；真实临时 SQLite，不触发生产。"""
from datetime import datetime
import hashlib
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from video_processing.core.engagement_presentation import present_engagement
from video_processing.core.task_lease import TaskLease
from video_processing.db.database import PipelineDB
from web import app as web_app


def seed(db, yid, status="PENDING", score=85, source="AUTO", error=None):
    db.add_video(yid, "验收素材 " + yid, "fixture", score=score, source=source,
                 view_count=1000, like_count=40, upload_date=datetime.now().strftime("%Y%m%d"))
    db.update_video_status(yid, status, error_msg=error)


@pytest.fixture
def api(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "engagement.db"))
    dispatch = Mock()
    monkeypatch.setattr(web_app, "db", db)
    monkeypatch.setattr(web_app, "_trigger_video_async", dispatch)
    with TestClient(web_app.app) as client:
        yield db, client, dispatch


@pytest.mark.parametrize("status,score,source,error,stage,action", [
    ("PENDING", 20, "DISCOVERY", None, "ENG_DISCOVERY", "promote"),
    ("PENDING", 0, "AUTO", None, "ENG_UNSCORED", "promote"),
    ("METADATA_PENDING", 0, "AUTO", None, "ENG_UNSCORED", None),
    ("PENDING", 26, "AUTO", None, "ENG_LOW_SCORE", "promote"),
    ("PENDING", 90, "AUTO", None, "ENG_PENDING", "process"),
    ("TRANSCRIBING", 90, "AUTO", None, "ENG_ACTIVE", None),
    ("FAILED", 90, "AUTO", "download timeout", "ENG_FAILED", "retry"),
    ("FAILED", 90, "AUTO", "Channel Policy Reject: tutorial", "ENG_POLICY", "bypass-censor"),
    ("FAILED", 90, "AUTO", "Censorship P0 Reject: rule", "ENG_POLICY", "bypass-censor"),
    ("LOGIN_REQUIRED", 90, "AUTO", None, "ENG_LOGIN", None),
    ("SUBMITTED_BOUND", 90, "AUTO", None, "ENG_SUBMITTED", None),
    ("UNDER_REVIEW", 90, "AUTO", None, "ENG_REVIEW", None),
    ("PUBLISHED", 90, "AUTO", None, "ENG_VERIFY", None),
    ("SEGMENTED", 90, "AUTO", None, "ENG_SEGMENTED", None),
    ("IGNORED", 90, "AUTO", None, "ENG_EXCLUDED", None),
])
def test_stage_and_allowed_action(api, status, score, source, error, stage, action):
    db, client, _ = api
    seed(db, "sample", status, score, source, error)
    row = client.get("/api/videos?tab=high_likes&created_window=all").json()["videos"][0]
    assert row["engagement"]["stage"] == stage
    assert row["engagement"]["action"] == action
    assert row["engagement"]["version"] == present_engagement(db.get_engagement_video("sample"))["version"]


def test_filter_before_pagination_ready_blacklist_and_ledger(api):
    db, client, dispatch = api
    for yid in ("ready", "denied", "ledger", "low-a", "low-b"):
        seed(db, yid, score=30)
    db.add_to_blacklist("denied", reason="manual exclusion")
    db.update_video_status("denied", "FAILED", error_msg="download error")
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET preparation_ready=1 WHERE youtube_id='ready'")
    db.record_wechat_publication_confirmation("ledger", state="SUBMITTED_BOUND",
                                              evidence_path=None, platform_post_id="fixture-native-id")
    assert db.get_engagement_video("ready")["engagement_stage"] == "ENG_READY"
    assert db.get_engagement_video("denied")["engagement_stage"] == "ENG_EXCLUDED"
    assert present_engagement(db.get_engagement_video("ledger"))["action"] is None
    data = client.get("/api/videos?tab=high_likes&status=ENG_LOW_SCORE&page=2&size=1&created_window=all").json()
    assert data["total_count"] == 2 and data["total_pages"] == 2 and len(data["videos"]) == 1
    assert data["videos"][0]["engagement"]["stage"] == "ENG_LOW_SCORE"
    assert client.get("/api/videos?tab=high_likes&status=ENG_NOT_REAL").status_code == 422
    dispatch.assert_not_called()


def test_stale_and_wrong_action_rejected_and_fresh_process_once(api):
    db, client, dispatch = api
    seed(db, "fresh")
    row = client.get("/api/videos?tab=high_likes").json()["videos"][0]
    version = row["engagement"]["version"]
    assert client.post("/api/videos/fresh/retry", params={"engagement_version": version}).status_code == 409
    assert client.post("/api/videos/fresh/process", params={"engagement_version": version}).json()["success"]
    assert client.post("/api/videos/fresh/process", params={"engagement_version": version}).status_code == 409
    dispatch.assert_called_once()
    seed(db, "stale")
    version = present_engagement(db.get_engagement_video("stale"))["version"]
    db.update_video_status("stale", "SUBMITTED_BOUND")
    assert client.post("/api/videos/stale/process", params={"engagement_version": version}).status_code == 409
    dispatch.assert_called_once()


def test_promote_low_score_retry_and_browse_independence(api):
    db, client, dispatch = api
    seed(db, "choose", score=20)
    version = present_engagement(db.get_engagement_video("choose"))["version"]
    response = client.post("/api/videos/choose/engagement-reviewed", json={"reviewed": True})
    assert response.status_code == 200
    assert present_engagement(db.get_engagement_video("choose"))["version"] == version
    assert client.post("/api/videos/choose/promote", params={"engagement_version": version}).json()["success"]
    row = db.get_video_by_youtube_id("choose")
    assert row["score"] == 100 and row["source"] == "MANUAL"
    dispatch.assert_called_once()
    seed(db, "retry-low", "FAILED", 20, error="network error")
    version = present_engagement(db.get_engagement_video("retry-low"))["version"]
    assert client.post("/api/videos/retry-low/retry", params={"engagement_version": version}).json()["success"]
    assert db.get_video_by_youtube_id("retry-low")["status"] == "PENDING"
    dispatch.assert_called_once()


def test_policy_requires_p0_confirmation_and_stale_censor_tag_is_not_pass(api):
    db, client, dispatch = api
    seed(db, "policy", "FAILED", error="Censorship P0 Reject: rule")
    db.add_to_blacklist("policy", reason="censor")
    version = present_engagement(db.get_engagement_video("policy"))["version"]
    response = client.post("/api/videos/policy/bypass-censor", params={"engagement_version": version})
    assert not response.json()["success"]
    assert db.is_blacklisted("policy")
    dispatch.assert_not_called()
    seed(db, "technical", "FAILED", error="render crashed")
    db.update_video_censor_status("technical", "old tag", 20)
    assert present_engagement(db.get_engagement_video("technical"))["action"] == "retry"


def test_action_lock_blocks_duplicate_and_review_flag_disables_start(api):
    db, client, dispatch = api
    seed(db, "locked")
    token = present_engagement(db.get_engagement_video("locked"))["version"]
    key = hashlib.sha256(b"locked").hexdigest()
    with TaskLease(web_app._OUT_DIR / "engagement_action_locks" / f"{key}.lock"):
        assert client.post("/api/videos/locked/process", params={"engagement_version": token}).status_code == 409
    assert db.get_video_by_youtube_id("locked")["status"] == "PENDING"
    db.set_publication_review_required("locked", True)
    assert present_engagement(db.get_engagement_video("locked"))["action"] is None
    dispatch.assert_not_called()


def test_confirmed_publication_requires_evidence(api):
    db, client, dispatch = api
    seed(db, "confirmed", "PUBLISHED")
    assert db.get_engagement_video("confirmed")["engagement_stage"] == "ENG_VERIFY"
    db.record_wechat_publication_confirmation("confirmed", state="PUBLISHED",
                                              evidence_path="fixture-only.json", platform_post_id="native")
    assert db.get_engagement_video("confirmed")["engagement_stage"] == "ENG_PUBLISHED"
    dispatch.assert_not_called()


def test_prepared_video_read_is_task_scoped_and_no_missing_link(api, tmp_path, monkeypatch):
    db, client, dispatch = api
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(web_app, "_OUT_DIR", output)
    seed(db, "render")
    assert client.get("/api/videos/render/prepared-video").status_code == 404
    video = output / "render_vertical.mp4"
    video.write_bytes(b"fixture-video")
    row = client.get("/api/videos?tab=high_likes").json()["videos"][0]
    assert row["prepared_video_url"] is None
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET preparation_ready=1 WHERE youtube_id='render'")
    row = client.get("/api/videos?tab=high_likes").json()["videos"][0]
    assert row["prepared_video_url"]
    assert client.get(row["prepared_video_url"]).content == b"fixture-video"
    assert web_app._prepared_video_path("../elsewhere", 0) is None
    video.unlink()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not-for-this-task")
    video.symlink_to(outside)
    assert client.get("/api/videos/render/prepared-video").status_code == 404
    dispatch.assert_not_called()

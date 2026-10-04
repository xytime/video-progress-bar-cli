"""具名媒体恢复必须保留历史并拒绝已投稿作品。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-05 | Codex | 认证恢复必须具有新鲜验证，且不能绕过投稿、策略与 CAS 保护。 |
| 1.0.0 | 2026-10-05 | Codex | compare-and-set、进程归属、策略与投稿账本保护。 |
"""
import pytest
import time
from video_processing.db.database import PipelineDB

ERROR = "Caption progress timed out: stage=TRANSLATING (724s)"


def make_db(tmp_path):
    db = PipelineDB(tmp_path / "test.db")
    db.add_video("test", "视频生产", "channel", score=80)
    db.update_video_status("test", "FAILED", error_msg=ERROR)
    return db


def test_claim_keeps_retry_history_and_cannot_be_repeated(tmp_path):
    db = make_db(tmp_path)
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET retry_count=2")
    assert db.claim_failed_media_recovery("test", expected_error=ERROR, expected_retry_count=2, owner_pid=123)
    row = db.get_video_by_youtube_id("test")
    assert (row["status"], row["retry_count"], row["process_pid"], row["score"]) == ("PROCESSING", 3, 123, 80)
    assert not db.claim_failed_media_recovery("test", expected_error=ERROR, expected_retry_count=2, owner_pid=123)


@pytest.mark.parametrize("change", ["submitted", "historical", "running", "changed", "policy", "discovery", "old"])
def test_protected_rows_are_not_claimed(tmp_path, change):
    db = make_db(tmp_path)
    if change == "submitted":
        db.record_wechat_submission_attempt("test", evidence_path="test-receipt")
    with db.get_connection() as conn:
        row_id = db.get_video_by_youtube_id("test")["id"]
        if change == "historical":
            conn.execute("INSERT INTO wechat_publications_historical_archive(video_id, archived_at, archive_reason, state) VALUES (?, CURRENT_TIMESTAMP, 'archived', 'HISTORICAL_ARCHIVED')", (row_id,))
        elif change == "running": conn.execute("UPDATE processed_videos SET process_pid=123")
        elif change == "changed": conn.execute("UPDATE processed_videos SET error_msg='other failure'")
        elif change == "policy": conn.execute("UPDATE processed_videos SET error_msg='Channel Policy Reject'")
        elif change == "discovery": conn.execute("UPDATE processed_videos SET source='DISCOVERY'")
        elif change == "old": conn.execute("UPDATE processed_videos SET updated_at=datetime('now','-49 hours')")
    assert not db.claim_failed_media_recovery("test", expected_error=ERROR, expected_retry_count=0, owner_pid=123)


@pytest.mark.parametrize("age", [None, 61, -10, float("nan")])
def test_auth_failure_requires_fresh_verified_source(tmp_path, age):
    db = make_db(tmp_path)
    error = "SOURCE_DOWNLOAD_AUTH: not a bot; previous request timed out"
    db.update_video_status("test", "FAILED", error_msg=error)
    verified_at = None if age is None else time.time() - age
    assert not db.claim_failed_media_recovery("test", expected_error=error,
        expected_retry_count=0, owner_pid=123, verified_source_auth_at=verified_at)


@pytest.mark.parametrize("protection", [None, "submitted", "policy", "changed"])
def test_verified_auth_still_preserves_recovery_guards(tmp_path, protection):
    db = make_db(tmp_path)
    error = "SOURCE_DOWNLOAD_AUTH: Sign in to confirm you are not a bot"
    if protection == "policy":
        error += "; CENSOR blocked"
    db.update_video_status("test", "FAILED", error_msg=error)
    if protection == "submitted":
        db.record_wechat_submission_attempt("test", evidence_path="submission-proof")
    if protection == "changed":
        db.update_video_status("test", "FAILED", error_msg="other failure")
    claimed = db.claim_failed_media_recovery("test", expected_error=error,
        expected_retry_count=0, owner_pid=123, verified_source_auth_at=time.time())
    assert claimed is (protection is None)
    row = db.get_video_by_youtube_id("test")
    assert row["retry_count"] == (1 if protection is None else 0)

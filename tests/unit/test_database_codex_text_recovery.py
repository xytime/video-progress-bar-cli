"""具名文字失败恢复的业务状态和投稿防重边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-03 | Codex | 覆盖近24小时 compare-and-set、进程占用、策略和投稿账本。 |
"""

import pytest

from video_processing.db.database import PipelineDB


ERROR = "All subtitle translation providers failed or were blocked."


def _db(tmp_path, status="FAILED", error=ERROR):
    db = PipelineDB(tmp_path / "test.db")
    db.add_video("test-text", "制造技术", "channel", score=80)
    db.update_video_status("test-text", status, error_msg=error)
    return db


def test_named_text_recovery_is_atomic_and_preserves_score(tmp_path):
    db = _db(tmp_path)
    assert db.requeue_recent_text_provider_failure("test-text", expected_error=ERROR)
    row = db.get_video_by_youtube_id("test-text")
    assert row["status"] == "PENDING" and row["score"] == 80 and row["retry_count"] == 1
    assert not db.requeue_recent_text_provider_failure("test-text", expected_error=ERROR)


@pytest.mark.parametrize("status", ["PUBLISHED", "PUBLISHING", "LOGIN_REQUIRED", "TRANSCRIBING", "IGNORED"])
def test_other_states_not_released(tmp_path, status):
    assert not _db(tmp_path, status).requeue_recent_text_provider_failure("test-text", expected_error=ERROR)


@pytest.mark.parametrize("change", ["old", "running", "retried", "submitted", "historical", "other_error"])
def test_protected_failure_not_released(tmp_path, change):
    db = _db(tmp_path)
    if change == "submitted":
        db.record_wechat_submission_attempt("test-text", evidence_path="test-receipt")
    # SQL 限于 DAL 测试夹具，生产调用只使用公开方法。
    with db.get_connection() as conn:
        video_id = conn.execute("SELECT id FROM processed_videos WHERE youtube_id='test-text'").fetchone()[0]
        if change == "old":
            conn.execute("UPDATE processed_videos SET updated_at=datetime('now','-25 hours')")
        elif change == "running":
            conn.execute("UPDATE processed_videos SET process_pid=123")
        elif change == "retried":
            conn.execute("UPDATE processed_videos SET retry_count=3")
        elif change == "other_error":
            conn.execute("UPDATE processed_videos SET error_msg='changed by another worker'")
        elif change == "historical":
            conn.execute("INSERT INTO wechat_publications_historical_archive(video_id, archived_at, archive_reason, state) VALUES (?, CURRENT_TIMESTAMP, 'archived', 'HISTORICAL_ARCHIVED')", (video_id,))
    assert not db.requeue_recent_text_provider_failure("test-text", expected_error=ERROR)


def test_policy_error_and_deferred_queue_deadline(tmp_path):
    db = _db(tmp_path, "COPYWRITING", "COPY_PROVIDER_DEFERRED")
    assert db.defer_copywriter_provider("test-text", slice_index=0, until=9999999999, reason="COPY_PROVIDER_DEFERRED")
    assert not db.claim_video_for_processing("test-text")
    assert db.requeue_recent_text_provider_failure("test-text", expected_error="COPY_PROVIDER_DEFERRED")
    assert db.claim_video_for_processing("test-text")
    assert not db.requeue_recent_text_provider_failure("test-text", expected_error="Channel Policy Reject TitleContractError:")

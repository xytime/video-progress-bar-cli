"""快手浏览器发布账本：仅发布成功去重、迁移限额和不确定结果保护。"""

import sqlite3
from pathlib import Path

from video_processing.db.database import PipelineDB


def _add_video(db: PipelineDB, youtube_id: str) -> None:
    assert db.add_video(youtube_id, "测试视频", "test-channel", score=80)


def test_kuaishou_ledger_only_deduplicates_assets_after_published(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "video-one")
    _add_video(db, "video-two")
    _add_video(db, "video-three")
    digest = "a" * 64

    first = db.create_kuaishou_publication("video-one", digest, "/tmp/one.mp4", source_kind="HISTORY")
    retryable = db.create_kuaishou_publication("video-two", digest, "/tmp/two.mp4", source_kind="HISTORY")
    assert retryable["id"] != first["id"]

    assert db.update_kuaishou_publication_state(first["id"], "PUBLISHED")
    duplicate = db.create_kuaishou_publication("video-three", digest, "/tmp/three.mp4", source_kind="HISTORY")

    assert duplicate["id"] == first["id"]
    assert db.get_kuaishou_publication("video-one")["state"] == "PUBLISHED"
    assert db.get_kuaishou_publication("video-two")["state"] == "QUEUED"


def test_same_video_can_create_a_new_attempt_after_failure(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "retry-video")
    digest = "d" * 64

    first = db.create_kuaishou_publication("retry-video", digest, "/tmp/retry.mp4", source_kind="HISTORY")
    assert db.update_kuaishou_publication_state(first["id"], "RETRYABLE_FAILED")
    second = db.create_kuaishou_publication("retry-video", digest, "/tmp/retry.mp4", source_kind="HISTORY")

    assert second["attempt_number"] == 2
    assert second["state"] == "QUEUED"


def test_history_claim_respects_daily_limit_and_uncertain_never_requeues(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "history-one")
    _add_video(db, "history-two")
    db.create_kuaishou_publication("history-one", "b" * 64, "/tmp/one.mp4", source_kind="HISTORY")
    db.create_kuaishou_publication("history-two", "c" * 64, "/tmp/two.mp4", source_kind="HISTORY")

    claimed = db.claim_next_kuaishou_history_publication(daily_limit=1)
    assert claimed is not None
    assert claimed["state"] == "UPLOADING"
    assert db.claim_next_kuaishou_history_publication(daily_limit=1) is None

    assert db.update_kuaishou_publication_state(claimed["id"], "UNCERTAIN", error_message="页面关闭前未确认")
    assert db.claim_next_kuaishou_history_publication(daily_limit=2) is not None
    assert db.claim_next_kuaishou_history_publication(daily_limit=2) is None


def test_history_candidates_only_include_wechat_published_and_non_blacklisted(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "published-video")
    _add_video(db, "pending-video")
    _add_video(db, "blocked-video")
    db.update_video_status("published-video", "PUBLISHED")
    db.update_video_status("blocked-video", "PUBLISHED")
    assert db.add_to_blacklist("blocked-video", "wechat_takedown_prohibited")

    candidates = db.get_unqueued_kuaishou_history_videos()

    assert [candidate["youtube_id"] for candidate in candidates] == ["published-video"]


def test_new_video_claim_is_not_limited_by_historical_daily_quota(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "new-video")
    publication = db.create_kuaishou_publication(
        "new-video", "e" * 64, "/tmp/new.mp4", source_kind="NEW"
    )

    claimed = db.claim_next_kuaishou_publication("NEW")

    assert claimed is not None
    assert claimed["id"] == publication["id"]
    assert claimed["youtube_id"] == "new-video"


def test_failed_claim_waits_until_the_next_day_instead_of_reclicking_same_day(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "retry-tomorrow")
    db.create_kuaishou_publication("retry-tomorrow", "f" * 64, "/tmp/retry.mp4", source_kind="NEW")
    claimed = db.claim_next_kuaishou_publication("NEW")
    assert claimed is not None
    assert db.update_kuaishou_publication_state(claimed["id"], "RETRYABLE_FAILED")

    assert db.claim_next_kuaishou_publication("NEW") is None


def test_under_review_is_a_terminal_submission_state_not_a_duplicate_retry(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "under-review-video")
    publication = db.create_kuaishou_publication(
        "under-review-video", "0" * 64, "/tmp/review.mp4", source_kind="HISTORY"
    )
    assert db.update_kuaishou_publication_state(publication["id"], "UNDER_REVIEW")

    assert db.get_kuaishou_publication("under-review-video")["state"] == "UNDER_REVIEW"
    assert db.claim_next_kuaishou_history_publication(daily_limit=10) is None


def test_manually_completed_attempt_counts_toward_history_daily_limit(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "manual-attempt")
    _add_video(db, "next-history")
    manual = db.create_kuaishou_publication(
        "manual-attempt", "2" * 64, "/tmp/manual.mp4", source_kind="HISTORY"
    )
    db.create_kuaishou_publication("next-history", "3" * 64, "/tmp/next.mp4", source_kind="HISTORY")
    assert db.update_kuaishou_publication_state(manual["id"], "UNDER_REVIEW")
    assert db.mark_kuaishou_publication_attempted(manual["id"])

    assert db.claim_next_kuaishou_history_publication(daily_limit=1) is None


def test_retryable_failure_does_not_consume_a_history_submission_slot(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "failed-calibration")
    _add_video(db, "ready-to-submit")
    failed = db.create_kuaishou_publication(
        "failed-calibration", "4" * 64, "/tmp/failed.mp4", source_kind="HISTORY"
    )
    db.create_kuaishou_publication(
        "ready-to-submit", "5" * 64, "/tmp/ready.mp4", source_kind="HISTORY"
    )
    assert db.mark_kuaishou_publication_attempted(failed["id"])
    assert db.update_kuaishou_publication_state(failed["id"], "RETRYABLE_FAILED")

    assert db.claim_next_kuaishou_history_publication(daily_limit=1)["youtube_id"] == "ready-to-submit"


def test_existing_ledger_is_migrated_to_support_under_review(tmp_path: Path):
    db_path = tmp_path / "pipeline.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE kuaishou_publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL,
                asset_sha256 TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('QUEUED', 'PUBLISHED')),
                video_path TEXT NOT NULL,
                attempt_number INTEGER NOT NULL DEFAULT 1,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                claimed_at TIMESTAMP DEFAULT NULL,
                published_at TIMESTAMP DEFAULT NULL,
                external_post_id TEXT DEFAULT NULL,
                external_url TEXT DEFAULT NULL,
                last_error_message TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )

    db = PipelineDB(str(db_path))
    _add_video(db, "migrated-review")
    publication = db.create_kuaishou_publication(
        "migrated-review", "1" * 64, "/tmp/migrated.mp4", source_kind="NEW"
    )

    assert db.update_kuaishou_publication_state(publication["id"], "UNDER_REVIEW")

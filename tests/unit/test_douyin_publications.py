"""抖音浏览器发布账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-23 | Codex | 覆盖抖音账本去重、迁移限额和审核状态 |
| 1.1.0 | 2026-07-25 | Codex | 覆盖提交后未确认的遗留失败不会被自动重投 |
| 1.2.0 | 2026-07-29 | Codex | 覆盖含未确认反证的抖音 PUBLISHED 写入会保守降级且不参与去重 |
"""

from pathlib import Path

from video_processing.db.database import PipelineDB


def _add_video(db: PipelineDB, youtube_id: str) -> None:
    assert db.add_video(youtube_id, "测试视频", "test-channel", score=80)


def test_douyin_ledger_only_deduplicates_assets_after_published(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "video-one")
    _add_video(db, "video-two")
    _add_video(db, "video-three")
    digest = "a" * 64

    first = db.create_douyin_publication("video-one", digest, "/tmp/one.mp4", source_kind="HISTORY")
    retryable = db.create_douyin_publication("video-two", digest, "/tmp/two.mp4", source_kind="HISTORY")
    assert retryable["id"] != first["id"]

    assert db.update_douyin_publication_state(first["id"], "PUBLISHED")
    duplicate = db.create_douyin_publication("video-three", digest, "/tmp/three.mp4", source_kind="HISTORY")

    assert duplicate["id"] == first["id"]
    assert db.get_douyin_publication("video-one")["state"] == "PUBLISHED"
    assert db.get_douyin_publication("video-two")["state"] == "QUEUED"


def test_douyin_published_with_unconfirmed_evidence_is_not_success_dedup(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "video-one")
    _add_video(db, "video-two")
    digest = "8" * 64

    first = db.create_douyin_publication("video-one", digest, "/tmp/one.mp4", source_kind="HISTORY")
    assert db.update_douyin_publication_state(
        first["id"],
        "PUBLISHED",
        error_message="抖音已接受发布提交，当前按审核中处理；等待作品管理回查校准后确认最终发布。",
    )
    second = db.create_douyin_publication("video-two", digest, "/tmp/two.mp4", source_kind="HISTORY")

    first_row = db.get_douyin_publication("video-one")
    assert first_row["state"] == "UNDER_REVIEW"
    assert first_row["published_at"] is None
    assert second["id"] != first["id"]
    assert db.get_douyin_publication("video-two")["state"] == "QUEUED"


def test_douyin_same_video_can_create_a_new_attempt_after_failure(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "retry-video")
    digest = "d" * 64

    first = db.create_douyin_publication("retry-video", digest, "/tmp/retry.mp4", source_kind="HISTORY")
    assert db.update_douyin_publication_state(first["id"], "RETRYABLE_FAILED")
    second = db.create_douyin_publication("retry-video", digest, "/tmp/retry.mp4", source_kind="HISTORY")

    assert second["attempt_number"] == 2
    assert second["state"] == "QUEUED"


def test_douyin_history_claim_respects_daily_limit_and_uncertain_never_requeues(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "history-one")
    _add_video(db, "history-two")
    db.create_douyin_publication("history-one", "b" * 64, "/tmp/one.mp4", source_kind="HISTORY")
    db.create_douyin_publication("history-two", "c" * 64, "/tmp/two.mp4", source_kind="HISTORY")

    claimed = db.claim_next_douyin_history_publication(daily_limit=1)
    assert claimed is not None
    assert claimed["state"] == "UPLOADING"
    assert db.claim_next_douyin_history_publication(daily_limit=1) is None

    assert db.update_douyin_publication_state(claimed["id"], "UNCERTAIN", error_message="页面关闭前未确认")
    assert db.claim_next_douyin_history_publication(daily_limit=2) is not None
    assert db.claim_next_douyin_history_publication(daily_limit=2) is None


def test_douyin_history_candidates_only_include_wechat_published_and_non_blacklisted(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "published-video")
    _add_video(db, "pending-video")
    _add_video(db, "blocked-video")
    db.update_video_status("published-video", "PUBLISHED")
    db.update_video_status("blocked-video", "PUBLISHED")
    assert db.add_to_blacklist("blocked-video", "wechat_takedown_prohibited")

    candidates = db.get_unqueued_douyin_history_videos()

    assert [candidate["youtube_id"] for candidate in candidates] == ["published-video"]


def test_douyin_under_review_is_a_terminal_submission_state_not_a_duplicate_retry(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "under-review-video")
    publication = db.create_douyin_publication(
        "under-review-video", "0" * 64, "/tmp/review.mp4", source_kind="HISTORY"
    )
    assert db.update_douyin_publication_state(publication["id"], "UNDER_REVIEW")

    assert db.get_douyin_publication("under-review-video")["state"] == "UNDER_REVIEW"
    assert db.claim_next_douyin_history_publication(daily_limit=10) is None


def test_unconfirmed_douyin_failure_is_not_claimed_again(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "maybe-submitted")
    publication = db.create_douyin_publication(
        "maybe-submitted", "1" * 64, "/tmp/maybe.mp4", source_kind="NEW"
    )
    assert db.update_douyin_publication_state(
        publication["id"],
        "RETRYABLE_FAILED",
        error_message="抖音提交后未能在作品管理确认可见；请先人工核对，勿切换视频。",
    )

    assert db.claim_next_douyin_publication("NEW") is None


def test_douyin_new_video_claim_is_not_limited_by_historical_daily_quota(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "new-video")
    publication = db.create_douyin_publication(
        "new-video", "e" * 64, "/tmp/new.mp4", source_kind="NEW"
    )

    claimed = db.claim_next_douyin_publication("NEW")

    assert claimed is not None
    assert claimed["id"] == publication["id"]
    assert claimed["youtube_id"] == "new-video"

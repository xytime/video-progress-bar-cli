"""快手浏览器发布账本：仅发布成功去重、迁移限额和不确定结果保护。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-15 | Codex | 覆盖快手账本去重、迁移限额和审核状态 |
| 1.1.0 | 2026-07-16 | Codex | 覆盖视频号延后发布任务的原子领取与黑名单保护 |
| 1.2.0 | 2026-07-25 | Codex | 覆盖取消状态为历史补录自动重试终态与多尝试账本迁移 |
| 1.3.0 | 2026-07-26 | Codex | 覆盖快手上传前审查命中时取消平台任务且不调用上传器 |
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager


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


def test_canceled_history_publication_is_not_claimed_again(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "missing-assets-video")
    publication = db.create_kuaishou_publication(
        "missing-assets-video", "6" * 64, "/tmp/missing.mp4", source_kind="HISTORY"
    )
    assert db.update_kuaishou_publication_state(
        publication["id"], "CANCELED", error_message="本地投递产物缺失"
    )

    assert db.get_kuaishou_publication("missing-assets-video")["state"] == "CANCELED"
    assert db.claim_next_kuaishou_history_publication(daily_limit=10) is None


def test_kuaishou_publication_censorship_hit_cancels_without_upload(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    (tmp_path / "video-id_vertical.mp4").write_bytes(b"video")
    (tmp_path / "video-id_kuaishou_copy.txt").write_text("涉及中国工程师遇袭的敏感文案", encoding="utf-8")
    manager.db = MagicMock()
    manager.db.get_video_by_youtube_id.return_value = {
        "title": "测试视频",
        "zh_title": "测试标题",
    }
    manager._check_censorship = MagicMock(return_value=True)
    manager._run_tracked = MagicMock()

    assert not manager._publish_claimed_kuaishou_publication(
        {"id": 191, "youtube_id": "video-id", "slice_index": 0, "source_kind": "HISTORY"}
    )

    manager._run_tracked.assert_not_called()
    manager.db.update_kuaishou_publication_state.assert_called_once()
    args, kwargs = manager.db.update_kuaishou_publication_state.call_args
    assert args == (191, "CANCELED")
    assert "上传前内容安全审查拦截" in kwargs["error_message"]
    manager._check_censorship.assert_called_once()


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


def test_ledger_migration_preserves_multiple_attempt_numbers(tmp_path: Path):
    db_path = tmp_path / "pipeline.db"
    db = PipelineDB(str(db_path))
    _add_video(db, "multi-attempt")
    video_id = db.get_video_by_youtube_id("multi-attempt")["id"]
    old_schema = '''
        CREATE TABLE kuaishou_publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            asset_sha256 TEXT NOT NULL,
            source_kind TEXT NOT NULL CHECK(source_kind IN ('HISTORY', 'NEW')),
            state TEXT NOT NULL DEFAULT 'QUEUED'
                CHECK(state IN ('QUEUED', 'UPLOADING', 'DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETRYABLE_FAILED', 'UNCERTAIN', 'BANNED')),
            video_path TEXT NOT NULL,
            attempt_number INTEGER NOT NULL DEFAULT 1,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            claimed_at TIMESTAMP DEFAULT NULL,
            published_at TIMESTAMP DEFAULT NULL,
            external_post_id TEXT DEFAULT NULL,
            external_url TEXT DEFAULT NULL,
            last_error_message TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(video_id, attempt_number)
        )
    '''
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE kuaishou_publications")
        conn.execute(old_schema)
        conn.execute(
            "INSERT INTO kuaishou_publications (video_id, asset_sha256, source_kind, state, video_path, attempt_number) VALUES (?, ?, 'HISTORY', 'RETRYABLE_FAILED', '/tmp/one.mp4', 1)",
            (video_id, "a" * 64),
        )
        conn.execute(
            "INSERT INTO kuaishou_publications (video_id, asset_sha256, source_kind, state, video_path, attempt_number) VALUES (?, ?, 'HISTORY', 'PUBLISHED', '/tmp/two.mp4', 2)",
            (video_id, "b" * 64),
        )

    migrated = PipelineDB(str(db_path))

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT state, attempt_number FROM kuaishou_publications ORDER BY attempt_number"
        ).fetchall()
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'kuaishou_publications'"
        ).fetchone()[0]
    assert rows == [("RETRYABLE_FAILED", 1), ("PUBLISHED", 2)]
    assert "CANCELED" in schema
    assert migrated.update_kuaishou_publication_state(1, "CANCELED")


def test_deferred_wechat_publication_is_claimed_once_and_blacklist_is_never_released(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "deferred-video")
    _add_video(db, "blocked-deferred")
    db.update_video_status("deferred-video", "WECHAT_DEFERRED")
    db.update_video_status("blocked-deferred", "WECHAT_DEFERRED")
    assert db.add_to_blacklist("blocked-deferred", "wechat_takedown_prohibited")

    claimed = db.claim_next_deferred_wechat_publication()

    assert claimed is not None
    assert claimed["youtube_id"] == "deferred-video"
    assert db.get_video_by_youtube_id("deferred-video")["status"] == "DOWNLOADING"
    assert db.claim_next_deferred_wechat_publication() is None

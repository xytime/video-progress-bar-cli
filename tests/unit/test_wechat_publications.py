"""视频号后台确认账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-10 | Codex | 覆盖后台列表证据落账、待核验状态和面板聚合优先级 |
| 1.1.0 | 2026-08-11 | Codex | 覆盖提交受理的 UNDER_REVIEW 状态，不将截图等同公开发布 |
| 1.2.0 | 2026-08-11 | Codex | 覆盖视频号未最终确认时取消下游未提交队列，避免跨平台抢跑 |
"""

from __future__ import annotations

import sqlite3

import pytest

from video_processing.db.database import PipelineDB


def _add_video(db: PipelineDB, youtube_id: str = "wechat-ledger") -> None:
    assert db.add_video(youtube_id, "Title", "channel", score=80)
    db.update_video_status(youtube_id, "PUBLISHED")


def test_wechat_confirmation_requires_post_list_evidence(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db)

    with pytest.raises(ValueError, match="requires post-list evidence"):
        db.record_wechat_publication_confirmation("wechat-ledger", evidence_path=None)


def test_wechat_confirmation_is_upserted_and_preferred_by_platform_map(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db)
    evidence = tmp_path / "post_list_after_submission.png"
    evidence.write_bytes(b"png")

    first = db.record_wechat_publication_confirmation(
        "wechat-ledger", evidence_path=str(evidence),
    )
    second = db.record_wechat_publication_confirmation(
        "wechat-ledger", evidence_path=str(evidence),
    )

    assert first["id"] == second["id"]
    assert second["state"] == "PUBLISHED"
    video = db.get_video_by_youtube_id("wechat-ledger")
    publications = db.get_video_publications_map([video["id"]])
    assert publications[video["id"]]["wechat"]["state"] == "PUBLISHED"
    assert publications[video["id"]]["wechat"]["published_at"] is not None
    assert publications[video["id"]]["wechat"]["error"] is None


def test_wechat_uncertain_confirmation_is_visible_in_platform_map(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "wechat-uncertain")
    reason = "提交后后台列表截图未落盘；禁止自动重传。"

    db.record_wechat_publication_confirmation(
        "wechat-uncertain",
        evidence_path=None,
        state="UNCERTAIN",
        error_message=reason,
    )

    video = db.get_video_by_youtube_id("wechat-uncertain")
    publications = db.get_video_publications_map([video["id"]])
    assert publications[video["id"]]["wechat"]["state"] == "UNCERTAIN"
    assert publications[video["id"]]["wechat"]["published_at"] is None
    assert publications[video["id"]]["wechat"]["error"] == reason


def test_wechat_submission_evidence_is_under_review_not_published(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "wechat-under-review")
    evidence = tmp_path / "post_list_after_submission.png"
    evidence.write_bytes(b"png")

    publication = db.record_wechat_publication_confirmation(
        "wechat-under-review",
        evidence_path=str(evidence),
        state="UNDER_REVIEW",
        error_message="平台已受理提交，等待作品管理页确认公开发布。",
    )

    assert publication["state"] == "UNDER_REVIEW"
    assert publication["confirmed_at"] is None
    video = db.get_video_by_youtube_id("wechat-under-review")
    publications = db.get_video_publications_map([video["id"]])
    assert publications[video["id"]]["wechat"]["state"] == "UNDER_REVIEW"
    assert publications[video["id"]]["wechat"]["published_at"] is None


def test_legacy_wechat_ledger_is_migrated_for_under_review(tmp_path):
    db_path = tmp_path / "pipeline.db"
    db = PipelineDB(str(db_path))
    _add_video(db, "wechat-legacy")
    video = db.get_video_by_youtube_id("wechat-legacy")

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_wechat_publications_state")
        conn.execute("DROP TABLE wechat_publications")
        conn.execute('''
            CREATE TABLE wechat_publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL UNIQUE,
                state TEXT NOT NULL CHECK(state IN ('PUBLISHED', 'UNCERTAIN')),
                evidence_path TEXT DEFAULT NULL,
                confirmed_at TIMESTAMP DEFAULT NULL,
                last_error_message TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
            )
        ''')
        conn.execute(
            "INSERT INTO wechat_publications (video_id, state, evidence_path, confirmed_at) VALUES (?, 'PUBLISHED', 'proof.png', CURRENT_TIMESTAMP)",
            (video["id"],),
        )

    migrated = PipelineDB(str(db_path))
    publication = migrated.record_wechat_publication_confirmation(
        "wechat-legacy",
        evidence_path="proof.png",
        state="UNDER_REVIEW",
        error_message="旧提交截图无最终公开证明。",
    )

    assert publication["state"] == "UNDER_REVIEW"
    assert publication["confirmed_at"] is None


def test_unconfirmed_wechat_cancels_only_queued_downstream_publications(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "wechat-upstream")
    queued = db.create_douyin_publication(
        "wechat-upstream", "d" * 64, "/tmp/queued.mp4", source_kind="NEW"
    )
    under_review = db.create_kuaishou_publication(
        "wechat-upstream", "e" * 64, "/tmp/review.mp4", source_kind="NEW"
    )
    assert db.update_kuaishou_publication_state(under_review["id"], "UNDER_REVIEW")

    canceled = db.cancel_queued_downstream_publications_for_unconfirmed_wechat(
        "wechat-upstream", reason="视频号尚未确认公开发布。"
    )

    assert canceled == {"kuaishou": 0, "douyin": 1}
    assert db.get_douyin_publication("wechat-upstream")["id"] == queued["id"]
    assert db.get_douyin_publication("wechat-upstream")["state"] == "CANCELED"
    assert db.get_kuaishou_publication("wechat-upstream")["state"] == "UNDER_REVIEW"

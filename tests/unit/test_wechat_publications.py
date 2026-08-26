"""视频号后台确认账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-10 | Codex | 覆盖后台列表证据落账、待核验状态和面板聚合优先级 |
| 1.1.0 | 2026-08-11 | Codex | 覆盖提交受理的 UNDER_REVIEW 状态，不将截图等同公开发布 |
| 1.2.0 | 2026-08-11 | Codex | 覆盖视频号未最终确认时取消下游未提交队列，避免跨平台抢跑 |
| 1.4.0 | 2026-08-20 | Codex | 覆盖已提交未绑定、唯一平台 ID 绑定和同一证据幂等尝试记录 |
| 1.5.0 | 2026-08-20 | Codex | 覆盖旧视频号提交尝试迁移到通用发布主体 |
| 1.7.0 | 2026-08-21 | Codex | 覆盖未绑定提交在平台矩阵中作为不可重发待核验状态展示 |
| 1.8.0 | 2026-08-26 | Codex | 覆盖受理账本、尝试与任务状态同事务落盘及历史分叉修复。 |
| 1.6.0 | 2026-08-20 | Codex | 覆盖旧库缺少 Highlight 表时的发布主体迁移顺序 |
| 1.3.0 | 2026-08-20 | Codex | 覆盖作品管理页明确驳回和未找到的终结账本状态 |
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


def test_unbound_submission_is_visible_but_never_reported_as_published(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "wechat-unbound")
    db.record_wechat_publication_confirmation(
        "wechat-unbound",
        evidence_path=None,
        state="SUBMITTED_UNBOUND",
        error_message="平台已接收提交；禁止自动重传。",
    )

    video = db.get_video_by_youtube_id("wechat-unbound")
    state = db.get_video_publications_map([video["id"]])[video["id"]]["wechat"]

    assert state["state"] == "SUBMITTED_UNBOUND"
    assert state["published_at"] is None


def test_submission_acceptance_is_atomic_and_repairs_prior_status_divergence(tmp_path):
    """受理后任务状态必须与不可重传账本一起持久化，历史 FAILED 分叉也可原地修复。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "wechat-atomic")

    accepted = db.record_wechat_submission_acceptance(
        "wechat-atomic",
        evidence_path="accepted-proof.png",
        error_message="平台已接收提交；停止自动重传。",
        final_title="唯一标题",
    )

    assert accepted["publication"]["state"] == "SUBMITTED_UNBOUND"
    assert accepted["attempt_id"]
    assert db.get_video_by_youtube_id("wechat-atomic")["status"] == "SUBMITTED_UNBOUND"

    db.update_video_status("wechat-atomic", "FAILED", "模拟旧版本在账本后崩溃")
    assert db.repair_wechat_submission_status_divergence() == 1
    assert db.get_video_by_youtube_id("wechat-atomic")["status"] == "SUBMITTED_UNBOUND"


def test_submitted_bound_requires_platform_id_and_attempt_binding_is_idempotent(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "wechat-bound")
    evidence = tmp_path / "post_list_after_submission.png"
    evidence.write_bytes(b"png")

    with pytest.raises(ValueError, match="requires platform_post_id"):
        db.record_wechat_publication_confirmation(
            "wechat-bound", evidence_path=str(evidence), state="SUBMITTED_BOUND",
        )

    publication = db.record_wechat_publication_confirmation(
        "wechat-bound", evidence_path=str(evidence), state="SUBMITTED_BOUND",
        platform_post_id="wechat-post-001", platform_url="https://example.test/post/001",
    )
    first_attempt = db.record_wechat_submission_attempt(
        "wechat-bound", evidence_path=str(evidence), final_title="唯一标题",
    )
    repeated_attempt = db.record_wechat_submission_attempt(
        "wechat-bound", evidence_path=str(evidence), final_title="唯一标题",
    )
    bound = db.bind_wechat_submission_attempt_platform_id(
        first_attempt["attempt_id"], platform_post_id="wechat-post-001",
    )

    assert publication["state"] == "SUBMITTED_BOUND"
    assert repeated_attempt["attempt_id"] == first_attempt["attempt_id"]
    assert bound["state"] == "PLATFORM_ID_BOUND"
    assert bound["platform_post_id"] == "wechat-post-001"


@pytest.mark.parametrize("state", ["REJECTED", "NOT_FOUND"])
def test_wechat_management_terminal_nonpublished_states_require_evidence(tmp_path, state):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, f"wechat-{state.lower()}")
    evidence = tmp_path / f"management_{state.lower()}.png"
    evidence.write_bytes(b"png")

    publication = db.record_wechat_publication_confirmation(
        f"wechat-{state.lower()}",
        evidence_path=str(evidence),
        state=state,
        error_message="作品管理页明确回查结果。",
        reconciled=True,
    )

    assert publication["state"] == state
    assert publication["confirmed_at"] is None
    assert publication["last_reconciled_at"] is not None


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


def test_legacy_wechat_submission_attempt_is_migrated_to_video_subject(tmp_path):
    db_path = tmp_path / "pipeline.db"
    db = PipelineDB(str(db_path))
    _add_video(db, "wechat-attempt-legacy")
    video = db.get_video_by_youtube_id("wechat-attempt-legacy")

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE wechat_submission_attempts")
        conn.execute('''
            CREATE TABLE wechat_submission_attempts (
                attempt_id TEXT PRIMARY KEY,
                video_id INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND')),
                final_title TEXT NOT NULL,
                final_title_sha256 TEXT DEFAULT NULL,
                video_sha256 TEXT DEFAULT NULL,
                cover_sha256 TEXT DEFAULT NULL,
                evidence_path TEXT DEFAULT NULL,
                platform_post_id TEXT DEFAULT NULL UNIQUE,
                platform_url TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                bound_at TIMESTAMP DEFAULT NULL,
                FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE CASCADE
            )
        ''')
        conn.execute(
            '''INSERT INTO wechat_submission_attempts
               (attempt_id, video_id, state, final_title, evidence_path)
               VALUES ('legacy-attempt', ?, 'SUBMITTED_UNBOUND', '旧标题', 'legacy-proof.png')''',
            (video["id"],),
        )

    migrated = PipelineDB(str(db_path))
    with migrated.get_connection() as conn:
        row = conn.execute(
            "SELECT subject_id, video_id FROM wechat_submission_attempts WHERE attempt_id = 'legacy-attempt'"
        ).fetchone()

    assert dict(row) == {"subject_id": f"video:{video['id']}", "video_id": video["id"]}


def test_legacy_migration_creates_highlight_parents_before_subject_ledger(tmp_path):
    db_path = tmp_path / "pipeline.db"
    db = PipelineDB(str(db_path))
    _add_video(db, "wechat-old-no-highlight")
    video = db.get_video_by_youtube_id("wechat-old-no-highlight")

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP TABLE wechat_submission_attempts")
        conn.execute("DROP TABLE wechat_publications")
        conn.execute("DROP TABLE publication_subjects")
        conn.execute("DROP TABLE highlight_clips")
        conn.execute("DROP TABLE highlight_jobs")
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
            "INSERT INTO wechat_publications (video_id, state) VALUES (?, 'UNCERTAIN')", (video["id"],)
        )

    migrated = PipelineDB(str(db_path))
    publication = migrated.get_wechat_publication("wechat-old-no-highlight")

    assert publication["state"] == "UNCERTAIN"
    assert publication["subject_id"] == f"video:{video['id']}"


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

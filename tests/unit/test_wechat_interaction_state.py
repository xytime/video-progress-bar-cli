"""视频号互动账本安全状态机回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-09-20 | Codex | 覆盖无提交意图的草稿修订审计，并拒绝修改已进入提交边界的评论。 |
| 1.2.0 | 2026-09-20 | Codex | 覆盖人工批量候选按上传记录时间排序，并严格排除已有互动账本。 |
| 1.1.0 | 2026-09-19 | Codex | 固定人工“最新视频”查询不因已有互动账本回退到旧作品。 |
| 1.0.0 | 2026-09-19 | Codex | 覆盖非空旧表迁移、原子 lease、提交意图、终态和有界退避。 |
"""

from __future__ import annotations

import datetime
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from video_processing.db.database import PipelineDB


UTC = datetime.timezone.utc


def _published_target(db: PipelineDB, tmp_path: Path, suffix: str = "one") -> dict:
    yid = f"yt_interaction_{suffix}"
    post_id = f"export/post_{suffix}"
    db.add_video(yid, f"Title {suffix}", "channel_test", score=80)
    evidence = tmp_path / f"{suffix}.png"
    evidence.write_bytes(b"evidence")
    return db.record_wechat_publication_confirmation(
        yid,
        evidence_path=str(evidence),
        state="PUBLISHED",
        platform_post_id=post_id,
    )


@pytest.mark.parametrize("with_late_columns", [False, True])
def test_nonempty_legacy_schema_migrates_idempotently_and_preserves_index(
    tmp_path: Path, with_late_columns: bool
) -> None:
    db_path = tmp_path / "legacy.db"
    db = PipelineDB(db_path=str(db_path))
    publication = _published_target(db, tmp_path, "legacy")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE wechat_interactions")
        late_columns = (
            ", attempt_count INTEGER DEFAULT 1, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            if with_late_columns else ""
        )
        conn.execute(f'''
            CREATE TABLE wechat_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publication_id INTEGER NOT NULL,
                platform_post_id TEXT NOT NULL UNIQUE,
                interaction_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                comment_text TEXT NOT NULL,
                status TEXT NOT NULL,
                evidence_path TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                commented_at TIMESTAMP
                {late_columns},
                FOREIGN KEY(publication_id) REFERENCES wechat_publications(id) ON DELETE CASCADE
            )
        ''')
        conn.execute(
            "CREATE INDEX legacy_interaction_provider_idx ON wechat_interactions(provider)"
        )
        columns = (
            "publication_id, platform_post_id, interaction_type, provider, "
            "comment_text, status"
        )
        conn.execute(
            f"INSERT INTO wechat_interactions ({columns}) VALUES (?, ?, ?, ?, ?, ?)",
            (
                publication["id"], "export/post_legacy", "POLL_STAND",
                "legacy", "stable legacy comment", "PENDING_REVIEW",
            ),
        )

    migrated = PipelineDB(db_path=str(db_path))
    row = migrated.get_wechat_interaction_by_post_id("export/post_legacy")
    assert row is not None
    assert row["status"] == "UNCERTAIN"
    assert row["comment_text"] == "stable legacy comment"
    assert row["max_attempts"] == 5
    with sqlite3.connect(db_path) as conn:
        index_names = {
            item[0] for item in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='wechat_interactions'"
            )
        }
        foreign_keys = list(conn.execute("PRAGMA foreign_key_list(wechat_interactions)"))
    assert "legacy_interaction_provider_idx" in index_names
    assert any(item[2] == "wechat_publications" for item in foreign_keys)
    PipelineDB(db_path=str(db_path))  # 二次初始化不应重复迁移或丢数据
    assert migrated.get_wechat_interaction_by_post_id("export/post_legacy")["status"] == "UNCERTAIN"


def test_legacy_migration_failure_rolls_back_without_legacy_artifact(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback.db"
    PipelineDB(db_path=str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DROP TABLE wechat_interactions")
        conn.execute('''
            CREATE TABLE wechat_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publication_id INTEGER NOT NULL,
                platform_post_id TEXT NOT NULL UNIQUE,
                interaction_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                comment_text TEXT NOT NULL,
                status TEXT NOT NULL,
                evidence_path TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                commented_at TIMESTAMP,
                FOREIGN KEY(publication_id) REFERENCES wechat_publications(id) ON DELETE CASCADE
            )
        ''')
        conn.execute(
            '''INSERT INTO wechat_interactions (
                   publication_id, platform_post_id, interaction_type,
                   provider, comment_text, status
               ) VALUES (999999, 'export/bad_fk', 'POLL_STAND', 'legacy', 'text', 'PENDING')'''
        )

    with pytest.raises(sqlite3.IntegrityError):
        PipelineDB(db_path=str(db_path))
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        row = conn.execute(
            "SELECT status FROM wechat_interactions WHERE platform_post_id='export/bad_fk'"
        ).fetchone()
    assert "wechat_interactions" in tables
    assert "wechat_interactions_legacy" not in tables
    assert row == ("PENDING",)


def test_submit_intent_expiry_becomes_verify_only_and_terminal_is_immutable(tmp_path: Path) -> None:
    db = PipelineDB(db_path=str(tmp_path / "state.db"))
    publication = _published_target(db, tmp_path)
    start = datetime.datetime(2026, 9, 19, 1, 0, tzinfo=UTC)
    queued = db.queue_wechat_interaction(
        publication_id=publication["id"],
        platform_post_id="export/post_one",
        interaction_type="POLL_STAND",
        provider="rule",
        comment_text="persisted comment",
        now=start,
    )
    claimed = db.claim_due_wechat_interaction(now=start, platform_post_id="export/post_one")
    assert claimed and claimed["status"] == "CLAIMED"
    assert db.mark_wechat_interaction_submit_intent(
        queued["id"], claimed["lease_token"], now=start
    )

    expired = start + datetime.timedelta(minutes=4)
    verify_claim = db.claim_due_wechat_interaction(
        now=expired, platform_post_id="export/post_one"
    )
    assert verify_claim and verify_claim["status"] == "UNCERTAIN"
    assert verify_claim["verify_only"] is True
    assert verify_claim["comment_text"] == "persisted comment"
    final = db.finish_wechat_interaction_attempt(
        queued["id"], verify_claim["lease_token"],
        result_status="COMMENTED", now=expired,
    )
    assert final["status"] == "COMMENTED"

    db.record_wechat_interaction(
        publication_id=publication["id"], platform_post_id="export/post_one",
        interaction_type="WARNING_SHARE", provider="other",
        comment_text="replacement must not win", status="PENDING",
    )
    immutable = db.get_wechat_interaction_by_post_id("export/post_one")
    assert immutable["status"] == "COMMENTED"
    assert immutable["comment_text"] == "persisted comment"


def test_pre_submit_draft_revision_keeps_audit_and_refuses_submit_intent(tmp_path: Path) -> None:
    db = PipelineDB(db_path=str(tmp_path / "revision.db"))
    publication = _published_target(db, tmp_path, "revision")
    start = datetime.datetime(2026, 9, 20, 1, 0, tzinfo=UTC)
    queued = db.queue_wechat_interaction(
        publication_id=publication["id"],
        platform_post_id="export/revision_post",
        interaction_type="POLL_STAND",
        provider="agy:old",
        comment_text="原始草稿",
        now=start,
    )

    revised = db.revise_wechat_interaction_before_submit(
        platform_post_id="export/revision_post",
        interaction_type="POLL_STAND",
        provider="rule:current",
        comment_text="新的短草稿",
        reason="人工确认短格式修订",
        now=start,
    )
    assert revised and revised["comment_text"] == "新的短草稿"
    assert revised["provider"] == "rule:current"
    with db.get_connection() as conn:
        revision = conn.execute(
            """SELECT previous_comment_text, replacement_comment_text
               FROM wechat_interaction_draft_revisions WHERE interaction_id = ?""",
            (queued["id"],),
        ).fetchone()
    assert tuple(revision) == ("原始草稿", "新的短草稿")

    claimed = db.claim_due_wechat_interaction(now=start, platform_post_id="export/revision_post")
    assert claimed
    assert db.mark_wechat_interaction_submit_intent(queued["id"], claimed["lease_token"], now=start)
    assert db.revise_wechat_interaction_before_submit(
        platform_post_id="export/revision_post",
        interaction_type="POLL_STAND",
        provider="rule:later",
        comment_text="不得替换",
        reason="必须拒绝",
        now=start,
    ) is None


def test_claim_is_atomic_and_expired_pre_submit_lease_is_safely_reclaimable(tmp_path: Path) -> None:
    db_path = tmp_path / "atomic.db"
    db = PipelineDB(db_path=str(db_path))
    publication = _published_target(db, tmp_path, "atomic")
    start = datetime.datetime(2026, 9, 19, 1, 30, tzinfo=UTC)
    db.queue_wechat_interaction(
        publication_id=publication["id"], platform_post_id="export/post_atomic",
        interaction_type="POLL_STAND", provider="rule",
        comment_text="atomic stable comment", now=start,
    )

    def claim_once() -> dict | None:
        separate = PipelineDB(db_path=str(db_path))
        return separate.claim_due_wechat_interaction(
            now=start, platform_post_id="export/post_atomic"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _index: claim_once(), range(2)))
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    assert winners[0]["verify_only"] is False

    reclaimed = db.claim_due_wechat_interaction(
        now=start + datetime.timedelta(minutes=4),
        platform_post_id="export/post_atomic",
    )
    assert reclaimed is not None
    assert reclaimed["status"] == "CLAIMED"
    assert reclaimed["verify_only"] is False
    assert reclaimed["lease_token"] != winners[0]["lease_token"]


def test_legacy_status_update_cannot_take_over_active_lease_without_token(tmp_path: Path) -> None:
    db = PipelineDB(db_path=str(tmp_path / "legacy_token_guard.db"))
    publication = _published_target(db, tmp_path, "legacy-token")
    now = datetime.datetime(2026, 9, 19, 1, 45, tzinfo=UTC)
    db.queue_wechat_interaction(
        publication_id=publication["id"],
        platform_post_id="export/post_legacy_token",
        interaction_type="POLL_STAND",
        provider="rule",
        comment_text="lease-owned comment",
        now=now,
    )
    claimed = db.claim_due_wechat_interaction(
        now=now, platform_post_id="export/post_legacy_token"
    )
    assert claimed is not None

    with pytest.raises(ValueError, match="lease_token"):
        db.update_wechat_interaction_status(
            "export/post_legacy_token", "COMMENTED"
        )

    unchanged = db.get_wechat_interaction_by_post_id("export/post_legacy_token")
    assert unchanged["status"] == "CLAIMED"
    assert unchanged["lease_token"] == claimed["lease_token"]


def test_pre_submit_failure_uses_exponential_due_time_and_stops_at_five(tmp_path: Path) -> None:
    db = PipelineDB(db_path=str(tmp_path / "backoff.db"))
    publication = _published_target(db, tmp_path, "backoff")
    base = datetime.datetime(2026, 9, 19, 2, 0, tzinfo=UTC)
    row = db.queue_wechat_interaction(
        publication_id=publication["id"], platform_post_id="export/post_backoff",
        interaction_type="POLL_STAND", provider="rule",
        comment_text="same text every retry", now=base,
    )
    now = base
    expected_delays = [60, 120, 240, 480]
    for attempt in range(1, 6):
        claim = db.claim_due_wechat_interaction(
            now=now, platform_post_id="export/post_backoff"
        )
        assert claim and claim["attempt_count"] == attempt
        result = db.finish_wechat_interaction_attempt(
            row["id"], claim["lease_token"], result_status="FAILED",
            error_message="pre-submit failure", now=now,
        )
        assert result["comment_text"] == "same text every retry"
        if attempt < 5:
            assert result["status"] == "RETRY_WAIT"
            due = datetime.datetime.fromisoformat(result["next_attempt_at"])
            assert due == now + datetime.timedelta(seconds=expected_delays[attempt - 1])
            assert db.claim_due_wechat_interaction(
                now=due - datetime.timedelta(microseconds=1),
                platform_post_id="export/post_backoff",
            ) is None
            now = due
        else:
            assert result["status"] == "FAILED"
            assert result["next_attempt_at"] is None
    assert db.claim_due_wechat_interaction(
        now=now + datetime.timedelta(days=1), platform_post_id="export/post_backoff"
    ) is None


def test_latest_published_post_does_not_fall_back_when_latest_has_interaction(
    tmp_path: Path,
) -> None:
    db = PipelineDB(db_path=str(tmp_path / "latest.db"))
    older = _published_target(db, tmp_path, "older")
    newer = _published_target(db, tmp_path, "newer")
    db.queue_wechat_interaction(
        publication_id=newer["id"],
        platform_post_id="export/post_newer",
        interaction_type="POLL_STAND",
        provider="rule",
        comment_text="already persisted for newest",
    )

    latest = db.get_latest_published_wechat_post()

    assert latest is not None
    assert latest["publication_id"] == newer["id"]
    assert latest["platform_post_id"] == "export/post_newer"
    assert latest["interaction_status"] == "QUEUED"
    assert latest["publication_id"] != older["id"]


def test_recent_uninteracted_candidates_follow_upload_record_time(tmp_path: Path) -> None:
    db_path = tmp_path / "batch_candidates.db"
    db = PipelineDB(db_path=str(db_path))
    older = _published_target(db, tmp_path, "batch_older")
    newest = _published_target(db, tmp_path, "batch_newest")
    already_queued = _published_target(db, tmp_path, "batch_queued")
    db.queue_wechat_interaction(
        publication_id=already_queued["id"],
        platform_post_id="export/post_batch_queued",
        interaction_type="POLL_STAND",
        provider="rule",
        comment_text="已有账本的评论不得进入人工批量候选",
    )

    # 造出与自增主键相反的上传记录时间，验证排序不依赖 publication id。
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE wechat_publications SET created_at = ? WHERE id = ?",
            ("2026-09-19 01:00:00", older["id"]),
        )
        conn.execute(
            "UPDATE wechat_publications SET created_at = ? WHERE id = ?",
            ("2026-09-19 03:00:00", newest["id"]),
        )
        conn.execute(
            "UPDATE wechat_publications SET created_at = ? WHERE id = ?",
            ("2026-09-19 04:00:00", already_queued["id"]),
        )

    candidates = db.get_recent_wechat_posts_without_interaction(limit=3)

    assert [item["publication_id"] for item in candidates] == [newest["id"], older["id"]]

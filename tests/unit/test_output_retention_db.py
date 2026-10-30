"""产物清理的只读账本依据，不把缺证据或失败任务当成过期垃圾。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 覆盖只读/WAL、未知 schema、多切片、多平台与产物引用边界 |
"""
import json
import sqlite3

import pytest

from video_processing.db.database import PipelineDB


OLD = "2026-09-01 01:02:03"
RECENT = "2026-10-30 02:03:04"


@pytest.fixture
def db_path(tmp_path):
    """只在隔离 runner 的临时根初始化完整维护 schema。"""
    path = tmp_path / "retention.sqlite"
    PipelineDB(str(path))
    return path


def insert(database_path, table, **values):
    with sqlite3.connect(database_path) as conn:
        columns = ",".join(values)
        cursor = conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in values)})",
            tuple(values.values()),
        )
        return cursor.lastrowid


def video(path, youtube_id="source-one", *, status="COMPLETED", slice_index=0, **extra):
    return insert(path, "processed_videos", youtube_id=youtube_id, slice_index=slice_index,
                  title="test", channel_id="test", status=status, created_at=OLD, updated_at=OLD, **extra)


def publication(path, video_id, *, state="PUBLISHED", post_id="native-one", **extra):
    subject = f"video:{video_id}"
    insert(path, "publication_subjects", id=subject, kind="VIDEO_ITEM", video_id=video_id, created_at=OLD)
    insert(path, "wechat_publications", subject_id=subject, video_id=video_id, state=state,
           platform_post_id=post_id, confirmed_at=OLD, created_at=OLD, updated_at=OLD, **extra)
    return subject


def test_missing_database_is_unknown_and_never_created(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("snapshot must not initialize or migrate")

    monkeypatch.setattr(PipelineDB, "__init__", forbidden)
    monkeypatch.setattr(PipelineDB, "_init_db", forbidden)
    missing = tmp_path / "absent" / "pipeline.db"
    snapshot = PipelineDB.output_retention_snapshot(missing)
    assert snapshot["status"] == "UNKNOWN"
    assert snapshot["unknown_reasons"] == ["DATABASE_UNAVAILABLE:OperationalError"]
    assert not missing.parent.exists()


def test_snapshot_uses_readonly_uri_and_query_only_without_migration(db_path, monkeypatch):
    original_connect = sqlite3.connect
    seen = []
    statements = []

    class RecordingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            statements.append(sql)
            return super().execute(sql, *args, **kwargs)

    def readonly_connect(target, *args, **kwargs):
        seen.append((target, kwargs.copy()))
        return original_connect(target, *args, factory=RecordingConnection, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("instance API must not be used")

    monkeypatch.setattr(PipelineDB, "__init__", forbidden)
    monkeypatch.setattr(PipelineDB, "get_connection", forbidden)
    monkeypatch.setattr(sqlite3, "connect", readonly_connect)
    before = db_path.read_bytes()
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    assert snapshot["status"] == "OK", snapshot["unknown_reasons"]
    assert len(seen) == 1 and seen[0][1]["uri"] is True
    assert seen[0][0].endswith("?mode=ro") and "immutable" not in seen[0][0]
    assert statements[:2] == ["PRAGMA query_only=ON", "BEGIN"]
    assert db_path.read_bytes() == before
    json.dumps(snapshot, allow_nan=False)


def test_committed_wal_is_visible_without_checkpointing(db_path):
    with sqlite3.connect(db_path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO processed_videos (youtube_id,title,channel_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                       ("wal-source", "test", "test", "FAILED", OLD, RECENT))
        writer.commit()
        snapshot = PipelineDB.output_retention_snapshot(db_path)
        assert snapshot["status"] == "OK"
        assert snapshot["sources"]["wal-source"]["terminal"] is False
        assert snapshot["sources"]["wal-source"]["last_activity_at"] == "2026-10-30T02:03:04+00:00"


def test_missing_schema_is_unknown_instead_of_empty_safe_snapshot(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE processed_videos (id INTEGER, youtube_id TEXT, status TEXT)")
        conn.execute("INSERT INTO processed_videos VALUES (1,'legacy','COMPLETED')")
    snapshot = PipelineDB.output_retention_snapshot(path)
    assert snapshot["status"] == "UNKNOWN"
    assert any(reason.startswith("SCHEMA:processed_videos:") for reason in snapshot["unknown_reasons"])
    assert any(reason.startswith("SCHEMA:douyin_publications:") for reason in snapshot["unknown_reasons"])
    assert snapshot["sources"]["legacy"]["terminal"] is False


def test_every_slice_must_be_terminal_and_failed_stays_protected(db_path):
    video(db_path, slice_index=0, vocabulary_json_path="output/source-one/words.json")
    video(db_path, slice_index=1, status="FAILED")
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    source = snapshot["sources"]["source-one"]
    assert snapshot["status"] == "OK"
    assert len(source["slices"]) == 2
    assert source["terminal"] is False
    assert "NONTERMINAL:processed_videos:FAILED" in source["protection_reasons"]
    reference = next(row for row in snapshot["path_references"] if row["column"] == "vocabulary_json_path")
    assert reference["youtube_ids"] == ["source-one"] and reference["protected"] is True


def test_published_requires_native_confirmation_and_all_platforms_finished(db_path):
    first = video(db_path, status="PUBLISHED")
    publication(db_path, first)
    insert(db_path, "douyin_publications", video_id=first, asset_sha256="a", source_kind="HISTORY",
           state="UNCERTAIN", video_path="output/first_vertical.mp4", created_at=OLD, updated_at=RECENT)
    second = video(db_path, "missing-native", status="PUBLISHED")
    publication(db_path, second, post_id=None)
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    assert snapshot["sources"]["source-one"]["terminal"] is False
    assert "NONTERMINAL:douyin_publications:UNCERTAIN" in snapshot["sources"]["source-one"]["protection_reasons"]
    assert snapshot["sources"]["missing-native"]["terminal"] is False
    assert "MISSING_CONFIRMED_WECHAT_PUBLICATION" in snapshot["sources"]["missing-native"]["protection_reasons"]


def test_published_with_review_note_is_still_unconfirmed(db_path):
    first = video(db_path, status="PUBLISHED")
    publication(db_path, first)
    insert(db_path, "kuaishou_publications", video_id=first, asset_sha256="a", source_kind="HISTORY",
           state="PUBLISHED", video_path="output/first_vertical.mp4", external_post_id="kwai-native",
           published_at=OLD, created_at=OLD, updated_at=OLD, last_error_message="等待作品管理回查，尚未确认")
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    assert snapshot["sources"]["source-one"]["terminal"] is False
    assert "last_error_message" not in snapshot["tables"]["kuaishou_publications"][0]


def test_resolved_attempt_does_not_permanently_pin_old_published_assets(db_path):
    first = video(db_path, status="PUBLISHED", vocabulary_json_path="output/old/words.json")
    subject = publication(db_path, first, evidence_path="output/old/publication-evidence.json")
    insert(db_path, "wechat_submission_attempts", attempt_id="attempt-one", video_id=first,
           subject_id=subject, state="PLATFORM_ID_BOUND", final_title="test", platform_post_id="native-one",
           created_at=OLD, bound_at=OLD)
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    assert snapshot["sources"]["source-one"]["terminal"] is True
    assert all(not row["protected"] for row in snapshot["path_references"])
    evidence = next(row for row in snapshot["path_references"] if row["column"] == "evidence_path")
    assert evidence["kind"] == "evidence"  # 年龄/31天证据保留由 core 决定。


def test_maintained_artifacts_inherit_owner_and_unknown_rows_fail_closed(db_path):
    first = video(db_path)
    insert(db_path, "highlight_jobs", id="highlight-one", source_video_id=first, state="CANCELED",
           workspace_path="output/highlight-one", created_at=OLD, updated_at=OLD)
    insert(db_path, "dubbing_jobs", id=99, source_video_id=first, state="CANCELED", requested_platforms="[]",
           model="test-model", voice_id="test-voice", workspace_path="output/dubbing-one", created_at=OLD, updated_at=OLD)
    insert(db_path, "dubbing_artifacts", job_id=99, artifact_kind="video", path="output/dubbing-one/final.mp4", created_at=OLD)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE future_assets (id INTEGER, video_id INTEGER, state TEXT, artifact_path TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO future_assets VALUES (1,?,'RENDERING','output/future/video.mp4',?)", (first, OLD))
        conn.execute("CREATE TABLE orphan_assets (id INTEGER, path TEXT)")
        conn.execute("INSERT INTO orphan_assets VALUES (1,'output/orphan.mp4')")
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    refs = {row["path"]: row for row in snapshot["path_references"]}
    assert refs["output/dubbing-one/final.mp4"]["youtube_ids"] == ["source-one"]
    assert refs["output/highlight-one"]["youtube_ids"] == ["source-one"]
    assert refs["output/future/video.mp4"]["protected"] is True
    assert refs["output/orphan.mp4"]["protected"] is True
    assert refs["output/orphan.mp4"]["reason"] == "UNKNOWN_OWNER"
    assert snapshot["sources"]["source-one"]["terminal"] is False


def test_missing_activity_time_never_becomes_terminal(db_path):
    video(db_path, status="COMPLETED")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE processed_videos SET created_at=NULL,updated_at=NULL")
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    source = snapshot["sources"]["source-one"]
    assert source["terminal"] is False
    assert "UNKNOWN_TIME:processed_videos" in source["protection_reasons"]


def test_invalid_updated_at_cannot_fall_back_to_old_creation_time(db_path):
    video(db_path, vocabulary_json_path="output/source-one/words.json")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE processed_videos SET updated_at='damaged-time'")
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    source = snapshot["sources"]["source-one"]
    assert source["terminal"] is False
    assert "UNKNOWN_TIME:processed_videos" in source["protection_reasons"]
    assert all(row["protected"] for row in snapshot["path_references"])


def test_english_world_douyin_uses_its_maintained_reconciliation_contract(db_path):
    video(db_path)
    insert(db_path, "english_world_review_items", id="review-one", state="UNDER_REVIEW",
           artifact_sha256="ew-asset", title="test", source_youtube_id="source-one",
           mp4_path="output/ew/final.mp4", manifest_path="output/ew/manifest.json",
           title_path="output/ew/title.txt", copy_path="output/ew/copy.txt",
           cover_path="output/ew/cover.png", cover_provenance_path="output/ew/cover.json",
           platform_state="PUBLISHED", platform_post_id="wechat-ew", last_reconciled_at=OLD,
           created_at=OLD, updated_at=OLD)
    insert(db_path, "english_world_douyin_publications", review_id="review-one", state="UNDER_REVIEW",
           artifact_sha256="ew-asset", platform_state="UNDER_REVIEW", evidence_dir="output/ew/douyin-evidence",
           created_at=OLD, updated_at=OLD)
    assert PipelineDB.output_retention_snapshot(db_path)["sources"]["source-one"]["terminal"] is False
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE english_world_douyin_publications SET state='PUBLISHED',platform_state='PUBLISHED',published_at=?,last_reconciled_at=?",
                     (OLD, OLD))
    snapshot = PipelineDB.output_retention_snapshot(db_path)
    assert snapshot["status"] == "OK", snapshot["unknown_reasons"]
    assert snapshot["sources"]["source-one"]["terminal"] is True
    assert all(not row["protected"] for row in snapshot["path_references"])

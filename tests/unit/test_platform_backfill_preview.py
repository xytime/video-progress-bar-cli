"""三平台补录预览候选测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-23 | Codex | 覆盖微信/抖音补录预览规则、平台状态排除与日批次切分 |
| 1.1.0 | 2026-07-23 | Codex | 覆盖后台补录预览与确认入队 API |
| 1.2.0 | 2026-07-23 | Codex | 覆盖视频号延后补发领取同样受补录规则约束 |
| 1.3.0 | 2026-08-07 | Codex | 覆盖抖音 CANCELED 账本经显式 API 新建人工恢复尝试 |
| 1.4.0 | 2026-09-02 | Codex | 覆盖仪表盘补录与 CANCELED 重入队遵守阶段化 UI 熔断并 fail-closed |
"""

from pathlib import Path

import pytest

from video_processing.db.database import PipelineDB


def _add_video(
    db: PipelineDB,
    youtube_id: str,
    title: str,
    channel_id: str = "general",
    *,
    status: str = "PUBLISHED",
    upload_date: str = "20260701",
    category: str | None = None,
) -> None:
    assert db.add_video(
        youtube_id,
        title,
        channel_id,
        score=88,
        upload_date=upload_date,
        category=category,
    )
    db.update_video_status(youtube_id, status)


def test_wechat_preview_only_includes_deferred_backfill_candidates(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_channel("wst", "Wall Street Truthbombs")
    _add_video(db, "deferred-wst", "Market shock", "wst", status="WECHAT_DEFERRED", upload_date="20260722")
    _add_video(db, "published-speech", "Full speech at Berkeley", status="PUBLISHED", upload_date="20260720")
    _add_video(db, "old-wst", "Old clip", "wst", status="WECHAT_DEFERRED", upload_date="20260701")

    candidates = db.get_platform_backfill_preview_candidates(
        "wechat",
        wall_street_since_upload_date="20260713",
    )

    assert [row["youtube_id"] for row in candidates] == ["deferred-wst"]
    assert candidates[0]["is_recent_wall_street"] == 1


def test_wechat_deferred_claim_is_limited_to_backfill_rules(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_channel("wst", "Wall Street Truthbombs")
    _add_video(db, "plain-deferred", "Regular market update", status="WECHAT_DEFERRED", upload_date="20260722")
    _add_video(db, "speech-deferred", "A full interview on markets", status="WECHAT_DEFERRED", upload_date="20260720")
    _add_video(db, "wst-deferred", "Market shock", "wst", status="WECHAT_DEFERRED", upload_date="20260722")

    claimed = db.claim_next_deferred_wechat_publication(wall_street_since_upload_date="20260713")

    assert claimed is not None
    assert claimed["youtube_id"] in {"speech-deferred", "wst-deferred"}
    assert db.get_video_by_youtube_id("plain-deferred")["status"] == "WECHAT_DEFERRED"
    assert db.get_video_by_youtube_id(claimed["youtube_id"])["status"] == "DOWNLOADING"


def test_douyin_preview_excludes_active_terminal_and_blacklisted_candidates(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "ready-speech", "A full interview with the CEO")
    _add_video(db, "under-review", "Keynote remarks")
    _add_video(db, "retryable", "Lecture on economics")
    _add_video(db, "canceled", "Canceled keynote remarks")
    _add_video(db, "blocked", "Full speech blocked")
    assert db.add_to_blacklist("blocked", "policy")

    under_review = db.create_douyin_publication(
        "under-review", "1" * 64, "/tmp/review.mp4", source_kind="HISTORY"
    )
    assert db.update_douyin_publication_state(under_review["id"], "UNDER_REVIEW")
    retryable = db.create_douyin_publication(
        "retryable", "2" * 64, "/tmp/retry.mp4", source_kind="HISTORY"
    )
    assert db.update_douyin_publication_state(retryable["id"], "RETRYABLE_FAILED")
    canceled = db.create_douyin_publication(
        "canceled", "3" * 64, "/tmp/canceled.mp4", source_kind="HISTORY"
    )
    assert db.update_douyin_publication_state(canceled["id"], "CANCELED")

    candidates = db.get_platform_backfill_preview_candidates(
        "douyin",
        wall_street_since_upload_date="20260713",
    )

    assert [row["youtube_id"] for row in candidates] == ["ready-speech", "retryable"]
    assert candidates[0]["platform_state"] is None
    assert candidates[1]["platform_state"] == "RETRYABLE_FAILED"


def test_wall_street_recent_window_is_independent_from_speech_terms(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_channel("wst", "Wall Street Truthbombs")
    _add_video(db, "plain-wst", "Inflation numbers are moving", "wst", upload_date="20260721")
    _add_video(db, "plain-general", "Inflation numbers are moving", "general", upload_date="20260721")

    candidates = db.get_platform_backfill_preview_candidates(
        "douyin",
        wall_street_since_upload_date="20260713",
    )

    assert [row["youtube_id"] for row in candidates] == ["plain-wst"]
    assert candidates[0]["is_speech_or_interview"] == 0
    assert candidates[0]["is_recent_wall_street"] == 1


def test_preview_batch_split_uses_daily_limit():
    from scripts.platform_backfill_preview import split_batches

    rows = [{"youtube_id": str(index)} for index in range(12)]

    batches = split_batches(rows, 5)

    assert [len(batch) for batch in batches] == [5, 5, 2]


def test_backfill_preview_api_returns_platform_batches(tmp_path: Path, monkeypatch):
    import web.app
    from fastapi.testclient import TestClient

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_channel("wst", "Wall Street Truthbombs")
    _add_video(db, "api-wst", "Market warning", "wst", upload_date="20260722")

    client = TestClient(web.app.app)
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(web.app, "_OUT_DIR", tmp_path)

    response = client.get("/api/platform-backfill/preview?since_upload_date=20260713&douyin_daily_limit=5")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["platforms"]["douyin"]["candidate_count"] == 1
    assert data["platforms"]["douyin"]["batches"][0]["items"][0]["youtube_id"] == "api-wst"


def test_douyin_backfill_queue_api_creates_history_publication(tmp_path: Path, monkeypatch):
    import web.app
    from fastapi.testclient import TestClient

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "api-speech", "A full speech about markets", upload_date="20260720")
    (tmp_path / "api-speech_vertical.mp4").write_bytes(b"video")
    (tmp_path / "api-speech_copy.txt").write_text("文案", encoding="utf-8")
    (tmp_path / "api-speech_title.txt").write_text("标题", encoding="utf-8")

    client = TestClient(web.app.app)
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(web.app, "_OUT_DIR", tmp_path)

    response = client.post(
        "/api/platform-backfill/queue",
        json={"platform": "douyin", "since_upload_date": "20260713", "daily_limit": 5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["queued_count"] == 1
    publication = db.get_douyin_publication("api-speech")
    assert publication["source_kind"] == "HISTORY"
    assert publication["state"] == "QUEUED"


def _activate_douyin_ui_guard(db: PipelineDB, stage: str) -> None:
    for _ in range(2):
        db.record_platform_ui_failure(
            "douyin",
            stage,
            "selector drift",
            recording_threshold=2,
        )


@pytest.mark.parametrize("stage", ["management_verify", "publish_pre_submit", "future_ui_stage"])
def test_douyin_backfill_queue_api_refuses_any_active_ui_guard_before_ledger_write(
    tmp_path: Path,
    monkeypatch,
    stage: str,
):
    """HISTORY 补录会触及作品管理页，任一活动熔断均不得先建账。"""
    import web.app
    from fastapi.testclient import TestClient

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "api-guarded-history", "A full speech about markets", upload_date="20260720")
    (tmp_path / "api-guarded-history_vertical.mp4").write_bytes(b"video")
    (tmp_path / "api-guarded-history_copy.txt").write_text("文案", encoding="utf-8")
    (tmp_path / "api-guarded-history_title.txt").write_text("标题", encoding="utf-8")
    _activate_douyin_ui_guard(db, stage)

    client = TestClient(web.app.app)
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(web.app, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(web.app.settings, "douyin_ui_failure_recording_threshold", 2)

    response = client.post(
        "/api/platform-backfill/queue",
        json={"platform": "douyin", "since_upload_date": "20260713", "daily_limit": 5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "熔断" in data["error"]
    assert stage in data["error"]
    assert db.get_douyin_publication("api-guarded-history") is None


def test_douyin_requeue_api_creates_new_attempt_from_canceled_record(tmp_path: Path, monkeypatch):
    import web.app
    from fastapi.testclient import TestClient

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "api-requeue", "A full speech about markets", upload_date="20260720")
    video_path = tmp_path / "api-requeue_vertical.mp4"
    video_path.write_bytes(b"video")
    publication = db.create_douyin_publication(
        "api-requeue", "7" * 64, str(video_path), source_kind="NEW"
    )
    assert db.update_douyin_publication_state(publication["id"], "CANCELED")
    client = TestClient(web.app.app)
    monkeypatch.setattr(web.app, "db", db)

    response = client.post("/api/douyin/publications/requeue", json={"publication_id": publication["id"]})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["attempt_number"] == 2
    assert data["state"] == "QUEUED"


@pytest.mark.parametrize(
    ("source_kind", "stage", "allowed"),
    [
        ("NEW", "management_verify", True),
        ("NEW", "publish_pre_submit", False),
        ("NEW", "future_ui_stage", False),
        ("HISTORY", "management_verify", False),
    ],
)
def test_douyin_requeue_api_applies_stage_scoped_ui_guard_before_ledger_write(
    tmp_path: Path,
    monkeypatch,
    source_kind: str,
    stage: str,
    allowed: bool,
):
    """NEW 仅可绕过纯管理页熔断；HISTORY 遇任一活动阶段均停止。"""
    import web.app
    from fastapi.testclient import TestClient

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "api-guarded-requeue", "A full speech about markets", upload_date="20260720")
    video_path = tmp_path / "api-guarded-requeue_vertical.mp4"
    video_path.write_bytes(b"video")
    publication = db.create_douyin_publication(
        "api-guarded-requeue", "8" * 64, str(video_path), source_kind=source_kind
    )
    assert db.update_douyin_publication_state(publication["id"], "CANCELED")
    _activate_douyin_ui_guard(db, stage)

    client = TestClient(web.app.app)
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(web.app.settings, "douyin_ui_failure_recording_threshold", 2)

    response = client.post(
        "/api/douyin/publications/requeue",
        json={"publication_id": publication["id"]},
    )

    assert response.status_code == 200
    data = response.json()
    current = db.get_douyin_publication("api-guarded-requeue")
    if allowed:
        assert data["success"] is True
        assert current["attempt_number"] == 2
        assert current["state"] == "QUEUED"
    else:
        assert data["success"] is False
        assert "熔断" in data["error"]
        assert stage in data["error"]
        assert current["attempt_number"] == 1
        assert current["state"] == "CANCELED"


def test_douyin_backfill_queue_api_fails_closed_when_ui_guard_read_errors(tmp_path: Path, monkeypatch):
    """熔断账本无法读取时，不得以不可知状态继续创建 HISTORY 记录。"""
    import web.app
    from fastapi.testclient import TestClient

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "api-guard-read-error", "A full speech about markets", upload_date="20260720")
    (tmp_path / "api-guard-read-error_vertical.mp4").write_bytes(b"video")
    (tmp_path / "api-guard-read-error_copy.txt").write_text("文案", encoding="utf-8")
    (tmp_path / "api-guard-read-error_title.txt").write_text("标题", encoding="utf-8")

    def fail_read(_platform: str):
        raise RuntimeError("temporary database failure")

    monkeypatch.setattr(db, "get_platform_ui_failure_streaks", fail_read)
    client = TestClient(web.app.app)
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(web.app, "_OUT_DIR", tmp_path)

    response = client.post(
        "/api/platform-backfill/queue",
        json={"platform": "douyin", "since_upload_date": "20260713", "daily_limit": 5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "无法读取" in data["error"]
    assert db.get_douyin_publication("api-guard-read-error") is None


def test_douyin_requeue_api_fails_closed_when_ui_guard_format_is_invalid(tmp_path: Path, monkeypatch):
    """熔断账本格式异常时，不得新建 CANCELED 的下一次尝试。"""
    import web.app
    from fastapi.testclient import TestClient

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "api-guard-malformed", "A full speech about markets", upload_date="20260720")
    video_path = tmp_path / "api-guard-malformed_vertical.mp4"
    video_path.write_bytes(b"video")
    publication = db.create_douyin_publication(
        "api-guard-malformed", "9" * 64, str(video_path), source_kind="NEW"
    )
    assert db.update_douyin_publication_state(publication["id"], "CANCELED")
    monkeypatch.setattr(db, "get_platform_ui_failure_streaks", lambda _platform: {"stage": "bad"})
    client = TestClient(web.app.app)
    monkeypatch.setattr(web.app, "db", db)

    response = client.post(
        "/api/douyin/publications/requeue",
        json={"publication_id": publication["id"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "格式" in data["error"]
    current = db.get_douyin_publication("api-guard-malformed")
    assert current["attempt_number"] == 1
    assert current["state"] == "CANCELED"


def test_douyin_backfill_queue_api_skips_missing_assets(tmp_path: Path, monkeypatch):
    import web.app
    from fastapi.testclient import TestClient

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "api-missing", "A full lecture about markets", upload_date="20260720")

    client = TestClient(web.app.app)
    monkeypatch.setattr(web.app, "db", db)
    monkeypatch.setattr(web.app, "_OUT_DIR", tmp_path)

    response = client.post(
        "/api/platform-backfill/queue",
        json={"platform": "douyin", "since_upload_date": "20260713", "daily_limit": 5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["queued_count"] == 0
    assert data["skipped_count"] == 1
    assert db.get_douyin_publication("api-missing") is None

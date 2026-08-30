"""抖音浏览器发布账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-23 | Codex | 覆盖抖音账本去重、迁移限额和审核状态 |
| 1.1.0 | 2026-07-25 | Codex | 覆盖提交后未确认的遗留失败不会被自动重投 |
| 1.2.0 | 2026-07-29 | Codex | 覆盖含未确认反证的抖音 PUBLISHED 写入会保守降级且不参与去重 |
| 1.3.0 | 2026-08-07 | Codex | 覆盖发布前闸门和页面校准旧失败的安全停用迁移 |
| 1.4.0 | 2026-08-07 | Codex | 覆盖 CANCELED 抖音账本人工重入队且保留历史记录 |
| 1.5.0 | 2026-08-08 | Codex | 覆盖缺失抖音投递产物的旧失败在恢复前安全停用 |
| 1.6.0 | 2026-08-08 | Codex | 覆盖 NEW 每日领取上限与跨进程浏览器动作节流账本 |
| 1.7.0 | 2026-08-30 | Codex | 覆盖视频号未确认造成的抖音 shadow 候选且保证不创建任务 |
| 1.8.0 | 2026-08-30 | Codex | 覆盖同阶段 UI 连续失败跨进程累计、录屏阈值和证据化清除审计 |
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


def test_pre_submit_gate_failures_are_canceled_without_touching_review_states(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "pre-submit-gate")
    _add_video(db, "uncalibrated")
    _add_video(db, "missing-assets")
    _add_video(db, "under-review")
    gate = db.create_douyin_publication(
        "pre-submit-gate", "3" * 64, "/tmp/gate.mp4", source_kind="HISTORY"
    )
    calibration = db.create_douyin_publication(
        "uncalibrated", "4" * 64, "/tmp/calibration.mp4", source_kind="HISTORY"
    )
    missing_assets = db.create_douyin_publication(
        "missing-assets", "6" * 64, "/tmp/missing-assets.mp4", source_kind="NEW"
    )
    review = db.create_douyin_publication(
        "under-review", "5" * 64, "/tmp/review.mp4", source_kind="HISTORY"
    )
    assert db.update_douyin_publication_state(
        gate["id"], "RETRYABLE_FAILED", error_message="发布前元信息、封面或自主声明闸门未能确认；本次未提交。"
    )
    assert db.update_douyin_publication_state(
        calibration["id"], "RETRYABLE_FAILED", error_message="抖音上传器尚未完成页面校准；本次没有触发发布。"
    )
    assert db.update_douyin_publication_state(
        missing_assets["id"], "RETRYABLE_FAILED", error_message="抖音投递产物缺失：video=True copy=True title=True cover=False"
    )
    assert db.update_douyin_publication_state(review["id"], "UNDER_REVIEW")

    assert db.cancel_douyin_pre_submit_gate_failures() == 3

    assert db.get_douyin_publication("pre-submit-gate")["state"] == "CANCELED"
    assert db.get_douyin_publication("uncalibrated")["state"] == "CANCELED"
    assert db.get_douyin_publication("missing-assets")["state"] == "CANCELED"
    assert db.get_douyin_publication("under-review")["state"] == "UNDER_REVIEW"
    assert db.cancel_douyin_pre_submit_gate_failures() == 0


def test_canceled_douyin_publication_requeues_as_a_new_attempt(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "requeue-video")
    original = db.create_douyin_publication(
        "requeue-video", "6" * 64, "/tmp/requeue.mp4", source_kind="NEW"
    )
    assert db.update_douyin_publication_state(original["id"], "CANCELED")

    requeued = db.requeue_canceled_douyin_publication(original["id"])

    assert requeued["id"] != original["id"]
    assert requeued["attempt_number"] == 2
    assert requeued["state"] == "QUEUED"
    assert db.get_douyin_publication_by_id(original["id"])["state"] == "CANCELED"


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


def test_douyin_new_video_claim_respects_its_own_daily_quota(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "new-video-one")
    _add_video(db, "new-video-two")
    db.create_douyin_publication("new-video-one", "a" * 64, "/tmp/one.mp4", source_kind="NEW")
    db.create_douyin_publication("new-video-two", "b" * 64, "/tmp/two.mp4", source_kind="NEW")

    first = db.claim_next_douyin_publication("NEW", daily_limit=1)

    assert first is not None
    assert db.claim_next_douyin_publication("NEW", daily_limit=1) is None


def test_douyin_upstream_shadow_is_read_only_and_excludes_other_cancellations(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    for yid in ("blocked-without-ledger", "blocked-canceled", "content-canceled"):
        _add_video(db, yid)
        db.record_wechat_submission_acceptance(
            yid,
            evidence_path=None,
            error_message="视频号已受理，等待公开确认",
            final_title="测试标题",
        )
    upstream = db.create_douyin_publication(
        "blocked-canceled", "8" * 64, "/tmp/upstream.mp4", source_kind="NEW"
    )
    db.update_douyin_publication_state(
        upstream["id"], "CANCELED", error_message="视频号仅确认提交、尚未确认公开发布；已取消下游未提交队列。"
    )
    content = db.create_douyin_publication(
        "content-canceled", "9" * 64, "/tmp/content.mp4", source_kind="NEW"
    )
    db.update_douyin_publication_state(
        content["id"], "CANCELED", error_message="抖音上传前内容安全审查缺少可读字幕正文。"
    )

    snapshot = db.get_douyin_upstream_shadow_snapshot(limit=5)

    assert snapshot["count"] == 2
    assert {row["youtube_id"] for row in snapshot["items"]} == {
        "blocked-without-ledger", "blocked-canceled"
    }
    assert db.get_douyin_publication("blocked-without-ledger") is None
    assert db.get_douyin_publication_by_id(upstream["id"])["state"] == "CANCELED"


def test_douyin_browser_action_slot_persists_the_interval(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))

    assert db.reserve_douyin_browser_action_slot(120, "first", now_epoch=1_000) == 0
    assert db.reserve_douyin_browser_action_slot(120, "second", now_epoch=1_050) == 70
    assert db.reserve_douyin_browser_action_slot(120, "third", now_epoch=1_120) == 0


def test_douyin_ui_failure_streak_persists_and_clears_with_evidence(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))

    first = db.record_platform_ui_failure(
        "douyin", "publish_pre_submit", "未定位自主声明", recording_threshold=2
    )
    second = db.record_platform_ui_failure(
        "douyin",
        "publish_pre_submit",
        "未定位自主声明",
        evidence_path="/tmp/douyin_self_declaration_failed_controls.json",
        recording_threshold=2,
    )

    assert first["consecutive_failures"] == 1
    assert first["recording_requested_at"] is None
    assert second["consecutive_failures"] == 2
    assert second["active"] == 1
    assert second["recording_requested_at"] is not None
    assert second["evidence_path"].endswith("douyin_self_declaration_failed_controls.json")

    assert db.clear_platform_ui_failure_streak(
        "douyin", "publish_pre_submit", "/tmp/douyin_ready_to_submit_controls.json"
    )
    cleared = db.get_platform_ui_failure_streaks("douyin")[0]
    assert cleared["active"] == 0
    assert cleared["consecutive_failures"] == 0
    assert cleared["cleared_at"] is not None
    assert cleared["clear_evidence_path"].endswith("douyin_ready_to_submit_controls.json")

    restarted = db.record_platform_ui_failure(
        "douyin", "publish_pre_submit", "页面再次漂移", recording_threshold=2
    )
    assert restarted["active"] == 1
    assert restarted["consecutive_failures"] == 1

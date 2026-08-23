"""视频号重复提交本地证据防线测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.6.0 | 2026-08-22 | Codex | 已受理视频号任务须附送 Telegram 手机审核成片，且不改变未公开状态。 |
| 1.5.0 | 2026-08-21 | Codex | 历史提交墓碑不得占用视频号延后恢复的每日领取额度。 |
| 1.0.0 | 2026-08-03 | Codex | 覆盖既有视频号提交后证据阻止自动重发并恢复本地已发布态 |
| 1.1.0 | 2026-08-10 | Codex | 补充既有后台截图自动回填视频号确认账本 |
| 1.4.0 | 2026-08-20 | Codex | 覆盖历史归档墓碑：既有截图仍阻止重发，但不得重新生成活跃视频号账本。 |
| 1.3.0 | 2026-08-20 | Codex | 无原生平台 ID 的提交证据进入 SUBMITTED_UNBOUND，禁止标题回查或伪称审核状态。 |
| 1.2.0 | 2026-08-11 | Codex | 提交截图仅进入审核中账本，阻止重复发布但不伪造平台成功 |
"""

from __future__ import annotations

from pathlib import Path

from video_processing.pipeline_manager import PipelineManager


def test_existing_wechat_submission_evidence_blocks_duplicate_publish(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    assert manager.db.add_video("wechat-guard", "Title", "channel", score=90)
    manager.db.update_video_status("wechat-guard", "DOWNLOADING")
    evidence_dir = tmp_path / "wechat_evidence" / "wechat-guard" / "1785719430000000000"
    evidence_dir.mkdir(parents=True)
    evidence = evidence_dir / "post_list_after_submission.png"
    evidence.write_bytes(b"png")
    messages: list[str] = []
    manager.send_telegram_msg = messages.append

    assert manager._block_duplicate_wechat_submission_if_needed("wechat-guard", "wechat-guard") is True

    row = manager.db.get_video_by_youtube_id("wechat-guard")
    assert row["status"] == "SUBMITTED_UNBOUND"
    assert "拒绝自动重发" in row["error_msg"]
    assert str(evidence) in row["error_msg"]
    publication = manager.db.get_wechat_publication("wechat-guard")
    assert publication["state"] == "SUBMITTED_UNBOUND"
    assert publication["evidence_path"] == str(evidence)
    assert messages and "submission accepted" in messages[0]


def test_missing_wechat_submission_evidence_does_not_change_status(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    assert manager.db.add_video("wechat-new", "Title", "channel", score=90)
    manager.db.update_video_status("wechat-new", "DOWNLOADING")

    assert manager._block_duplicate_wechat_submission_if_needed("wechat-new", "wechat-new") is False

    assert manager.db.get_video_by_youtube_id("wechat-new")["status"] == "DOWNLOADING"


def test_accepted_submission_sends_rendered_video_for_mobile_review(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    assert manager.db.add_video("wechat-review", "Title", "channel", score=90)
    (tmp_path / "wechat-review_vertical.mp4").write_bytes(b"review-video")
    (tmp_path / "wechat-review_title.txt").write_text("手机审核标题", encoding="utf-8")
    messages: list[str] = []
    attachments: list[tuple[Path, str]] = []
    manager.send_telegram_msg = messages.append
    manager.send_telegram_video = lambda path, caption: attachments.append((path, caption)) or True

    manager._mark_wechat_submission_under_review(
        "wechat-review", "wechat-review", evidence_path=None,
        reason="platform accepted", submission_confirmed=True,
    )

    assert manager.db.get_video_by_youtube_id("wechat-review")["status"] == "SUBMITTED_UNBOUND"
    assert messages and "submission accepted" in messages[0]
    assert len(attachments) == 1
    assert attachments[0][0] == tmp_path / "wechat-review_vertical.mp4"
    assert "手机审核标题" in attachments[0][1]


def test_historical_archive_tombstone_blocks_publish_without_reactivating_ledger(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    assert manager.db.add_video("wechat-history", "Title", "channel", score=90)
    evidence_dir = tmp_path / "wechat_evidence" / "wechat-history" / "1785719430000000000"
    evidence_dir.mkdir(parents=True)
    evidence = evidence_dir / "post_list_after_submission.png"
    evidence.write_bytes(b"png")
    manager.db.record_wechat_publication_confirmation(
        "wechat-history", evidence_path=str(evidence), state="SUBMITTED_UNBOUND",
    )
    assert manager.db.archive_wechat_publication_as_historical_unresolved(
        "wechat-history", reason="operator archive",
    )

    assert manager._block_duplicate_wechat_submission_if_needed("wechat-history", "wechat-history") is True

    assert manager.db.get_wechat_publication("wechat-history") is None
    assert manager.db.get_video_by_youtube_id("wechat-history")["status"] == "HISTORICAL_UNRESOLVED"


def test_deferred_recovery_skips_historical_tombstone_without_spending_daily_limit(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    assert manager.db.add_video("wechat-history", "Historical", "channel", score=90)
    assert manager.db.add_video("wechat-fresh", "Fresh", "channel", score=90)
    manager.db.record_wechat_publication_confirmation(
        "wechat-history", evidence_path="history.png", state="SUBMITTED_UNBOUND",
    )
    assert manager.db.archive_wechat_publication_as_historical_unresolved(
        "wechat-history", reason="operator archive",
    )
    manager.db.update_video_status("wechat-history", "WECHAT_DEFERRED")
    manager.db.update_video_status("wechat-fresh", "WECHAT_DEFERRED")

    claimed = manager.db.claim_next_deferred_wechat_publication(daily_limit=1)

    assert claimed is not None
    assert claimed["youtube_id"] == "wechat-fresh"
    assert manager.db.get_video_by_youtube_id("wechat-history")["status"] == "WECHAT_DEFERRED"

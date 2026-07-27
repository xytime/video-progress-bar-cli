"""抖音账本到浏览器上传器的管线衔接测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-23 | Codex | 覆盖抖音发布器 fail-closed、审核回查和每日入口衔接 |
| 1.1.0 | 2026-07-23 | Codex | 每日入口在新片重试正常后继续处理抖音补录队列 |
| 1.2.0 | 2026-07-23 | Codex | 覆盖抖音历史补录每日自动领取仅限补录规则候选 |
| 1.3.0 | 2026-07-25 | Codex | 覆盖历史补录缺失本地投递素材时取消并继续下一条 |
| 1.4.0 | 2026-07-26 | Codex | 覆盖抖音上传前审查命中时取消平台任务且不调用上传器 |
| 1.5.0 | 2026-07-27 | Codex | 覆盖抖音历史补发命中审查时取消当前任务并继续下一条 |
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager


def _manager_with_assets(tmp_path: Path) -> PipelineManager:
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    (tmp_path / "video-id_vertical.mp4").write_bytes(b"video")
    (tmp_path / "video-id_copy.txt").write_text("测试文案", encoding="utf-8")
    (tmp_path / "video-id_title.txt").write_text("测试标题", encoding="utf-8")
    manager.db = MagicMock()
    manager.db.get_video_by_youtube_id.return_value = {
        "title": "测试视频",
        "zh_title": "测试标题",
    }
    manager.send_telegram_msg = MagicMock()
    manager._check_censorship = MagicMock(return_value=False)
    return manager


def _add_history_video(manager: PipelineManager, youtube_id: str, title: str, channel_id: str = "general") -> None:
    assert manager.db.add_video(
        youtube_id,
        title,
        channel_id,
        score=88,
        upload_date="20260720",
    )
    manager.db.update_video_status(youtube_id, "PUBLISHED")


def test_claimed_douyin_publication_runs_publish_and_marks_published(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["douyin"], 0, stdout="ok", stderr="")
    )

    assert manager._publish_claimed_douyin_publication(
        {"id": 17, "youtube_id": "video-id", "slice_index": 0}
    )

    command = manager._run_tracked.call_args.args[0]
    assert "douyin_uploader.py" in " ".join(command)
    assert "--publish" in command
    assert "--video" in command
    assert "--prepare-description" in command
    assert "--title-file" in command
    manager.db.update_douyin_publication_state.assert_called_once_with(17, "PUBLISHED")


def test_uncalibrated_douyin_publish_never_marks_the_ledger_published(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    error = subprocess.CalledProcessError(4, ["douyin"], stderr="not calibrated")
    manager._run_tracked = MagicMock(side_effect=error)

    assert not manager._publish_claimed_douyin_publication(
        {"id": 18, "youtube_id": "video-id", "slice_index": 0}
    )

    manager.db.update_douyin_publication_state.assert_called_once()
    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (18, "RETRYABLE_FAILED")
    assert "尚未完成页面校准" in kwargs["error_message"]


def test_douyin_publication_censorship_hit_cancels_without_upload(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager._check_censorship.return_value = True
    manager._run_tracked = MagicMock()

    assert not manager._publish_claimed_douyin_publication(
        {"id": 181, "youtube_id": "video-id", "slice_index": 0, "source_kind": "HISTORY"}
    )

    manager._run_tracked.assert_not_called()
    manager.db.update_douyin_publication_state.assert_called_once()
    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (181, "CANCELED")
    assert "上传前内容安全审查拦截" in kwargs["error_message"]
    manager._check_censorship.assert_called_once()


def test_douyin_review_reconciliation_only_checks_management(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.db.get_douyin_publications_by_states.return_value = [
        {"id": 19, "youtube_id": "video-id", "slice_index": 0}
    ]
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["douyin"], 0, stdout="published", stderr="")
    )

    previous = settings.enable_douyin_browser_publishing
    settings.enable_douyin_browser_publishing = True
    try:
        assert manager.reconcile_douyin_under_review() == 1
    finally:
        settings.enable_douyin_browser_publishing = previous

    command = manager._run_tracked.call_args.args[0]
    assert "--verify-only" in command
    assert "--publish" not in command
    assert "--video" not in command
    manager.db.update_douyin_publication_state.assert_called_once_with(19, "PUBLISHED")


def test_paused_wechat_defers_video_and_uses_enabled_douyin_submission(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.db.get_kuaishou_publication.return_value = None
    manager.db.get_douyin_publication.return_value = {"state": "UNDER_REVIEW"}
    manager.db.is_blacklisted.return_value = False

    prior_douyin = settings.enable_douyin_browser_publishing
    prior_kuaishou = settings.enable_kuaishou_browser_publishing
    settings.enable_douyin_browser_publishing = True
    settings.enable_kuaishou_browser_publishing = False
    try:
        manager._defer_wechat_and_publish_kuaishou("video-id", 0)
    finally:
        settings.enable_douyin_browser_publishing = prior_douyin
        settings.enable_kuaishou_browser_publishing = prior_kuaishou

    manager.db.update_video_status.assert_called_once_with("video-id", "WECHAT_DEFERRED", slice_index=0)
    manager.db.create_douyin_publication.assert_not_called()


def test_daily_job_runs_douyin_history_migration_after_clean_new_retry(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_douyin_under_review = MagicMock()
    manager._retry_one_douyin_new_video = MagicMock(return_value=True)
    manager._run_douyin_history_migration = MagicMock()

    previous_douyin = settings.enable_douyin_browser_publishing
    previous_kuaishou = settings.enable_kuaishou_browser_publishing
    previous_paused = settings.wechat_publishing_paused
    settings.enable_douyin_browser_publishing = True
    settings.enable_kuaishou_browser_publishing = False
    settings.wechat_publishing_paused = True
    try:
        manager.run_daily_job()
    finally:
        settings.enable_douyin_browser_publishing = previous_douyin
        settings.enable_kuaishou_browser_publishing = previous_kuaishou
        settings.wechat_publishing_paused = previous_paused

    manager.reconcile_douyin_under_review.assert_called_once()
    manager._retry_one_douyin_new_video.assert_called_once()
    manager._run_douyin_history_migration.assert_called_once()


def test_daily_job_skips_douyin_history_migration_when_new_retry_is_uncertain(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_douyin_under_review = MagicMock()
    manager._retry_one_douyin_new_video = MagicMock(return_value=False)
    manager._run_douyin_history_migration = MagicMock()

    previous_douyin = settings.enable_douyin_browser_publishing
    previous_kuaishou = settings.enable_kuaishou_browser_publishing
    previous_paused = settings.wechat_publishing_paused
    settings.enable_douyin_browser_publishing = True
    settings.enable_kuaishou_browser_publishing = False
    settings.wechat_publishing_paused = True
    try:
        manager.run_daily_job()
    finally:
        settings.enable_douyin_browser_publishing = previous_douyin
        settings.enable_kuaishou_browser_publishing = previous_kuaishou
        settings.wechat_publishing_paused = previous_paused

    manager.reconcile_douyin_under_review.assert_called_once()
    manager._retry_one_douyin_new_video.assert_called_once()
    manager._run_douyin_history_migration.assert_not_called()


def test_douyin_history_migration_auto_queues_only_rule_candidates(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)
    assert manager.db.add_channel("wst", "Wall Street Truthbombs")
    _add_history_video(manager, "speech-video", "A full speech about markets")
    _add_history_video(manager, "plain-video", "Regular market update")
    _add_history_video(manager, "wst-video", "Market update", "wst")
    for yid in ("speech-video", "plain-video", "wst-video"):
        (tmp_path / f"{yid}_vertical.mp4").write_bytes(b"video")
        (tmp_path / f"{yid}_copy.txt").write_text("测试文案", encoding="utf-8")
        (tmp_path / f"{yid}_title.txt").write_text("测试标题", encoding="utf-8")

    previous_enabled = settings.enable_douyin_browser_publishing
    previous_limit = settings.douyin_history_daily_limit
    previous_since = settings.platform_backfill_wall_street_since_upload_date
    settings.enable_douyin_browser_publishing = True
    settings.douyin_history_daily_limit = 5
    settings.platform_backfill_wall_street_since_upload_date = "20260713"
    try:
        manager._run_douyin_history_migration()
    finally:
        settings.enable_douyin_browser_publishing = previous_enabled
        settings.douyin_history_daily_limit = previous_limit
        settings.platform_backfill_wall_street_since_upload_date = previous_since

    assert manager.db.get_douyin_publication("speech-video") is not None
    assert manager.db.get_douyin_publication("wst-video") is not None
    assert manager.db.get_douyin_publication("plain-video") is None
    assert manager._publish_claimed_douyin_publication.call_count == 2


def test_douyin_history_migration_continues_after_canceling_missing_assets(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    for yid in ("missing-title", "ready-douyin"):
        _add_history_video(manager, yid, "A full speech about markets")
        (tmp_path / f"{yid}_vertical.mp4").write_bytes(b"video")
        (tmp_path / f"{yid}_copy.txt").write_text("测试文案", encoding="utf-8")
    (tmp_path / "ready-douyin_title.txt").write_text("测试标题", encoding="utf-8")
    missing = manager.db.create_douyin_publication(
        "missing-title", "6" * 64, str(tmp_path / "missing-title_vertical.mp4"), source_kind="HISTORY"
    )
    ready = manager.db.create_douyin_publication(
        "ready-douyin", "7" * 64, str(tmp_path / "ready-douyin_vertical.mp4"), source_kind="HISTORY"
    )
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["douyin"], 0, stdout="ok", stderr="")
    )

    previous_enabled = settings.enable_douyin_browser_publishing
    previous_limit = settings.douyin_history_daily_limit
    settings.enable_douyin_browser_publishing = True
    settings.douyin_history_daily_limit = 2
    try:
        manager._run_douyin_history_migration()
    finally:
        settings.enable_douyin_browser_publishing = previous_enabled
        settings.douyin_history_daily_limit = previous_limit

    assert manager.db.get_douyin_publication("missing-title")["state"] == "CANCELED"
    assert manager.db.get_douyin_publication("ready-douyin")["state"] == "PUBLISHED"
    assert manager._run_tracked.call_count == 1
    assert missing["id"] != ready["id"]


def test_douyin_history_migration_continues_after_censorship_cancel(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    for yid in ("blocked-history", "ready-douyin"):
        _add_history_video(manager, yid, "A full speech about markets")
        (tmp_path / f"{yid}_vertical.mp4").write_bytes(b"video")
        (tmp_path / f"{yid}_copy.txt").write_text("测试文案", encoding="utf-8")
        (tmp_path / f"{yid}_title.txt").write_text("测试标题", encoding="utf-8")
    blocked = manager.db.create_douyin_publication(
        "blocked-history", "8" * 64, str(tmp_path / "blocked-history_vertical.mp4"), source_kind="HISTORY"
    )
    ready = manager.db.create_douyin_publication(
        "ready-douyin", "9" * 64, str(tmp_path / "ready-douyin_vertical.mp4"), source_kind="HISTORY"
    )
    manager._check_censorship = MagicMock(side_effect=[True, False])
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["douyin"], 0, stdout="ok", stderr="")
    )

    previous_enabled = settings.enable_douyin_browser_publishing
    previous_limit = settings.douyin_history_daily_limit
    settings.enable_douyin_browser_publishing = True
    settings.douyin_history_daily_limit = 2
    try:
        manager._run_douyin_history_migration()
    finally:
        settings.enable_douyin_browser_publishing = previous_enabled
        settings.douyin_history_daily_limit = previous_limit

    assert manager.db.get_douyin_publication("blocked-history")["state"] == "CANCELED"
    assert manager.db.get_douyin_publication("ready-douyin")["state"] == "PUBLISHED"
    assert manager._run_tracked.call_count == 1
    assert blocked["id"] != ready["id"]

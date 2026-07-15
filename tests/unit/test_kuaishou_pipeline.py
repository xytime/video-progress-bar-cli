"""快手账本到浏览器上传器的管线衔接测试。"""

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
    manager.db = MagicMock()
    manager.send_telegram_msg = MagicMock()
    return manager


def test_claimed_publication_runs_explicit_publish_and_marks_published(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["kuaishou"], 0, stdout="ok", stderr="")
    )

    assert manager._publish_claimed_kuaishou_publication(
        {"id": 7, "youtube_id": "video-id", "slice_index": 0}
    )

    command = manager._run_tracked.call_args.args[0]
    assert "--calibrate-after-upload" in command
    assert "--prepare-description" in command
    assert "--publish" in command
    manager.db.update_kuaishou_publication_state.assert_called_once_with(7, "PUBLISHED")


def test_unconfirmed_publish_never_marks_the_ledger_published(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    error = subprocess.CalledProcessError(3, ["kuaishou"], stderr="作品管理未找到")
    manager._run_tracked = MagicMock(side_effect=error)

    assert not manager._publish_claimed_kuaishou_publication(
        {"id": 8, "youtube_id": "video-id", "slice_index": 0}
    )

    manager.db.update_kuaishou_publication_state.assert_called_once()
    args, kwargs = manager.db.update_kuaishou_publication_state.call_args
    assert args == (8, "UNCERTAIN")
    assert "作品管理确认" in kwargs["error_message"]


def test_review_reconciliation_only_checks_management_and_marks_confirmed_publish(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.db.get_kuaishou_publications_by_states.return_value = [
        {"id": 9, "youtube_id": "video-id", "slice_index": 0}
    ]
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["kuaishou"], 0, stdout="published", stderr="")
    )

    previous = settings.enable_kuaishou_browser_publishing
    settings.enable_kuaishou_browser_publishing = True
    try:
        assert manager.reconcile_kuaishou_under_review() == 1
    finally:
        settings.enable_kuaishou_browser_publishing = previous

    command = manager._run_tracked.call_args.args[0]
    assert "--verify-only" in command
    assert "--publish" not in command
    assert "--video" not in command
    manager.db.update_kuaishou_publication_state.assert_called_once_with(9, "PUBLISHED")


def test_daily_job_does_not_run_history_migration(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_kuaishou_under_review = MagicMock()
    manager._retry_one_kuaishou_new_video = MagicMock(return_value=True)
    manager._run_kuaishou_history_migration = MagicMock()
    previous = settings.enable_kuaishou_browser_publishing
    settings.enable_kuaishou_browser_publishing = True
    try:
        manager.run_daily_job()
    finally:
        settings.enable_kuaishou_browser_publishing = previous

    manager.score_pending_videos.assert_called_once()
    manager.process_high_score_videos.assert_called_once_with(limit=5)
    manager.reconcile_kuaishou_under_review.assert_called_once()
    manager._retry_one_kuaishou_new_video.assert_called_once()
    manager._run_kuaishou_history_migration.assert_not_called()

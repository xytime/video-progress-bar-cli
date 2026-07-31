"""快手账本到浏览器上传器的管线衔接测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-15 | Codex | 覆盖快手账本、发布器和审核回查衔接 |
| 1.1.0 | 2026-07-16 | Codex | 覆盖视频号暂停期间的快手单平台发布与恢复入口 |
| 1.2.0 | 2026-07-23 | Codex | 显式隔离抖音开关，避免三平台上线后快手单测被环境配置带偏 |
| 1.3.0 | 2026-07-25 | Codex | 覆盖历史补录缺失本地投递素材时取消自动重试 |
| 1.4.0 | 2026-07-25 | Codex | 覆盖快手平台专用短文案优先级 |
| 1.5.0 | 2026-07-27 | Codex | 覆盖快手历史补发命中审查时取消当前任务并继续下一条 |
| 1.6.0 | 2026-07-27 | Codex | 浏览器上传衔接夹具显式 mock 审查通过，避免 MagicMock DB 触发严格模式异常 |
| 1.7.0 | 2026-07-29 | Codex | 覆盖快手账号封禁退出码落 BANNED，防止审核回查误标发布 |
| 1.8.0 | 2026-07-31 | Codex | 夹具提供哈希绑定的专门生成封面，禁止历史帧封面被测试默许 |
"""

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager


def _manager_with_assets(tmp_path: Path) -> PipelineManager:
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    cover = tmp_path / "video-id_cover.jpg"
    cover.write_bytes(b"dedicated-cover")
    (tmp_path / "video-id_cover_provenance.json").write_text(
        json.dumps({
            "cover_kind": "dedicated_generated_image",
            "uses_video_frame": False,
            "cover_filename": cover.name,
            "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )
    (tmp_path / "video-id_vertical.mp4").write_bytes(b"video")
    (tmp_path / "video-id_copy.txt").write_text("测试文案", encoding="utf-8")
    (tmp_path / "video-id.ass").write_text(
        "[Script Info]\nTitle: test\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,safe subtitle text\n",
        encoding="utf-8",
    )
    manager.db = MagicMock()
    manager.send_telegram_msg = MagicMock()
    manager._check_censorship = MagicMock(return_value=False)
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
    manager.db.update_kuaishou_publication_state.assert_called_once_with(
        7,
        "PUBLISHED",
        error_message="快手作品管理已确认本次作品为已发布。",
    )


def test_claimed_publication_maps_account_banned_exit_to_banned(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    error = subprocess.CalledProcessError(7, ["kuaishou"], stderr="账号已被封禁")
    manager._run_tracked = MagicMock(side_effect=error)

    assert not manager._publish_claimed_kuaishou_publication(
        {"id": 71, "youtube_id": "video-id", "slice_index": 0}
    )

    manager.db.update_kuaishou_publication_state.assert_called_once()
    args, kwargs = manager.db.update_kuaishou_publication_state.call_args
    assert args == (71, "BANNED")
    assert "账号已被封禁" in kwargs["error_message"]


def test_kuaishou_prefers_platform_specific_copy_when_present(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    (tmp_path / "video-id_kuaishou_copy.txt").write_text("快手短文案", encoding="utf-8")
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["kuaishou"], 0, stdout="ok", stderr="")
    )

    assert manager._publish_claimed_kuaishou_publication(
        {"id": 70, "youtube_id": "video-id", "slice_index": 0}
    )

    command = manager._run_tracked.call_args.args[0]
    assert str(tmp_path / "video-id_kuaishou_copy.txt") in command
    assert str(tmp_path / "video-id_copy.txt") not in command


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


def test_history_publication_missing_copy_is_canceled(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    (tmp_path / "video-id_copy.txt").unlink()

    assert not manager._publish_claimed_kuaishou_publication(
        {"id": 10, "youtube_id": "video-id", "slice_index": 0, "source_kind": "HISTORY"}
    )

    manager.db.update_kuaishou_publication_state.assert_called_once()
    args, kwargs = manager.db.update_kuaishou_publication_state.call_args
    assert args == (10, "CANCELED")
    assert "copy=False" in kwargs["error_message"]


def test_history_migration_continues_after_canceling_missing_assets(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    for yid in ("missing-copy", "ready-history"):
        assert manager.db.add_video(yid, "测试视频", "test-channel", score=80)
        manager.db.update_video_status(yid, "PUBLISHED")
        (tmp_path / f"{yid}_vertical.mp4").write_bytes(b"video")
        (tmp_path / f"{yid}.ass").write_text(
            "[Script Info]\nTitle: test\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,safe subtitle text\n",
            encoding="utf-8",
        )
    (tmp_path / "ready-history_copy.txt").write_text("测试文案", encoding="utf-8")
    missing = manager.db.create_kuaishou_publication(
        "missing-copy", "7" * 64, str(tmp_path / "missing-copy_vertical.mp4"), source_kind="HISTORY"
    )
    ready = manager.db.create_kuaishou_publication(
        "ready-history", "8" * 64, str(tmp_path / "ready-history_vertical.mp4"), source_kind="HISTORY"
    )
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["kuaishou"], 0, stdout="ok", stderr="")
    )

    previous = settings.enable_kuaishou_browser_publishing
    previous_limit = settings.kuaishou_history_daily_limit
    settings.enable_kuaishou_browser_publishing = True
    settings.kuaishou_history_daily_limit = 2
    try:
        manager._run_kuaishou_history_migration()
    finally:
        settings.enable_kuaishou_browser_publishing = previous
        settings.kuaishou_history_daily_limit = previous_limit

    assert manager.db.get_kuaishou_publication("missing-copy")["state"] == "CANCELED"
    assert manager.db.get_kuaishou_publication("ready-history")["state"] == "PUBLISHED"
    assert manager._run_tracked.call_count == 1
    assert missing["id"] != ready["id"]


def test_history_migration_continues_after_censorship_cancel(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    for yid in ("blocked-history", "ready-history"):
        assert manager.db.add_video(yid, "测试视频", "test-channel", score=80)
        manager.db.update_video_status(yid, "PUBLISHED")
        (tmp_path / f"{yid}_vertical.mp4").write_bytes(b"video")
        (tmp_path / f"{yid}_copy.txt").write_text("测试文案", encoding="utf-8")
        (tmp_path / f"{yid}.ass").write_text(
            "[Script Info]\nTitle: test\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,safe subtitle text\n",
            encoding="utf-8",
        )
    blocked = manager.db.create_kuaishou_publication(
        "blocked-history", "9" * 64, str(tmp_path / "blocked-history_vertical.mp4"), source_kind="HISTORY"
    )
    ready = manager.db.create_kuaishou_publication(
        "ready-history", "a" * 64, str(tmp_path / "ready-history_vertical.mp4"), source_kind="HISTORY"
    )
    manager._check_censorship = MagicMock(side_effect=[True, False])
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["kuaishou"], 0, stdout="ok", stderr="")
    )

    previous = settings.enable_kuaishou_browser_publishing
    previous_limit = settings.kuaishou_history_daily_limit
    settings.enable_kuaishou_browser_publishing = True
    settings.kuaishou_history_daily_limit = 2
    try:
        manager._run_kuaishou_history_migration()
    finally:
        settings.enable_kuaishou_browser_publishing = previous
        settings.kuaishou_history_daily_limit = previous_limit

    assert manager.db.get_kuaishou_publication("blocked-history")["state"] == "CANCELED"
    assert manager.db.get_kuaishou_publication("ready-history")["state"] == "PUBLISHED"
    assert manager._run_tracked.call_count == 1
    assert blocked["id"] != ready["id"]


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
    manager.db.update_kuaishou_publication_state.assert_called_once_with(
        9,
        "PUBLISHED",
        error_message="快手作品管理已确认本次作品为已发布。",
    )


def test_review_reconciliation_maps_account_banned_exit_to_banned(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.db.get_kuaishou_publications_by_states.return_value = [
        {"id": 91, "youtube_id": "video-id", "slice_index": 0}
    ]
    manager._run_tracked = MagicMock(
        side_effect=subprocess.CalledProcessError(7, ["kuaishou"], stderr="账号已被封禁")
    )

    previous = settings.enable_kuaishou_browser_publishing
    settings.enable_kuaishou_browser_publishing = True
    try:
        assert manager.reconcile_kuaishou_under_review() == 0
    finally:
        settings.enable_kuaishou_browser_publishing = previous

    manager.db.update_kuaishou_publication_state.assert_called_once()
    args, kwargs = manager.db.update_kuaishou_publication_state.call_args
    assert args == (91, "BANNED")
    assert "账号已被封禁" in kwargs["error_message"]


def test_daily_job_does_not_run_history_migration(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_kuaishou_under_review = MagicMock()
    manager._retry_one_kuaishou_new_video = MagicMock(return_value=True)
    manager._run_kuaishou_history_migration = MagicMock()
    previous = settings.enable_kuaishou_browser_publishing
    previous_douyin = settings.enable_douyin_browser_publishing
    previous_paused = settings.wechat_publishing_paused
    settings.enable_kuaishou_browser_publishing = True
    settings.enable_douyin_browser_publishing = False
    settings.wechat_publishing_paused = True
    try:
        manager.run_daily_job()
    finally:
        settings.enable_kuaishou_browser_publishing = previous
        settings.enable_douyin_browser_publishing = previous_douyin
        settings.wechat_publishing_paused = previous_paused

    manager.score_pending_videos.assert_called_once()
    manager.process_high_score_videos.assert_called_once_with(limit=5)
    manager.reconcile_kuaishou_under_review.assert_called_once()
    manager._retry_one_kuaishou_new_video.assert_called_once()
    manager._run_kuaishou_history_migration.assert_not_called()


def test_paused_wechat_defers_video_and_uses_existing_kuaishou_submission(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.db.get_kuaishou_publication.return_value = {"state": "UNDER_REVIEW"}
    manager.db.is_blacklisted.return_value = False
    previous_douyin = settings.enable_douyin_browser_publishing
    settings.enable_douyin_browser_publishing = False

    try:
        manager._defer_wechat_and_publish_kuaishou("video-id", 0)
    finally:
        settings.enable_douyin_browser_publishing = previous_douyin

    manager.db.update_video_status.assert_called_once_with("video-id", "WECHAT_DEFERRED", slice_index=0)
    manager.db.create_kuaishou_publication.assert_not_called()
    manager.send_telegram_msg.assert_not_called()


def test_recovery_claims_at_most_the_configured_daily_limit(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.db.claim_next_deferred_wechat_publication.side_effect = [
        {"youtube_id": "video-id", "slice_index": 0},
        {"youtube_id": "second-video", "slice_index": 0},
    ]
    manager._process_single_video = MagicMock()
    prior_paused = settings.wechat_publishing_paused
    prior_limit = settings.wechat_deferred_recovery_daily_limit
    settings.wechat_publishing_paused = False
    settings.wechat_deferred_recovery_daily_limit = 1
    try:
        assert manager.recover_deferred_wechat_publications() == 1
    finally:
        settings.wechat_publishing_paused = prior_paused
        settings.wechat_deferred_recovery_daily_limit = prior_limit

    manager._process_single_video.assert_called_once_with({"youtube_id": "video-id", "slice_index": 0})
    manager.db.claim_next_deferred_wechat_publication.assert_called_once_with(daily_limit=1)


def test_paused_daily_job_skips_wechat_recovery(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.recover_deferred_wechat_publications = MagicMock()
    manager.reconcile_kuaishou_under_review = MagicMock()
    manager._retry_one_kuaishou_new_video = MagicMock(return_value=True)
    prior_paused = settings.wechat_publishing_paused
    prior_kuaishou = settings.enable_kuaishou_browser_publishing
    prior_douyin = settings.enable_douyin_browser_publishing
    settings.wechat_publishing_paused = True
    settings.enable_kuaishou_browser_publishing = True
    settings.enable_douyin_browser_publishing = False
    try:
        manager.run_daily_job()
    finally:
        settings.wechat_publishing_paused = prior_paused
        settings.enable_kuaishou_browser_publishing = prior_kuaishou
        settings.enable_douyin_browser_publishing = prior_douyin

    manager.recover_deferred_wechat_publications.assert_not_called()
    manager.process_high_score_videos.assert_called_once_with(limit=5)


def test_daily_job_recovers_deferred_wechat_when_not_paused(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.recover_deferred_wechat_publications = MagicMock(return_value=2)
    manager.reconcile_kuaishou_under_review = MagicMock()
    manager._retry_one_kuaishou_new_video = MagicMock(return_value=True)
    prior_paused = settings.wechat_publishing_paused
    prior_kuaishou = settings.enable_kuaishou_browser_publishing
    prior_douyin = settings.enable_douyin_browser_publishing
    settings.wechat_publishing_paused = False
    settings.enable_kuaishou_browser_publishing = False
    settings.enable_douyin_browser_publishing = False
    try:
        manager.run_daily_job()
    finally:
        settings.wechat_publishing_paused = prior_paused
        settings.enable_kuaishou_browser_publishing = prior_kuaishou
        settings.enable_douyin_browser_publishing = prior_douyin

    manager.process_high_score_videos.assert_called_once_with(limit=5)
    manager.recover_deferred_wechat_publications.assert_called_once()


def test_claimed_kuaishou_publication_passes_cover_arg_when_cover_exists(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    cover = tmp_path / "video-id_cover.jpg"
    cover.write_bytes(b"cover_image_bytes")
    (tmp_path / "video-id_cover_provenance.json").write_text(
        json.dumps({
            "cover_kind": "dedicated_generated_image",
            "uses_video_frame": False,
            "cover_filename": cover.name,
            "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["kuaishou"], 0, stdout="ok", stderr="")
    )

    assert manager._publish_claimed_kuaishou_publication(
        {"id": 77, "youtube_id": "video-id", "slice_index": 0}
    )

    command = manager._run_tracked.call_args.args[0]
    assert "--cover" in command
    assert str(tmp_path / "video-id_cover.jpg") in command

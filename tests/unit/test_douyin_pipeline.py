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
| 1.6.0 | 2026-07-27 | Codex | 覆盖抖音动作节流、每轮回查上限和异常熔断停止后续自动动作 |
| 1.7.0 | 2026-07-29 | Codex | 覆盖抖音历史补发实时进度汇报和缺素材 HISTORY 跳过继续 |
| 1.7.1 | 2026-07-29 | Codex | 覆盖抖音缺封面时不调用上传器，避免半成品作品提交 |
| 1.7.2 | 2026-07-29 | Codex | 覆盖抖音审核回查未校准时转 UNCERTAIN，避免每轮重复回查同一条 |
| 1.7.3 | 2026-07-29 | Codex | 覆盖提交前未确认与提交后未确认的账本状态区分 |
| 1.7.4 | 2026-07-29 | Codex | 覆盖抖音上传器正常返回仍只记审核中，禁止本地假成功 |
| 1.7.5 | 2026-07-29 | Codex | 覆盖微信已发布但抖音 NEW 未建账时自动补齐并进入新片同步 |
| 1.7.6 | 2026-07-31 | Codex | 夹具提供哈希绑定的专门生成封面，禁止历史帧封面被测试默许 |
| 1.7.7 | 2026-08-07 | Codex | 覆盖抖音发布前闸门与页面校准失败停止自动重试 |
| 1.7.8 | 2026-08-08 | Codex | 覆盖缺失投递产物时不再让新稿跨轮自动重试 |
| 1.7.9 | 2026-08-08 | Codex | 覆盖跨巡航浏览器节流接口，测试替身明确返回可立即执行 |
| 1.8.0 | 2026-08-30 | Codex | 覆盖 UI 同阶段失败持久累计与下轮打开浏览器前录屏熔断 |
"""

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from config.settings import settings
from video_processing.core.cover_policy import compliant_cover_layout_policy
from video_processing.pipeline_manager import PipelineManager


def _manager_with_assets(tmp_path: Path) -> PipelineManager:
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    (tmp_path / "video-id_vertical.mp4").write_bytes(b"video")
    (tmp_path / "video-id_copy.txt").write_text("测试文案", encoding="utf-8")
    (tmp_path / "video-id_title.txt").write_text("测试标题", encoding="utf-8")
    cover = tmp_path / "video-id_cover.jpg"
    cover.write_bytes(b"dedicated-cover")
    (tmp_path / "video-id_cover_provenance.json").write_text(
        json.dumps({
            "cover_kind": "dedicated_generated_image",
            "uses_video_frame": False,
            "cover_filename": cover.name,
            "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
            "layout_policy": compliant_cover_layout_policy(),
        }),
        encoding="utf-8",
    )
    (tmp_path / "video-id.ass").write_text(
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,subtitle body\n",
        encoding="utf-8",
    )
    manager.db = MagicMock()
    manager.db.reserve_douyin_browser_action_slot.return_value = 0.0
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


def _write_dedicated_cover(directory: Path, youtube_id: str) -> None:
    cover = directory / f"{youtube_id}_cover.jpg"
    cover.write_bytes(b"dedicated-cover")
    (directory / f"{youtube_id}_cover_provenance.json").write_text(
        json.dumps({
            "cover_kind": "dedicated_generated_image",
            "uses_video_frame": False,
            "cover_filename": cover.name,
            "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
            "layout_policy": compliant_cover_layout_policy(),
        }),
        encoding="utf-8",
    )


def _add_published_video_assets(manager: PipelineManager, youtube_id: str) -> None:
    manager.db.add_video(youtube_id, "Published title", "general", score=88)
    manager.db.update_video_status(youtube_id, "PUBLISHED")
    (manager._OUT_DIR / f"{youtube_id}_vertical.mp4").write_bytes(b"video")
    (manager._OUT_DIR / f"{youtube_id}_copy.txt").write_text("测试文案", encoding="utf-8")
    (manager._OUT_DIR / f"{youtube_id}_title.txt").write_text("测试标题", encoding="utf-8")
    _write_dedicated_cover(manager._OUT_DIR, youtube_id)
    (manager._OUT_DIR / f"{youtube_id}.ass").write_text(
        "[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,subtitle body\n",
        encoding="utf-8",
    )


def test_claimed_douyin_publication_runs_publish_and_marks_under_review(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
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
    assert "--cover" in command
    manager.db.update_douyin_publication_state.assert_called_once()
    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (17, "UNDER_REVIEW")
    assert "等待作品管理页" in kwargs["error_message"]


def test_uncalibrated_douyin_publish_cancels_automatic_retry(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    error = subprocess.CalledProcessError(4, ["douyin"], stderr="not calibrated")
    manager._run_tracked = MagicMock(side_effect=error)

    assert not manager._publish_claimed_douyin_publication(
        {"id": 18, "youtube_id": "video-id", "slice_index": 0}
    )

    manager.db.update_douyin_publication_state.assert_called_once()
    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (18, "CANCELED")
    assert "尚未完成页面校准" in kwargs["error_message"]
    assert "停止自动重试" in kwargs["error_message"]
    manager.db.record_platform_ui_failure.assert_called_once()


def test_pre_submit_unconfirmed_cancels_not_uncertain(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    manager._run_tracked = MagicMock(side_effect=subprocess.CalledProcessError(3, ["douyin"]))

    assert not manager._publish_claimed_douyin_publication({"id": 183, "youtube_id": "video-id", "slice_index": 0})

    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (183, "CANCELED")
    assert "本次未提交" in kwargs["error_message"]
    assert "停止自动重试" in kwargs["error_message"]
    manager.db.record_platform_ui_failure.assert_called_once()


def test_persistent_douyin_ui_guard_halts_before_browser_action(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "publish_pre_submit",
        "consecutive_failures": 2,
        "active": 1,
    }]
    manager._run_tracked = MagicMock()

    manager._reset_douyin_run_guard()
    assert manager._douyin_platform_halted
    assert "打开浏览器前停止" in manager._douyin_halt_reason
    assert "录制一次完整手工操作流程" in manager._douyin_halt_reason
    assert not manager._publish_claimed_douyin_publication(
        {"id": 185, "youtube_id": "video-id", "slice_index": 0}
    )
    manager._run_tracked.assert_not_called()
    manager.db.reserve_douyin_browser_action_slot.assert_not_called()


def test_post_submit_unconfirmed_is_uncertain(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    manager._run_tracked = MagicMock(side_effect=subprocess.CalledProcessError(7, ["douyin"]))

    assert not manager._publish_claimed_douyin_publication({"id": 184, "youtube_id": "video-id", "slice_index": 0})

    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (184, "UNCERTAIN")
    assert "已点击最终发布" in kwargs["error_message"]


def test_douyin_publication_censorship_hit_cancels_without_upload(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
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


def test_douyin_missing_cover_cancels_without_upload(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    (tmp_path / "video-id_cover.jpg").unlink()
    manager._run_tracked = MagicMock()

    assert not manager._publish_claimed_douyin_publication(
        {"id": 182, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW"}
    )

    manager._run_tracked.assert_not_called()
    manager.db.update_douyin_publication_state.assert_called_once()
    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (182, "CANCELED")
    assert "cover=False" in kwargs["error_message"]


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


def test_douyin_review_reconciliation_marks_uncertain_when_not_calibrated(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    (tmp_path / "second-id_copy.txt").write_text("第二条文案", encoding="utf-8")
    manager.db.get_douyin_publications_by_states.return_value = [
        {"id": 19, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW"},
        {"id": 20, "youtube_id": "second-id", "slice_index": 0, "source_kind": "NEW"},
    ]
    manager._run_tracked = MagicMock(side_effect=subprocess.CalledProcessError(4, ["douyin"]))
    manager._throttle_douyin_browser_action = MagicMock()

    previous = settings.enable_douyin_browser_publishing
    previous_max = settings.douyin_review_max_per_run
    settings.enable_douyin_browser_publishing = True
    settings.douyin_review_max_per_run = 5
    try:
        assert manager.reconcile_douyin_under_review() == 0
    finally:
        settings.enable_douyin_browser_publishing = previous
        settings.douyin_review_max_per_run = previous_max

    manager._run_tracked.assert_called_once()
    manager._throttle_douyin_browser_action.assert_called_once()
    manager.db.update_douyin_publication_state.assert_called_once()
    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (19, "UNCERTAIN")
    assert "尚未完成作品管理回查校准" in kwargs["error_message"]
    manager.send_telegram_msg.assert_called_once()
    assert manager._douyin_platform_halted


def test_douyin_review_reconciliation_respects_per_run_limit(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    (tmp_path / "second-id_copy.txt").write_text("第二条文案", encoding="utf-8")
    manager.db.get_douyin_publications_by_states.return_value = [
        {"id": 19, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW"},
        {"id": 20, "youtube_id": "second-id", "slice_index": 0, "source_kind": "NEW"},
    ]
    manager._run_tracked = MagicMock(side_effect=subprocess.CalledProcessError(6, ["douyin"]))
    manager._throttle_douyin_browser_action = MagicMock()

    previous = settings.enable_douyin_browser_publishing
    previous_max = settings.douyin_review_max_per_run
    settings.enable_douyin_browser_publishing = True
    settings.douyin_review_max_per_run = 1
    try:
        assert manager.reconcile_douyin_under_review() == 0
    finally:
        settings.enable_douyin_browser_publishing = previous
        settings.douyin_review_max_per_run = previous_max

    manager._run_tracked.assert_called_once()
    manager._throttle_douyin_browser_action.assert_called_once()
    manager.send_telegram_msg.assert_not_called()


def test_douyin_review_limit_is_applied_after_skipping_history(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.db.get_douyin_publications_by_states.return_value = [
        {"id": 18, "youtube_id": "history-id", "slice_index": 0, "source_kind": "HISTORY"},
        {"id": 19, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW"},
    ]
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["douyin"], 0, stdout="published", stderr="")
    )
    manager._throttle_douyin_browser_action = MagicMock()

    previous = settings.enable_douyin_browser_publishing
    previous_max = settings.douyin_review_max_per_run
    settings.enable_douyin_browser_publishing = True
    settings.douyin_review_max_per_run = 1
    try:
        assert manager.reconcile_douyin_under_review() == 1
    finally:
        settings.enable_douyin_browser_publishing = previous
        settings.douyin_review_max_per_run = previous_max

    command = manager._run_tracked.call_args.args[0]
    assert str(tmp_path / "video-id_copy.txt") in command
    assert "history-id" not in " ".join(command)
    manager.db.update_douyin_publication_state.assert_called_once_with(19, "PUBLISHED")


def test_douyin_browser_actions_are_throttled_between_visits(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monotonic_values = iter([105.0, 130.0])
    sleep = MagicMock()

    previous_interval = settings.douyin_browser_action_interval_sec
    settings.douyin_browser_action_interval_sec = 30
    monkeypatch.setattr("video_processing.pipeline_manager.time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("video_processing.pipeline_manager.time.sleep", sleep)
    try:
        manager._last_douyin_browser_action_at = 100.0
        manager._throttle_douyin_browser_action("第二次打开页面")
    finally:
        settings.douyin_browser_action_interval_sec = previous_interval

    sleep.assert_called_once_with(25.0)
    assert manager._last_douyin_browser_action_at == 130.0


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


def test_daily_job_runs_douyin_history_migration_after_clean_new_sync(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_douyin_under_review = MagicMock()
    manager._run_douyin_new_sync = MagicMock(return_value=True)
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
    manager._run_douyin_new_sync.assert_called_once()
    manager._run_douyin_history_migration.assert_called_once()


def test_daily_job_skips_douyin_history_migration_when_new_sync_is_uncertain(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_douyin_under_review = MagicMock()
    manager._run_douyin_new_sync = MagicMock(return_value=False)
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
    manager._run_douyin_new_sync.assert_called_once()
    manager._run_douyin_history_migration.assert_not_called()


def test_daily_job_skips_douyin_retry_and_history_when_review_halts(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_douyin_under_review = MagicMock(
        side_effect=lambda: manager._halt_douyin_platform("review-video", "作品管理异常")
    )
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
    manager._retry_one_douyin_new_video.assert_not_called()
    manager._run_douyin_history_migration.assert_not_called()


def test_douyin_history_migration_auto_queues_only_rule_candidates(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)
    manager.send_telegram_msg = MagicMock()
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
    assert manager.send_telegram_msg.call_count == 2
    first_message = manager.send_telegram_msg.call_args_list[0].args[0]
    assert "Douyin History Progress" in first_message
    assert "正在发送" in first_message
    assert "今日进度：1/5" in first_message
    assert "待发队列" in first_message


def test_douyin_history_migration_continues_after_canceling_missing_assets(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    for yid in ("missing-title", "ready-douyin"):
        _add_history_video(manager, yid, "A full speech about markets")
        (tmp_path / f"{yid}_vertical.mp4").write_bytes(b"video")
        (tmp_path / f"{yid}_copy.txt").write_text("测试文案", encoding="utf-8")
        _write_dedicated_cover(tmp_path, yid)
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
    previous_subtitle = settings.enable_subtitle_censorship
    settings.enable_douyin_browser_publishing = True
    settings.douyin_history_daily_limit = 2
    settings.enable_subtitle_censorship = False
    try:
        manager._run_douyin_history_migration()
    finally:
        settings.enable_douyin_browser_publishing = previous_enabled
        settings.douyin_history_daily_limit = previous_limit
        settings.enable_subtitle_censorship = previous_subtitle

    assert manager.db.get_douyin_publication("missing-title")["state"] == "CANCELED"
    assert manager.db.get_douyin_publication("ready-douyin")["state"] == "UNDER_REVIEW"
    manager._run_tracked.assert_called_once()
    assert not manager._douyin_platform_halted
    assert missing["id"] != ready["id"]


def test_douyin_history_migration_halts_after_censorship_cancel(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    for yid in ("blocked-history", "ready-douyin"):
        _add_history_video(manager, yid, "A full speech about markets")
        (tmp_path / f"{yid}_vertical.mp4").write_bytes(b"video")
        (tmp_path / f"{yid}_copy.txt").write_text("测试文案", encoding="utf-8")
        (tmp_path / f"{yid}_title.txt").write_text("测试标题", encoding="utf-8")
        _write_dedicated_cover(tmp_path, yid)
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
    assert manager.db.get_douyin_publication("ready-douyin")["state"] == "QUEUED"
    manager._run_tracked.assert_not_called()
    assert manager._douyin_platform_halted
    assert blocked["id"] != ready["id"]


def test_douyin_new_sync_queues_recent_wechat_published_gap_and_publishes(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    _add_published_video_assets(manager, "wechat-only-new")
    manager._is_public_publish_window = MagicMock(return_value=True)
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)

    previous_enabled = settings.enable_douyin_browser_publishing
    previous_limit = settings.douyin_new_sync_max_per_run
    previous_lookback = settings.douyin_new_sync_lookback_hours
    settings.enable_douyin_browser_publishing = True
    settings.douyin_new_sync_max_per_run = 10
    settings.douyin_new_sync_lookback_hours = 24
    try:
        assert manager._run_douyin_new_sync()
    finally:
        settings.enable_douyin_browser_publishing = previous_enabled
        settings.douyin_new_sync_max_per_run = previous_limit
        settings.douyin_new_sync_lookback_hours = previous_lookback

    publication = manager.db.get_douyin_publication("wechat-only-new")
    assert publication is not None
    assert publication["source_kind"] == "NEW"
    assert manager._publish_claimed_douyin_publication.call_count == 1
    claimed = manager._publish_claimed_douyin_publication.call_args.args[0]
    assert claimed["youtube_id"] == "wechat-only-new"

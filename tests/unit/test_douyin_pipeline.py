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
| 1.9.0 | 2026-08-30 | Codex | 覆盖抖音 NEW 显式关闭视频号门禁后只为无历史账本新片建队 |
| 2.0.0 | 2026-09-01 | Codex | 覆盖无数量、日额和来源公开确认限制时，一轮同步全部合格新片。 |
| 2.0.1 | 2026-09-01 | Codex | 覆盖作品管理页无法精确匹配时纳入持久 UI 熔断，避免跨轮污染审核中队列。 |
| 2.0.2 | 2026-09-02 | Codex | 覆盖管理页熔断仅冻结回查与历史回填，不阻断独立投稿前闸门保护的新片同步。 |
| 2.0.3 | 2026-09-02 | Codex | 覆盖每日补发、直接回查与直接入队均在账本熔断前停止，禁止绕过浏览器前守卫。 |
| 2.0.4 | 2026-09-02 | Codex | 覆盖管理页熔断下补发/重试 NEW 的阶段放行，以及任一活动熔断在 HISTORY 与回查领取前停止。 |
| 2.0.5 | 2026-09-02 | Codex | 覆盖损坏的持久熔断账本仍能稳定 fail-closed，不让告警格式化中断整轮任务。 |
| 2.0.6 | 2026-09-02 | Codex | 覆盖通用抖音领取必须把一次性 ticket 与完整投稿包绑定后才启动低层浏览器。 |
| 2.0.7 | 2026-09-02 | Codex | 覆盖 NEW 自动发现的安全边界与缺素材聚合告警跨巡航去重。 |
| 2.0.8 | 2026-09-02 | Codex | 覆盖自动 NEW 的零额度安全停用，防止发现边界存在但实际浏览器动作仍无限。 |
| 2.0.9 | 2026-09-02 | Codex | 覆盖通用 ticket 绑定失败或子进程超时且凭据未启动时立即原子取消，禁止遗留可消费领取。 |
| 2.0.10 | 2026-09-02 | Codex | 覆盖视频号补发只入 NEW 队列，并与重试路径共享每轮浏览器动作预算。 |
| 2.0.11 | 2026-09-02 | Codex | 覆盖每个每日任务运行先重置 NEW 动作预算，避免常驻管理器跨轮永久耗尽。 |
| 2.0.12 | 2026-09-04 | Codex | 覆盖通用投稿透传独立横封面和单次证据目录，避免双封面退化且失败证据互相覆盖。 |
"""

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
    manager.db.get_platform_ui_failure_streaks.return_value = []
    manager.db.cancel_douyin_publication_pre_launch_failure.return_value = False
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
        {
            "id": 17, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW",
            "_douyin_launch_ticket_id": "ticket-17", "_douyin_launch_token": "token-17",
        }
    )

    command = manager._run_tracked.call_args.args[0]
    assert "douyin_uploader.py" in " ".join(command)
    assert "--publish" in command
    assert "--video" in command
    assert "--prepare-description" in command
    assert "--title-file" in command
    assert "--cover" in command
    assert "--evidence-dir" in command
    assert command[command.index("--evidence-dir") + 1] == str(
        tmp_path / "douyin_evidence" / "video-id" / "17"
    )
    assert command[command.index("--douyin-launch-ticket") + 1] == "ticket-17"
    assert command[command.index("--douyin-launch-token") + 1] == "token-17"
    manager.db.bind_douyin_browser_launch_ticket_payload.assert_called_once()
    manager.db.update_douyin_publication_state.assert_called_once()
    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (17, "UNDER_REVIEW")
    assert "等待作品管理页" in kwargs["error_message"]


def test_claimed_douyin_publication_prefers_generated_horizontal_cover(tmp_path: Path, monkeypatch):
    """通用投稿也必须透传已生成的横封面，而非从竖图重新裁切。"""
    manager = _manager_with_assets(tmp_path)
    horizontal = tmp_path / "video-id_cover_douyin_horizontal.jpg"
    horizontal.write_bytes(b"horizontal-cover")
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["douyin"], 0, stdout="ok", stderr="")
    )

    assert manager._publish_claimed_douyin_publication(
        {
            "id": 171, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW",
            "_douyin_launch_ticket_id": "ticket-171", "_douyin_launch_token": "token-171",
        }
    )

    command = manager._run_tracked.call_args.args[0]
    assert command[command.index("--horizontal-cover") + 1] == str(horizontal)
    bind_kwargs = manager.db.bind_douyin_browser_launch_ticket_payload.call_args.kwargs
    assert bind_kwargs["payload_sha256"]


def test_uncalibrated_douyin_publish_cancels_automatic_retry(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    error = subprocess.CalledProcessError(4, ["douyin"], stderr="not calibrated")
    manager._run_tracked = MagicMock(side_effect=error)

    assert not manager._publish_claimed_douyin_publication(
        {
            "id": 18, "youtube_id": "video-id", "slice_index": 0,
            "_douyin_launch_ticket_id": "ticket-18", "_douyin_launch_token": "token-18",
        }
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

    assert not manager._publish_claimed_douyin_publication(
        {
            "id": 183, "youtube_id": "video-id", "slice_index": 0,
            "_douyin_launch_ticket_id": "ticket-183", "_douyin_launch_token": "token-183",
        }
    )

    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (183, "CANCELED")
    assert "本次未提交" in kwargs["error_message"]
    assert "停止自动重试" in kwargs["error_message"]
    manager.db.record_platform_ui_failure.assert_called_once()


def test_ticket_bind_failure_immediately_cancels_unstarted_ticket(tmp_path: Path, monkeypatch):
    """父进程尚未启动上传器时，失败必须注销当前 ticket 而非等待 TTL 巡航。"""
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    manager.db.bind_douyin_browser_launch_ticket_payload.return_value = False
    manager.db.cancel_douyin_publication_pre_launch_failure.return_value = True
    manager._run_tracked = MagicMock()

    assert not manager._publish_claimed_douyin_publication(
        {
            "id": 187, "youtube_id": "video-id", "slice_index": 0,
            "_douyin_launch_ticket_id": "ticket-187", "_douyin_launch_token": "token-187",
        }
    )

    manager._run_tracked.assert_not_called()
    manager.db.cancel_douyin_publication_pre_launch_failure.assert_called_once()
    args, kwargs = manager.db.cancel_douyin_publication_pre_launch_failure.call_args
    assert args == (187,)
    assert kwargs["ticket_id"] == "ticket-187"
    assert "完整投稿包不匹配" in kwargs["reason"]
    manager.db.update_douyin_publication_state.assert_not_called()


def test_timeout_immediately_cancels_only_when_ticket_proves_browser_never_started(tmp_path: Path, monkeypatch):
    """进程超时不是天然 UNCERTAIN；未消费 ticket 可证实时必须先安全收口。"""
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    manager._run_tracked = MagicMock(side_effect=subprocess.TimeoutExpired(["douyin"], 1500))
    manager.db.cancel_douyin_publication_pre_launch_failure.return_value = True

    assert not manager._publish_claimed_douyin_publication(
        {
            "id": 188, "youtube_id": "video-id", "slice_index": 0,
            "_douyin_launch_ticket_id": "ticket-188", "_douyin_launch_token": "token-188",
        }
    )

    manager.db.cancel_douyin_publication_pre_launch_failure.assert_called_once()
    args, kwargs = manager.db.cancel_douyin_publication_pre_launch_failure.call_args
    assert args == (188,)
    assert kwargs["ticket_id"] == "ticket-188"
    assert "超时" in kwargs["reason"]
    manager.db.update_douyin_publication_state.assert_not_called()


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


def test_malformed_persistent_douyin_ui_guard_stably_halts_before_browser_action(
    tmp_path: Path,
    monkeypatch,
):
    """账本损坏必须 fail-closed，且不能在构造告警文本时令整轮任务崩溃。"""
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "__malformed_ui_guard_record__",
        "consecutive_failures": "not-an-integer",
        "active": 1,
    }]
    manager._run_tracked = MagicMock()

    manager._reset_douyin_run_guard()

    assert manager._douyin_platform_halted
    assert "打开浏览器前停止" in manager._douyin_halt_reason
    assert not manager._publish_claimed_douyin_publication(
        {"id": 186, "youtube_id": "video-id", "slice_index": 0}
    )
    manager._run_tracked.assert_not_called()
    manager.db.reserve_douyin_browser_action_slot.assert_not_called()


def test_management_verify_guard_skips_review_but_allows_independently_gated_new_submission(
    tmp_path: Path,
    monkeypatch,
):
    """管理页 selector 漂移不能阻断仍受投稿前闸门约束的新片。"""
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "management_verify",
        "consecutive_failures": 2,
        "active": 1,
    }]
    manager.db.get_douyin_publications_by_states.return_value = [
        {"id": 19, "youtube_id": "video-id", "slice_index": 0, "source_kind": "HISTORY"},
    ]
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["douyin"], 0, stdout="accepted", stderr="")
    )
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)

    manager._reset_douyin_run_guard()

    assert not manager._douyin_platform_halted
    assert manager._douyin_management_verify_halted
    assert manager.reconcile_douyin_under_review() == 0
    manager._run_tracked.assert_not_called()
    manager.db.reserve_douyin_browser_action_slot.assert_not_called()

    assert manager._publish_claimed_douyin_publication(
        {
            "id": 185, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW",
            "_douyin_launch_ticket_id": "ticket-185", "_douyin_launch_token": "token-185",
        }
    )
    command = manager._run_tracked.call_args.args[0]
    assert "--publish" in command
    assert "--verify-only" not in command


def test_daily_job_runs_new_sync_but_freezes_history_when_management_guard_is_active(
    tmp_path: Path,
    monkeypatch,
):
    """持久管理页熔断不能让正常 NEW 同步与旧 HISTORY 回填混为一谈。"""
    manager = _manager_with_assets(tmp_path)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_douyin_under_review = MagicMock()
    manager._run_douyin_new_sync = MagicMock(return_value=True)
    manager._run_douyin_history_migration = MagicMock()
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "management_verify",
        "consecutive_failures": 2,
        "active": 1,
    }]
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "enable_kuaishou_browser_publishing", False)
    monkeypatch.setattr(settings, "wechat_publishing_paused", True)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    manager.run_daily_job()

    manager.reconcile_douyin_under_review.assert_called_once()
    manager._run_douyin_new_sync.assert_called_once()
    manager._run_douyin_history_migration.assert_not_called()


def test_daily_job_loads_publish_guard_before_deferred_wechat_recovery(
    tmp_path: Path,
    monkeypatch,
):
    """视频号补发不能在每日任务恢复持久投稿熔断前抢先创建抖音 NEW。"""
    manager = _manager_with_assets(tmp_path)
    manager.reconcile_wechat_under_review = MagicMock()
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_douyin_under_review = MagicMock()
    manager._run_douyin_new_sync = MagicMock(return_value=True)
    manager._run_douyin_history_migration = MagicMock()
    manager._run_garbage_collection = MagicMock()
    manager._queue_and_publish_new_douyin_video = MagicMock(return_value=True)
    manager.db.get_douyin_publication.return_value = None
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "publish_pre_submit",
        "consecutive_failures": 2,
        "active": 1,
    }]

    def recover_one_deferred_video() -> int:
        manager._defer_wechat_and_publish_kuaishou("video-id")
        return 1

    manager.recover_deferred_wechat_publications = MagicMock(side_effect=recover_one_deferred_video)
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "enable_kuaishou_browser_publishing", False)
    monkeypatch.setattr(settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    manager.run_daily_job()

    manager.recover_deferred_wechat_publications.assert_called_once()
    manager._queue_and_publish_new_douyin_video.assert_not_called()
    manager._run_douyin_new_sync.assert_not_called()
    manager._run_douyin_history_migration.assert_not_called()


def test_deferred_wechat_management_guard_still_dispatches_new_douyin(
    tmp_path: Path,
    monkeypatch,
):
    """管理页 selector 漂移不得阻断独立投稿前闸门仍会检查的 NEW 补发。"""
    manager = _manager_with_assets(tmp_path)
    manager._queue_and_publish_new_douyin_video = MagicMock(return_value=True)
    manager._run_garbage_collection = MagicMock()
    manager.db.get_douyin_publication.return_value = None
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "management_verify",
        "consecutive_failures": 2,
        "active": 1,
    }]
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "enable_kuaishou_browser_publishing", False)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    manager._defer_wechat_and_publish_kuaishou("video-id")

    assert manager._douyin_management_verify_halted
    assert not manager._douyin_platform_halted
    manager._queue_and_publish_new_douyin_video.assert_called_once_with("video-id", slice_index=0)


@pytest.mark.parametrize("stage", ["publish_pre_submit", "future_ui_stage"])
def test_direct_new_retry_stops_before_claim_for_publish_blocking_guard(
    tmp_path: Path,
    monkeypatch,
    stage: str,
):
    """投稿页或未知 UI 熔断不能让遗留 NEW 重试先领取账本。"""
    manager = _manager_with_assets(tmp_path)
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": stage,
        "consecutive_failures": 2,
        "active": 1,
    }]
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    assert not manager._retry_one_douyin_new_video()

    manager.db.claim_next_douyin_publication.assert_not_called()
    manager._publish_claimed_douyin_publication.assert_not_called()


def test_direct_new_retry_allows_management_verify_guard(
    tmp_path: Path,
    monkeypatch,
):
    """管理页熔断不应将独立投稿前闸门保护的 NEW 重试整体关闭。"""
    manager = _manager_with_assets(tmp_path)
    claimed = {"id": 186, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW"}
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "management_verify",
        "consecutive_failures": 2,
        "active": 1,
    }]
    manager.db.claim_next_douyin_publication.return_value = claimed
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)
    manager._is_public_publish_window = MagicMock(return_value=True)
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    assert manager._retry_one_douyin_new_video()

    assert manager._douyin_management_verify_halted
    assert not manager._douyin_platform_halted
    manager.db.claim_next_douyin_publication.assert_called_once()
    manager._publish_claimed_douyin_publication.assert_called_once_with(claimed)


@pytest.mark.parametrize("stage", ["management_verify", "publish_pre_submit", "future_ui_stage"])
def test_direct_history_migration_stops_before_preview_create_or_claim_for_active_guard(
    tmp_path: Path,
    monkeypatch,
    stage: str,
):
    """任一达到阈值的 UI 熔断都必须在 HISTORY 的账本写入和浏览器动作前停止。"""
    manager = _manager_with_assets(tmp_path)
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": stage,
        "consecutive_failures": 2,
        "active": 1,
    }]
    manager._is_public_publish_window = MagicMock(return_value=True)
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    manager._run_douyin_history_migration()

    manager.db.get_platform_backfill_preview_candidates.assert_not_called()
    manager.db.create_douyin_publication.assert_not_called()
    manager.db.claim_next_douyin_history_publication.assert_not_called()
    manager._publish_claimed_douyin_publication.assert_not_called()


@pytest.mark.parametrize("stage", ["management_verify", "publish_pre_submit", "future_ui_stage"])
def test_direct_douyin_review_loads_persistent_guard_before_browser(
    tmp_path: Path,
    monkeypatch,
    stage: str,
):
    """任一活动 UI 熔断都必须在独立审核回查查询和浏览器槽位前停止。"""
    manager = _manager_with_assets(tmp_path)
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": stage,
        "consecutive_failures": 2,
        "active": 1,
    }]
    manager.db.get_douyin_publications_by_states.return_value = [{
        "id": 20,
        "youtube_id": "video-id",
        "slice_index": 0,
        "source_kind": "HISTORY",
    }]
    manager._run_tracked = MagicMock(
        return_value=subprocess.CompletedProcess(["douyin"], 0, stdout="published", stderr="")
    )
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)

    assert manager.reconcile_douyin_under_review() == 0

    manager.db.get_douyin_publications_by_states.assert_not_called()
    manager.db.reserve_douyin_browser_action_slot.assert_not_called()
    manager._run_tracked.assert_not_called()


def test_direct_new_queue_loads_publish_guard_before_ledger_mutation(
    tmp_path: Path,
    monkeypatch,
):
    """非每日入口也不能在投稿前熔断活动时先创建或领取 NEW 账本。"""
    manager = _manager_with_assets(tmp_path)
    manager.db.get_platform_ui_failure_streaks.return_value = [{
        "platform": "douyin",
        "stage": "publish_pre_submit",
        "consecutive_failures": 2,
        "active": 1,
    }]
    manager.db.get_douyin_publication.return_value = None
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_ui_failure_recording_threshold", 2)
    monkeypatch.setattr(manager, "_is_public_publish_window", MagicMock(return_value=False))

    assert not manager._queue_and_publish_new_douyin_video("video-id")

    manager.db.create_douyin_publication.assert_not_called()
    manager.db.claim_douyin_publication.assert_not_called()


def test_deferred_new_queue_is_consumed_once_by_the_capped_sync_runner(
    tmp_path: Path,
    monkeypatch,
):
    """视频号补发只入队，由统一 NEW 消费器按每轮上限领取一次。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    _add_published_video_assets(manager, "first-new")
    _add_published_video_assets(manager, "second-new")
    manager._is_public_publish_window = MagicMock(return_value=True)
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_require_wechat_public_confirmation", False)
    monkeypatch.setattr(settings, "douyin_new_sync_max_per_run", 1)
    monkeypatch.setattr(settings, "douyin_new_sync_daily_limit", 10)

    assert manager._queue_and_publish_new_douyin_video("first-new")
    assert manager._queue_and_publish_new_douyin_video("second-new")

    manager._publish_claimed_douyin_publication.assert_not_called()
    assert manager.db.get_douyin_publication("first-new")["state"] == "QUEUED"
    second = manager.db.get_douyin_publication("second-new")
    assert second is not None
    assert second["state"] == "QUEUED"

    assert manager._run_douyin_new_sync()

    assert manager._publish_claimed_douyin_publication.call_count == 1
    assert manager.db.get_douyin_publication("first-new")["state"] == "UPLOADING"
    assert manager.db.get_douyin_publication("second-new")["state"] == "QUEUED"


def test_new_retry_and_sync_share_per_run_action_budget(
    tmp_path: Path,
    monkeypatch,
):
    """独立 NEW 重试已领取一条后，同轮同步不得再领取第二条。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    _add_published_video_assets(manager, "retry-first")
    _add_published_video_assets(manager, "retry-second")
    for youtube_id in ("retry-first", "retry-second"):
        vertical = manager._OUT_DIR / f"{youtube_id}_vertical.mp4"
        manager.db.create_douyin_publication(
            youtube_id,
            manager._sha256_file(vertical),
            str(vertical),
            source_kind="NEW",
        )
    manager._is_public_publish_window = MagicMock(return_value=True)
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_new_sync_max_per_run", 1)
    monkeypatch.setattr(settings, "douyin_new_sync_daily_limit", 10)

    assert manager._retry_one_douyin_new_video()
    assert manager._run_douyin_new_sync()

    assert manager._publish_claimed_douyin_publication.call_count == 1
    assert manager.db.get_douyin_publication("retry-first")["state"] == "UPLOADING"
    assert manager.db.get_douyin_publication("retry-second")["state"] == "QUEUED"


def test_daily_run_resets_new_action_budget_before_sync(
    tmp_path: Path,
    monkeypatch,
):
    """常驻管理器的下一次 daily run 必须重新获得本轮 NEW 动作额度。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    _add_published_video_assets(manager, "next-run-new")
    vertical = manager._OUT_DIR / "next-run-new_vertical.mp4"
    manager.db.create_douyin_publication(
        "next-run-new",
        manager._sha256_file(vertical),
        str(vertical),
        source_kind="NEW",
    )
    manager._douyin_new_actions_claimed = 1
    manager._is_public_publish_window = MagicMock(return_value=True)
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)
    manager._recover_stale_douyin_prelaunch_attempts = MagicMock(return_value=0)
    manager.reconcile_wechat_under_review = MagicMock(return_value=0)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager.reconcile_douyin_under_review = MagicMock(return_value=0)
    manager._run_douyin_history_migration = MagicMock()
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "enable_kuaishou_browser_publishing", False)
    monkeypatch.setattr(settings, "wechat_publishing_paused", True)
    monkeypatch.setattr(settings, "douyin_new_sync_max_per_run", 1)
    monkeypatch.setattr(settings, "douyin_new_sync_daily_limit", 10)

    manager._run_daily_job_unlocked()

    assert manager._publish_claimed_douyin_publication.call_count == 1


def test_post_submit_unconfirmed_is_uncertain(tmp_path: Path, monkeypatch):
    manager = _manager_with_assets(tmp_path)
    monkeypatch.setattr(settings, "enable_subtitle_censorship", False)
    manager._run_tracked = MagicMock(side_effect=subprocess.CalledProcessError(7, ["douyin"]))

    assert not manager._publish_claimed_douyin_publication(
        {
            "id": 184, "youtube_id": "video-id", "slice_index": 0,
            "_douyin_launch_ticket_id": "ticket-184", "_douyin_launch_token": "token-184",
        }
    )

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
    assert manager._douyin_management_verify_halted
    assert not manager._douyin_platform_halted


def test_douyin_review_reconciliation_records_ui_failure_when_match_is_unknown(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    manager.db.get_douyin_publications_by_states.return_value = [
        {"id": 19, "youtube_id": "video-id", "slice_index": 0, "source_kind": "NEW"},
    ]
    manager._run_tracked = MagicMock(side_effect=subprocess.CalledProcessError(7, ["douyin"]))
    manager._throttle_douyin_browser_action = MagicMock()

    previous = settings.enable_douyin_browser_publishing
    settings.enable_douyin_browser_publishing = True
    try:
        assert manager.reconcile_douyin_under_review() == 0
    finally:
        settings.enable_douyin_browser_publishing = previous

    manager.db.record_platform_ui_failure.assert_called_once()
    args, kwargs = manager.db.update_douyin_publication_state.call_args
    assert args == (19, "UNCERTAIN")
    assert "未能精确确认" in kwargs["error_message"]
    assert manager._douyin_management_verify_halted
    assert not manager._douyin_platform_halted


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


def test_douyin_review_limit_is_applied_to_history_and_new_items(tmp_path: Path):
    manager = _manager_with_assets(tmp_path)
    (tmp_path / "history-id_copy.txt").write_text("历史文案", encoding="utf-8")
    (tmp_path / "history-id_title.txt").write_text("历史标题", encoding="utf-8")
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
    assert str(tmp_path / "history-id_copy.txt") in command
    assert "video-id" not in " ".join(command)
    manager.db.update_douyin_publication_state.assert_called_once_with(18, "PUBLISHED")


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


def test_douyin_history_migration_zero_limit_is_disabled_before_reading_candidates(tmp_path: Path):
    """历史回填没有正数上限时宁可停用，不能在解除熔断后无界投稿。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.db.get_platform_backfill_preview_candidates = MagicMock()

    previous_enabled = settings.enable_douyin_browser_publishing
    previous_limit = settings.douyin_history_daily_limit
    settings.enable_douyin_browser_publishing = True
    settings.douyin_history_daily_limit = 0
    try:
        manager._run_douyin_history_migration()
    finally:
        settings.enable_douyin_browser_publishing = previous_enabled
        settings.douyin_history_daily_limit = previous_limit

    manager.db.get_platform_backfill_preview_candidates.assert_not_called()


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


def test_douyin_new_sync_can_queue_unconfirmed_wechat_when_policy_is_disabled(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    _add_published_video_assets(manager, "wechat-unconfirmed-new")
    manager.db.record_wechat_submission_acceptance(
        "wechat-unconfirmed-new",
        evidence_path=None,
        error_message="视频号已受理，等待公开确认",
        final_title="测试标题",
    )
    manager._is_public_publish_window = MagicMock(return_value=True)
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)

    previous_enabled = settings.enable_douyin_browser_publishing
    previous_policy = settings.douyin_require_wechat_public_confirmation
    settings.enable_douyin_browser_publishing = True
    settings.douyin_require_wechat_public_confirmation = False
    try:
        assert manager._run_douyin_new_sync()
    finally:
        settings.enable_douyin_browser_publishing = previous_enabled
        settings.douyin_require_wechat_public_confirmation = previous_policy

    publication = manager.db.get_douyin_publication("wechat-unconfirmed-new")
    assert publication is not None
    assert publication["source_kind"] == "NEW"
    manager._publish_claimed_douyin_publication.assert_called_once()


def test_douyin_new_sync_with_explicit_caps_publishes_all_eligible_items(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    _add_published_video_assets(manager, "wechat-published-new")
    _add_published_video_assets(manager, "wechat-accepted-new")
    manager.db.record_wechat_submission_acceptance(
        "wechat-accepted-new",
        evidence_path=None,
        error_message="视频号已受理，等待公开确认",
        final_title="测试标题",
    )
    manager._is_public_publish_window = MagicMock(return_value=True)
    manager._publish_claimed_douyin_publication = MagicMock(return_value=True)

    original = {
        "enabled": settings.enable_douyin_browser_publishing,
        "require_public": settings.douyin_require_wechat_public_confirmation,
        "lookback": settings.douyin_new_sync_lookback_hours,
        "per_run": settings.douyin_new_sync_max_per_run,
        "daily": settings.douyin_new_sync_daily_limit,
    }
    settings.enable_douyin_browser_publishing = True
    settings.douyin_require_wechat_public_confirmation = False
    settings.douyin_new_sync_lookback_hours = 72
    settings.douyin_new_sync_max_per_run = 2
    settings.douyin_new_sync_daily_limit = 10
    try:
        assert manager._run_douyin_new_sync()
    finally:
        settings.enable_douyin_browser_publishing = original["enabled"]
        settings.douyin_require_wechat_public_confirmation = original["require_public"]
        settings.douyin_new_sync_lookback_hours = original["lookback"]
        settings.douyin_new_sync_max_per_run = original["per_run"]
        settings.douyin_new_sync_daily_limit = original["daily"]

    assert manager._publish_claimed_douyin_publication.call_count == 2
    claimed_ids = {
        call.args[0]["youtube_id"]
        for call in manager._publish_claimed_douyin_publication.call_args_list
    }
    assert claimed_ids == {"wechat-published-new", "wechat-accepted-new"}


def test_douyin_new_sync_aggregates_missing_asset_notifications_with_action_cap(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.send_telegram_msg = MagicMock()
    for yid in ("missing-one", "missing-two", "missing-three"):
        assert manager.db.add_video(yid, "缺素材视频", "channel", score=80)
        manager.db.update_video_status(yid, "PUBLISHED")

    original = {
        "enabled": settings.enable_douyin_browser_publishing,
        "lookback": settings.douyin_new_sync_lookback_hours,
        "per_run": settings.douyin_new_sync_max_per_run,
        "daily": settings.douyin_new_sync_daily_limit,
    }
    settings.enable_douyin_browser_publishing = True
    settings.douyin_new_sync_lookback_hours = 72
    settings.douyin_new_sync_max_per_run = 1
    settings.douyin_new_sync_daily_limit = 10
    try:
        assert manager._queue_missing_douyin_new_publications() == 0
    finally:
        settings.enable_douyin_browser_publishing = original["enabled"]
        settings.douyin_new_sync_lookback_hours = original["lookback"]
        settings.douyin_new_sync_max_per_run = original["per_run"]
        settings.douyin_new_sync_daily_limit = original["daily"]

    manager.send_telegram_msg.assert_called_once()
    assert "3 条" in manager.send_telegram_msg.call_args.args[0]


def test_douyin_new_sync_uses_safe_discovery_boundaries_behind_action_caps(tmp_path: Path, monkeypatch):
    """自动投稿受限时，发现仍可越过缺素材项检查有限候选集。"""
    manager = _manager_with_assets(tmp_path)
    manager.db.get_unqueued_douyin_new_videos.return_value = []
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_new_sync_lookback_hours", 0)
    monkeypatch.setattr(settings, "douyin_new_sync_max_per_run", 1)
    monkeypatch.setattr(settings, "douyin_new_sync_daily_limit", 10)

    assert manager._queue_missing_douyin_new_publications() == 0

    manager.db.get_unqueued_douyin_new_videos.assert_called_once_with(
        lookback_hours=72,
        limit=100,
        require_wechat_public_confirmation=False,
    )


def test_douyin_new_sync_zero_action_limits_disable_automatic_scan(tmp_path: Path, monkeypatch):
    """0 不得再表示自动 NEW 无限领取、建账或浏览器提交。"""
    manager = _manager_with_assets(tmp_path)
    manager.db.get_unqueued_douyin_new_videos.return_value = []
    manager.db.claim_next_douyin_publication.return_value = None
    manager._is_public_publish_window = MagicMock(return_value=True)
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_new_sync_max_per_run", 0)
    monkeypatch.setattr(settings, "douyin_new_sync_daily_limit", 0)

    assert manager._run_douyin_new_sync()

    manager.db.get_unqueued_douyin_new_videos.assert_not_called()
    manager.db.claim_next_douyin_publication.assert_not_called()


def test_douyin_new_sync_material_gap_alert_is_persistently_deduplicated(tmp_path: Path, monkeypatch):
    """同一缺素材 NEW 集合可告警一次，但绝不每分钟重复发送或建取消账本。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    for yid in ("missing-one", "missing-two"):
        assert manager.db.add_video(yid, "缺素材视频", "channel", score=80)
        manager.db.update_video_status(yid, "PUBLISHED")
    manager.telegram_token = "test-token"
    manager.telegram_chat_id = "test-chat"

    calls = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 2401}}

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("video_processing.telegram_delivery.requests.post", fake_post)
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(settings, "douyin_new_sync_lookback_hours", 0)
    monkeypatch.setattr(settings, "douyin_new_sync_max_per_run", 1)
    monkeypatch.setattr(settings, "douyin_new_sync_daily_limit", 10)

    assert manager._queue_missing_douyin_new_publications() == 0
    assert manager._queue_missing_douyin_new_publications() == 0

    assert len(calls) == 1
    assert "Douyin NEW material gap" in calls[0][1]["json"]["text"]
    assert "2 条" in calls[0][1]["json"]["text"]
    assert manager.db.get_douyin_publication("missing-one") is None
    assert manager.db.get_douyin_publication("missing-two") is None

"""盘中轻量提交守卫测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-07 | Codex | 验证盘中只放行 preparation_ready 成片，未完成任务不被领取 |
| 1.1.0 | 2026-08-07 | Codex | 覆盖 checkpoint-only 失败时不启动下载、转写或渲染 |
| 1.2.0 | 2026-08-24 | Codex | 显式声明无提交证据的替身，避免 MagicMock 真值绕过仅提交检查点测试。 |
| 1.3.0 | 2026-09-09 | Codex | 覆盖源视频旁和切片各自 ASS 检查、坏字幕提交前回队 |
"""

from unittest.mock import MagicMock
import pysubs2
import pytest

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager


def _manager(tmp_path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager.db = MagicMock()
    manager.send_telegram_msg = MagicMock()
    manager._process_single_video = MagicMock()
    return manager


def test_market_guard_submits_only_preparation_ready_video(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    ready = {"youtube_id": "ready", "slice_index": 0, "preparation_ready": 1}
    manager.db.get_high_score_pending_videos.side_effect = [[ready], []]
    manager.db.claim_video_for_processing.return_value = True
    monkeypatch.setattr(type(settings), "is_us_market_guard_window", lambda _self: True)

    manager.process_high_score_videos(limit=1)

    manager.db.claim_video_for_processing.assert_called_once_with("ready", slice_index=0)
    manager._process_single_video.assert_called_once_with(ready, submission_only=True)


def test_market_guard_does_not_claim_unprepared_video(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    manager.db.get_high_score_pending_videos.return_value = [
        {"youtube_id": "not-ready", "slice_index": 0, "preparation_ready": 0}
    ]
    monkeypatch.setattr(type(settings), "is_us_market_guard_window", lambda _self: True)

    manager.process_high_score_videos(limit=1)

    manager.db.claim_video_for_processing.assert_not_called()
    manager._process_single_video.assert_not_called()


def test_submission_only_invalid_checkpoint_never_starts_heavy_processing(tmp_path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.db = MagicMock()
    manager.send_telegram_msg = MagicMock()
    manager._run_tracked = MagicMock()
    manager._block_duplicate_wechat_submission_if_needed = MagicMock(return_value=False)
    manager._has_wechat_submission_terminal_state = MagicMock(return_value=False)

    manager._process_single_video(
        {"youtube_id": "missing-assets", "title": "Missing assets", "slice_index": 0},
        submission_only=True,
    )

    manager._run_tracked.assert_not_called()
    manager.db.update_video_status.assert_called_once()
    args, kwargs = manager.db.update_video_status.call_args
    assert args == ("missing-assets", "PENDING")
    assert "盘中仅提交检查点未通过" in kwargs["error_msg"]


@pytest.mark.parametrize("slice_index", [0, 1])
def test_checkpoint_reads_actual_input_ass_not_legacy_root(tmp_path, slice_index):
    manager = object.__new__(PipelineManager)
    manager._OUT_DIR = tmp_path
    original = tmp_path / "original_video" / "video.mp4"
    original.parent.mkdir()
    original.touch()
    manager._find_downloaded_video = lambda _: original
    prefix = "video_s1" if slice_index else "video"
    (tmp_path / f"{prefix}_title.txt").write_text("财政部回购国债")
    (tmp_path / f"{prefix}_copy.txt").write_text("视频讨论财政部回购国债的操作背景。")
    (tmp_path / f"{prefix}_label.txt").touch()
    actual_ass = (tmp_path / f"{prefix}.ass") if slice_index else original.with_suffix(".ass")
    subs = pysubs2.SSAFile()
    event = pysubs2.SSAEvent(start=7200, end=11600, text=r"{\fnGeorgia}English\N{\fnHiragino Sans GB}（承接上文）")
    subs.append(event)
    subs.save(str(actual_ass))
    error = manager._prepared_submission_checkpoint_error({"youtube_id": "video", "slice_index": slice_index})
    assert "翻译占位符" in error
    event.text = r"{\fnGeorgia}English\N{\fnHiragino Sans GB}正常译文"
    subs.save(str(actual_ass))
    assert manager._prepared_submission_checkpoint_error({"youtube_id": "video", "slice_index": slice_index}) == "缺少有效竖版成片"

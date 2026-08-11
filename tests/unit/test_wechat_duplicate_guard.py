"""视频号重复提交本地证据防线测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-03 | Codex | 覆盖既有视频号提交后证据阻止自动重发并恢复本地已发布态 |
| 1.1.0 | 2026-08-10 | Codex | 补充既有后台截图自动回填视频号确认账本 |
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
    assert row["status"] == "UNDER_REVIEW"
    assert "拒绝自动重发" in row["error_msg"]
    assert str(evidence) in row["error_msg"]
    publication = manager.db.get_wechat_publication("wechat-guard")
    assert publication["state"] == "UNDER_REVIEW"
    assert publication["evidence_path"] == str(evidence)
    assert messages and "submission under review" in messages[0]


def test_missing_wechat_submission_evidence_does_not_change_status(tmp_path: Path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    assert manager.db.add_video("wechat-new", "Title", "channel", score=90)
    manager.db.update_video_status("wechat-new", "DOWNLOADING")

    assert manager._block_duplicate_wechat_submission_if_needed("wechat-new", "wechat-new") is False

    assert manager.db.get_video_by_youtube_id("wechat-new")["status"] == "DOWNLOADING"

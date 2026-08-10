"""视频号后台确认账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-10 | Codex | 覆盖后台列表证据落账、待核验状态和面板聚合优先级 |
"""

from __future__ import annotations

import pytest

from video_processing.db.database import PipelineDB


def _add_video(db: PipelineDB, youtube_id: str = "wechat-ledger") -> None:
    assert db.add_video(youtube_id, "Title", "channel", score=80)
    db.update_video_status(youtube_id, "PUBLISHED")


def test_wechat_confirmation_requires_post_list_evidence(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db)

    with pytest.raises(ValueError, match="requires post-list evidence"):
        db.record_wechat_publication_confirmation("wechat-ledger", evidence_path=None)


def test_wechat_confirmation_is_upserted_and_preferred_by_platform_map(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db)
    evidence = tmp_path / "post_list_after_submission.png"
    evidence.write_bytes(b"png")

    first = db.record_wechat_publication_confirmation(
        "wechat-ledger", evidence_path=str(evidence),
    )
    second = db.record_wechat_publication_confirmation(
        "wechat-ledger", evidence_path=str(evidence),
    )

    assert first["id"] == second["id"]
    assert second["state"] == "PUBLISHED"
    video = db.get_video_by_youtube_id("wechat-ledger")
    publications = db.get_video_publications_map([video["id"]])
    assert publications[video["id"]]["wechat"]["state"] == "PUBLISHED"
    assert publications[video["id"]]["wechat"]["published_at"] is not None
    assert publications[video["id"]]["wechat"]["error"] is None


def test_wechat_uncertain_confirmation_is_visible_in_platform_map(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "wechat-uncertain")
    reason = "提交后后台列表截图未落盘；禁止自动重传。"

    db.record_wechat_publication_confirmation(
        "wechat-uncertain",
        evidence_path=None,
        state="UNCERTAIN",
        error_message=reason,
    )

    video = db.get_video_by_youtube_id("wechat-uncertain")
    publications = db.get_video_publications_map([video["id"]])
    assert publications[video["id"]]["wechat"]["state"] == "UNCERTAIN"
    assert publications[video["id"]]["wechat"]["published_at"] is None
    assert publications[video["id"]]["wechat"]["error"] == reason

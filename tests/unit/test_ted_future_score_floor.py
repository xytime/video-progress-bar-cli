"""TED/TEDx 新视频托底与存量隔离。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-25 | Codex | 验证新视频托底及历史主视频、切片从两个自动候选入口隔离。 |
"""

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager


TED = "UCAuUUnT6oDeKwE6v1NGQxug"
TEDX = "UCsT0YIqwnpJCM-mx7-gSA4Q"


def test_ted_floor_only_admits_future_auto_videos(tmp_path, monkeypatch):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    db = manager.db
    assert db.add_video("old-ted", "Old TED", TED, score=0, source="AUTO", view_count=1)
    boundary = db.get_video_by_youtube_id("old-ted")["id"]
    monkeypatch.setattr(settings, "ted_auto_publish_after_id", boundary)
    monkeypatch.setattr(settings, "speech_publish_score_line", 40)

    assert db.add_video("new-ted", "New TED", TED, score=0, source="AUTO", view_count=1)
    assert db.add_video("new-tedx", "New TEDx", TEDX, score=0, source="AUTO", view_count=1)
    assert db.add_video("other", "Other channel", "other-channel", score=0, source="AUTO", view_count=1)
    assert db.add_video("discovery", "TED discovery", TED, score=0, source="DISCOVERY", view_count=1)
    assert db.add_video("manual-lock", "Manually scored TED", TED, score=0, source="AUTO", view_count=1)
    db.update_video_score("manual-lock", 5, force=True)

    manager.score_pending_videos()

    scores = {
        yid: db.get_video_by_youtube_id(yid)["score"]
        for yid in ("old-ted", "new-ted", "new-tedx", "other", "discovery", "manual-lock")
    }
    assert scores == {
        "old-ted": 0, "new-ted": 40, "new-tedx": 40,
        "other": 0, "discovery": 0, "manual-lock": 5,
    }

    # 旧视频日后自然涨分或产生新切片，也不能从自动候选入口释放。
    db.update_video_score("old-ted", 90, force=True)
    assert db.batch_add_videos([{
        "youtube_id": "old-ted", "slice_index": 1, "parent_id": boundary,
        "title": "Old TED slice", "channel_id": TED, "score": 90, "source": "AUTO",
    }])

    queue = db.get_high_score_pending_videos(
        min_score=75, limit=10, channel_min_scores=settings.auto_publish_channel_min_scores,
    )
    prep = db.get_high_score_preparation_candidates(
        min_score=75, limit=10, channel_min_scores=settings.auto_publish_channel_min_scores,
    )
    assert {row["youtube_id"] for row in queue} == {"new-ted", "new-tedx"}
    assert {row["youtube_id"] for row in prep} == {"new-ted", "new-tedx"}


def test_ted_floor_is_disabled_without_boundary(tmp_path, monkeypatch):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    monkeypatch.setattr(settings, "ted_auto_publish_after_id", 0)
    assert manager.db.add_video("ted-disabled", "TED", TED, score=0, source="AUTO", view_count=1)

    manager.score_pending_videos()

    assert manager.db.get_video_by_youtube_id("ted-disabled")["score"] == 0
    manager.db.update_video_score("ted-disabled", 90, force=True)
    assert [row["youtube_id"] for row in manager.db.get_high_score_pending_videos()] == ["ted-disabled"]

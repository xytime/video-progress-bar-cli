"""频道访问减压策略与分频道发布线回归测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0   | 2026-07-12 | Codex  | 覆盖6/12/24小时熔断、成功复位及演讲类40分发布线 |
| 1.1.0   | 2026-07-28 | Codex  | 覆盖 RSS 降级成功复位与待补全候选转 PENDING 语义 |
"""
import datetime

from scripts import monitor_channels
from video_processing.db import PipelineDB


def test_access_backoff_grows_and_success_resets():
    now = datetime.datetime(2026, 7, 12, 12, 0, 0)
    state = {}

    for expected_hours in (6, 12, 24, 24):
        monitor_channels._record_access_result("channel", "limited", now, state)
        until = datetime.datetime.fromisoformat(state["channel"]["cooldown_until"])
        assert until - now == datetime.timedelta(hours=expected_hours)
        assert monitor_channels._is_backoff_active("channel", now, state)

    monitor_channels._record_access_result("channel", "ok", now, state)
    assert "channel" not in state


def test_rss_degraded_result_also_resets_access_backoff():
    now = datetime.datetime(2026, 7, 28, 12, 0, 0)
    state = {}
    monitor_channels._record_access_result("channel", "limited", now, state)

    monitor_channels._record_access_result("channel", "degraded", now, state)

    assert "channel" not in state


def test_channel_specific_publish_line(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("speech00001", "speech", "speech-channel", score=40, source="AUTO")
    db.add_video("normal00001", "normal low", "normal-channel", score=40, source="AUTO")
    db.add_video("normal00002", "normal high", "normal-channel", score=75, source="AUTO")

    rows = db.get_high_score_pending_videos(
        min_score=75,
        limit=10,
        channel_min_scores={"speech-channel": 40},
    )

    assert {row["youtube_id"] for row in rows} == {"speech00001", "normal00002"}


def test_rss_candidate_waits_for_complete_metadata(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    result = db.upsert_monitored_video(
        "rss-pending-1", "RSS title", "channel", zh_title="RSS 标题",
        duration_sec=None, view_count=None, like_count=None, upload_date="20260728",
        metadata_complete=False,
    )

    assert result == "inserted"
    assert [row["youtube_id"] for row in db.get_videos_by_status("METADATA_PENDING")] == ["rss-pending-1"]
    assert db.get_high_score_pending_videos(min_score=0, limit=10) == []

    result = db.upsert_monitored_video(
        "rss-pending-1", "API title", "channel", zh_title="API 标题",
        duration_sec=600, view_count=3000, like_count=120, upload_date="20260728",
        metadata_complete=True,
    )

    rows = db.get_videos_by_status("PENDING")
    assert result == "refreshed"
    assert len(rows) == 1
    assert rows[0]["duration_sec"] == 600
    assert rows[0]["view_count"] == 3000

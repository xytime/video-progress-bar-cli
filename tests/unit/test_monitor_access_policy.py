"""频道访问减压策略与分频道发布线回归测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0   | 2026-07-12 | Codex  | 覆盖6/12/24小时熔断、成功复位及演讲类40分发布线 |
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

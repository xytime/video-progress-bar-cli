"""低成本重评的轮转、冷却和统计写入回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-25 | Codex | 覆盖低播放新片不再被埋没、抓取冷却及批量统计边界 |
"""

from types import SimpleNamespace

from video_processing.db.database import PipelineDB
from video_processing.scoring import THE_ECONOMIST_CHANNEL_ID
from video_processing.utils import youtube_catalog


def _set_age(db, youtube_id, age):
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE processed_videos SET created_at = datetime('now', ?) WHERE youtube_id = ?",
            (age, youtube_id),
        )
        conn.commit()


def test_new_low_view_video_is_selected_ahead_of_old_high_view_backlog(tmp_path):
    db = PipelineDB(str(tmp_path / "rescore.db"))
    for index in range(60):
        yid = f"older-{index}"
        assert db.add_video(yid, yid, "ordinary", score=1, view_count=10_000, like_count=1)
        _set_age(db, yid, "-2 days")
    assert db.add_video("cold-start", "Cold start", "ordinary", score=1, view_count=32, like_count=8)
    _set_age(db, "cold-start", "-2 hours")

    candidates = db.get_rescore_candidates(limit=50)
    assert len(candidates) == 50
    assert candidates[0]["youtube_id"] == "cold-start"


def test_success_updates_metrics_and_cools_recheck_without_lowering_score(tmp_path):
    db = PipelineDB(str(tmp_path / "rescore.db"))
    assert db.add_video("grower", "Grower", "ordinary", score=1, view_count=32, like_count=8)
    _set_age(db, "grower", "-2 hours")
    assert db.record_rescore_attempt("grower", 0, 14_873, 302) == (1, 47)

    row = db.get_video_by_youtube_id("grower")
    assert (row["view_count"], row["like_count"], row["score"]) == (14_873, 302, 47)
    assert row["rescore_checked_at"] is not None
    assert row["score_input_signature"] == "ordinary:14873:302"
    assert db.get_rescore_candidates(limit=50) == []

    with db.get_connection() as conn:
        conn.execute(
            "UPDATE processed_videos SET rescore_checked_at = datetime('now', '-4 hours') WHERE youtube_id = 'grower'"
        )
        conn.commit()
    assert [r["youtube_id"] for r in db.get_rescore_candidates(limit=50)] == ["grower"]
    assert db.record_rescore_attempt("grower", 0, 14_900, 100) == (47, 47)
    assert db.get_video_by_youtube_id("grower")["view_count"] == 14_900


def test_failed_fetch_is_cooled_and_locked_video_is_untouched(tmp_path):
    db = PipelineDB(str(tmp_path / "rescore.db"))
    assert db.add_video("retry", "Retry", "ordinary", score=1, view_count=32, like_count=8)
    _set_age(db, "retry", "-2 hours")
    assert db.record_rescore_attempt("retry", 0, None, None) == (1, 1)
    assert db.get_rescore_candidates(limit=50) == []
    row = db.get_video_by_youtube_id("retry")
    assert (row["view_count"], row["like_count"], row["score"]) == (32, 8, 1)

    db.update_video_score("retry", 100, force=True)
    assert db.record_rescore_attempt("retry", 0, 20_000, 800) is None
    assert db.get_video_by_youtube_id("retry")["view_count"] == 32


def test_channel_line_and_blacklist_remain_hard_filters(tmp_path):
    db = PipelineDB(str(tmp_path / "rescore.db"))
    assert db.add_channel("speech", "Speech", status="APPROVED")
    assert db.add_channel("blocked-channel", "Blocked", status="BLACKLISTED")
    for yid, channel, score in (
        ("speech-ready", "speech", 45),
        ("speech-low", "speech", 20),
        ("blocked-channel-video", "blocked-channel", 1),
        ("blocked-video", "ordinary", 1),
        ("capped-video", THE_ECONOMIST_CHANNEL_ID, 60),
    ):
        assert db.add_video(yid, yid, channel, score=score, view_count=20)
        _set_age(db, yid, "-2 hours")
    assert db.add_to_blacklist("blocked-video", reason="test")

    candidates = db.get_rescore_candidates(limit=50, channel_min_scores={"speech": 40})
    assert [row["youtube_id"] for row in candidates] == ["speech-low"]
    assert db.record_rescore_attempt("blocked-channel-video", 0, 20_000, 800) is None
    assert db.record_rescore_attempt("blocked-video", 0, 20_000, 800) is None
    assert db.get_video_by_youtube_id("blocked-channel-video")["score"] == 1
    assert db.record_rescore_attempt("capped-video", 0, 20_000, 800) == (60, 60)


def test_data_api_statistics_are_batched_and_missing_views_are_not_success(monkeypatch):
    calls = []

    def fake_request(endpoint, params, timeout):
        calls.append((endpoint, params["id"].split(","), timeout))
        return {"items": [
            {"id": video_id, "statistics": {"viewCount": "100", "likeCount": "4"}}
            for video_id in params["id"].split(",") if video_id != "video-50"
        ]}

    monkeypatch.setattr(youtube_catalog, "_request_json", fake_request)
    ids = [f"video-{index}" for index in range(51)]
    stats = youtube_catalog.fetch_video_statistics(ids, api_key="test", timeout_sec=2)
    assert [len(call[1]) for call in calls] == [50, 1]
    assert "video-50" not in stats
    assert stats["video-0"] == (100, 4)


def test_rescore_runner_uses_batch_and_records_missing_video(monkeypatch):
    from scripts import rescore_refresh

    class FakeDB:
        def __init__(self):
            self.recorded = []

        def get_rescore_candidates(self, **kwargs):
            assert kwargs["limit"] == 50
            return [
                {"youtube_id": "grower", "slice_index": 0, "channel_id": "ordinary", "score": 1},
                {"youtube_id": "missing", "slice_index": 0, "channel_id": "ordinary", "score": 1},
            ]

        def record_rescore_attempt(self, yid, slice_index, views, likes):
            self.recorded.append((yid, slice_index, views, likes))
            return (1, 47) if views is not None else (1, 1)

    db = FakeDB()
    calls = []
    monkeypatch.setattr(rescore_refresh, "PipelineDB", lambda: db)
    monkeypatch.setattr(rescore_refresh, "settings", SimpleNamespace(
        youtube_data_api_key="test", youtube_data_api_timeout_sec=2,
        auto_publish_channel_min_scores={}, speech_channel_id_set=set(),
        speech_publish_score_line=40,
    ))

    def fake_statistics(ids, **kwargs):
        calls.append((ids, kwargs))
        return {"grower": (14_873, 302)}

    monkeypatch.setattr(rescore_refresh, "fetch_video_statistics", fake_statistics)

    rescore_refresh.main()
    assert len(calls) == 1
    assert calls[0][0] == ["grower", "missing"]
    assert db.recorded == [
        ("grower", 0, 14_873, 302), ("missing", 0, None, None),
    ]

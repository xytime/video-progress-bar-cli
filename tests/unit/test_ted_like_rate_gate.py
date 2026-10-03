"""TED/TEDx 点赞率闸门：真实数据库、严格边界及排队后的指标变化。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-03 | Codex | 验证双候选入口、切片继承、提交前复查和既有投稿保护。 |
"""
import pytest
from pydantic import ValidationError

from config.settings import Settings, settings
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing.scoring import TED_AUTO_PUBLISH_CHANNEL_IDS

TED, TEDX = TED_AUTO_PUBLISH_CHANNEL_IDS


@pytest.fixture(autouse=True)
def policy(monkeypatch):
    monkeypatch.setattr(settings, "ted_min_like_rate_pct", 0.6)
    monkeypatch.setattr(settings, "ted_auto_publish_after_id", 0)
    monkeypatch.setattr(settings, "speech_publish_score_line", 40)


@pytest.mark.parametrize("channel", [TED, TEDX])
@pytest.mark.parametrize("views,likes,eligible", [
    (1000, 6, False), (1000, 5, False), (1000, 7, True),
    (1_000_000, 6001, True), (167, 1, False),
    (0, 1, False), (None, 1, False), (1000, None, False),
    (1000, 0, False), (-1000, 7, False), (1000, -7, False),
])
def test_both_candidate_entries_apply_strict_rate_without_changing_score(tmp_path, channel, views, likes, eligible):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("one", "标题", channel, score=40, view_count=views, like_count=likes)
    kwargs = dict(min_score=75, limit=1, channel_min_scores={channel: 40})
    assert bool(db.get_high_score_pending_videos(**kwargs)) is eligible
    assert bool(db.get_high_score_preparation_candidates(**kwargs)) is eligible
    assert db.is_ted_like_rate_eligible("one") is eligible
    assert db.get_video_by_youtube_id("one")["score"] == 40


def test_filter_precedes_limit_and_also_applies_to_ready_and_manual_scores(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("blocked", "低互动", TED, score=99, view_count=1000, like_count=6)
    db.update_video_score("blocked", 99, force=True)
    db.add_video("pass", "达标", TEDX, score=40, view_count=1000, like_count=7)
    kwargs = dict(limit=1, channel_min_scores={TED: 40, TEDX: 40})
    for query in (db.get_high_score_pending_videos, db.get_high_score_preparation_candidates):
        assert [r["youtube_id"] for r in query(**kwargs)] == ["pass"]
    for yid in ("blocked", "pass"):
        db.mark_video_ready_for_publication(yid)
    assert [r["youtube_id"] for r in db.get_high_score_pending_videos(ready_only=True, **kwargs)] == ["pass"]


def test_other_channels_keep_existing_score_policy(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("normal", "普通频道", "other", score=75, view_count=0, like_count=None)
    db.add_video("speech", "其他演讲", "other-speech", score=40, view_count=0, like_count=0)
    db.add_video("low", "普通低分", "other", score=40, view_count=1000, like_count=100)
    for query in (db.get_high_score_pending_videos, db.get_high_score_preparation_candidates):
        assert {r["youtube_id"] for r in query(limit=10, channel_min_scores={"other-speech": 40})} == {"normal", "speech"}


@pytest.mark.parametrize("parent_likes,child_likes,eligible", [(7, None, True), (6, 1000, False)])
def test_slices_use_parent_metrics_even_when_child_metrics_are_missing_or_better(tmp_path, parent_likes, child_likes, eligible):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("parent", "原视频", TED, score=40, view_count=1000, like_count=parent_likes)
    parent = db.get_video_by_youtube_id("parent")
    db.update_video_status("parent", "SEGMENTED")
    db.add_video("parent", "切片", TED, score=40, slice_index=1, parent_id=parent["id"],
                 view_count=1000 if child_likes else None, like_count=child_likes)
    for query in (db.get_high_score_pending_videos, db.get_high_score_preparation_candidates):
        rows = query(channel_min_scores={TED: 40})
        assert bool(rows) is eligible
        if rows:
            assert rows[0]["slice_index"] == 1
    assert db.is_ted_like_rate_eligible("parent", slice_index=1) is eligible


def test_submission_rechecks_db_instead_of_queue_snapshot_and_keeps_artifacts(tmp_path, monkeypatch):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager.db.add_video("one", "TED", TED, score=40, view_count=1000, like_count=7)
    manager.db.mark_video_ready_for_publication("one")
    queued = manager.db.get_high_score_pending_videos(channel_min_scores={TED: 40})[0]
    assert manager.db.claim_video_for_publication("one", 123)
    manager.db.upsert_monitored_video("one", "TED", TED, zh_title=None, duration_sec=None,
        view_count=1200, like_count=7, upload_date=None, metadata_complete=True)
    artifact = tmp_path / "one_vertical.mp4"
    artifact.write_bytes(b"cached-render")
    monkeypatch.setattr(manager, "_run_tracked", lambda *a, **kw: pytest.fail("不达标不得启动上传器"))
    manager._publish_prepared_assets(queued, artifact, artifact, artifact, artifact)
    row = manager.db.get_video_by_youtube_id("one")
    assert row["status"] == "PENDING" and row["preparation_ready"] == 1
    assert row["process_pid"] is None and row["score"] == 40
    assert row["publication_ready_at"] == queued["publication_ready_at"]
    assert ">0.6%" in row["publication_wait_reason"]
    assert artifact.read_bytes() == b"cached-render"
    # 后续源指标更新达标，无需改分或销毁缓存即可重新成为候选。
    manager.db.upsert_monitored_video("one", "TED", TED, zh_title=None, duration_sec=None,
        view_count=1200, like_count=8, upload_date=None, metadata_complete=True)
    assert manager.db.get_high_score_pending_videos(ready_only=True, channel_min_scores={TED: 40})


def test_blocked_candidate_never_starts_download_or_caption(tmp_path, monkeypatch):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.db.add_video("one", "TED", TED, score=40, view_count=1000, like_count=6)
    monkeypatch.setattr(manager, "_run_tracked", lambda *a, **kw: pytest.fail("不达标不得启动加工"))
    manager._process_single_video(manager.db.get_video_by_youtube_id("one"), preparation_only=True)
    assert manager.db.get_video_by_youtube_id("one")["status"] == "PENDING"


def test_rate_deferral_cannot_reset_existing_submission(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("one", "TED", TED, score=40, view_count=1000, like_count=6)
    db.record_wechat_publication_confirmation("one", state="UNCERTAIN", evidence_path=None)
    before = db.get_video_by_youtube_id("one")
    db.defer_ted_like_rate_video("one", "低互动")
    assert db.get_video_by_youtube_id("one") == before


@pytest.mark.parametrize("threshold", [-1, 101, float("nan"), float("inf")])
def test_invalid_threshold_cannot_load(threshold):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ted_min_like_rate_pct=threshold)

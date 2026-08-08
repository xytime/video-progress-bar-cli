"""频道评分上限回归测试。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0 | 2026-08-08 | Codex | 锁定 The Economist 评分上限及统一写入口行为 |
"""
from video_processing.db import PipelineDB
from video_processing.scoring import THE_ECONOMIST_CHANNEL_ID, cap_channel_score


def test_the_economist_score_is_capped_at_sixty():
    assert cap_channel_score(THE_ECONOMIST_CHANNEL_ID, 95) == 60
    assert cap_channel_score(THE_ECONOMIST_CHANNEL_ID, 60) == 60


def test_other_channel_score_is_unchanged():
    assert cap_channel_score("another-channel", 95) == 95


def test_all_score_writes_obey_the_economist_cap(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_video("economist-score-cap", "The Economist", THE_ECONOMIST_CHANNEL_ID)

    db.update_video_score("economist-score-cap", 100, force=True)

    video = db.get_video_by_youtube_id("economist-score-cap")
    assert video["score"] == 60
    assert video["is_manually_scored"] == 1


def test_existing_economist_scores_are_reconciled_without_changing_status(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_video(
        "economist-historical-score", "The Economist", THE_ECONOMIST_CHANNEL_ID, score=95,
    )
    db.update_video_status("economist-historical-score", "PUBLISHED")

    assert db.enforce_channel_score_caps() == 1

    video = db.get_video_by_youtube_id("economist-historical-score")
    assert video["score"] == 60
    assert video["status"] == "PUBLISHED"

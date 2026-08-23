"""独立 Highlight Job 的持久化与候选分析测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-08-20 | Codex | 覆盖独立渲染资产、人工审核账本及其与源片状态隔离 |
| 1.2.0 | 2026-08-20 | Codex | 覆盖 YouTube 滚动 VTT 去重，阻断重复字幕进入候选文案 |
| 1.1.0 | 2026-08-20 | Codex | 覆盖 Highlight Clip 的独立发布主体和 post_id 账本边界 |
| 1.0.0 | 2026-08-20 | Codex | 覆盖 Highlight Job 不改写源片、活动去重和 VTT 候选计划 |
"""

from __future__ import annotations

from pathlib import Path

from video_processing.db.database import PipelineDB
from video_processing.highlight.miner import mine_candidates, parse_webvtt_cues
from video_processing.highlight.service import HighlightJobService


_YID = "highLight001"
_VTT = """WEBVTT

00:00:00.000 --> 00:00:18.000
Most people think more information automatically creates better decisions, but that is wrong.

00:00:18.000 --> 00:00:38.000
The real question is whether you can discard the signal that makes you comfortable?

00:00:38.000 --> 00:00:56.000
When every model agrees with you, that may be the moment you should look for the missing fact.
"""

_ROLLING_VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
Markets are never

00:00:01.000 --> 00:00:02.000
Markets are never just numbers.

00:00:02.000 --> 00:00:03.000
never just numbers. They are stories.
"""


def _db_with_source(tmp_path: Path) -> PipelineDB:
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_video(_YID, "A long interview", "channel-highlight", score=88)
    return db


def test_highlight_job_is_deduplicated_while_active_and_never_changes_source(tmp_path: Path):
    db = _db_with_source(tmp_path)

    job, created = db.create_highlight_job(_YID, requested_by="test")
    same_job, created_again = db.create_highlight_job(_YID, requested_by="test")

    assert created is True
    assert created_again is False
    assert same_job["id"] == job["id"]
    assert db.get_video_by_youtube_id(_YID)["status"] == "PENDING"


def test_vtt_candidate_plan_persists_without_touching_source_state(tmp_path: Path):
    db = _db_with_source(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / f"{_YID}_source_subtitle.en.vtt").write_text(_VTT, encoding="utf-8")
    job, created = db.create_highlight_job(_YID, requested_by="test")
    assert created is True

    result = HighlightJobService(db, tmp_path).analyze(job["id"])

    assert result is not None
    assert result["state"] == "CANDIDATES_READY"
    assert Path(result["plan_path"]).is_file()
    clips = db.get_highlight_clips(job["id"])
    assert len(clips) == 1
    assert clips[0]["raw_start_ms"] == 0
    assert clips[0]["raw_end_ms"] == 38_000
    assert db.get_video_by_youtube_id(_YID)["status"] == "PENDING"


def test_source_without_timed_vtt_is_not_eligible_for_candidate_analysis(tmp_path: Path):
    db = _db_with_source(tmp_path)
    service = HighlightJobService(db, tmp_path)

    assert service.has_source_subtitle(_YID) is False


def test_selected_highlight_clip_has_own_publication_subject_and_post_id_ledger(tmp_path: Path):
    db = _db_with_source(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / f"{_YID}_source_subtitle.en.vtt").write_text(_VTT, encoding="utf-8")
    job, created = db.create_highlight_job(_YID, requested_by="test")
    assert created is True
    assert HighlightJobService(db, tmp_path).analyze(job["id"])["state"] == "CANDIDATES_READY"
    clip = db.get_highlight_clips(job["id"])[0]

    selected = db.select_highlight_clip_for_publication(clip["id"])
    subject = db.get_publication_subject(selected["publication_subject_id"])

    assert selected["state"] == "SELECTED"
    assert selected["selected"] == 1
    assert subject["kind"] == "HIGHLIGHT_CLIP"
    assert subject["source_youtube_id"] == _YID
    assert db.get_video_by_youtube_id(_YID)["status"] == "PENDING"

    publication = db.record_wechat_publication_confirmation_for_subject(
        subject["id"], evidence_path=None, state="SUBMITTED_BOUND", platform_post_id="post-highlight-001",
    )
    attempt = db.record_wechat_submission_attempt_for_subject(
        subject["id"], final_title="独立 Highlight 标题", video_sha256="a" * 64,
    )
    bound_attempt = db.bind_wechat_submission_attempt_platform_id(
        attempt["attempt_id"], platform_post_id="post-highlight-001",
    )

    assert publication["video_id"] is None
    assert publication["subject_id"] == subject["id"]
    assert publication["platform_post_id"] == "post-highlight-001"
    assert bound_attempt["subject_id"] == subject["id"]
    assert bound_attempt["state"] == "PLATFORM_ID_BOUND"
    assert db.get_video_by_youtube_id(_YID)["status"] == "PENDING"


def test_highlight_assets_and_review_stay_on_clip_not_source(tmp_path: Path):
    db = _db_with_source(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / f"{_YID}_source_subtitle.en.vtt").write_text(_VTT, encoding="utf-8")
    job, _ = db.create_highlight_job(_YID, requested_by="test")
    assert HighlightJobService(db, tmp_path).analyze(job["id"])["state"] == "CANDIDATES_READY"
    selected = db.select_highlight_clip_for_publication(db.get_highlight_clips(job["id"])[0]["id"])

    claimed = db.claim_highlight_clip_for_rendering(selected["id"])
    assert claimed and claimed["state"] == "RENDERING"
    rendered = db.complete_highlight_clip_rendering(
        selected["id"],
        source_video_path="/assets/source.mp4",
        source_video_sha256="a" * 64,
        source_video_kind="source_download",
        rendered_video_path="/assets/highlight.mp4",
        title_path="/assets/title.txt",
        copy_path="/assets/copy.txt",
        category_path="/assets/category.txt",
        cover_path="/assets/cover.jpg",
        cover_provenance_path="/assets/cover_provenance.json",
        artifact_manifest_path="/assets/asset_manifest.json",
        evidence_dir="/assets/evidence",
    )
    review = db.approve_highlight_clip_publication(
        selected["id"], asset_manifest_sha256="b" * 64, approved_by="tester",
    )
    stored = db.get_highlight_clip_assets(selected["id"])

    assert rendered["state"] == "ASSETS_READY"
    assert stored and stored["rendered_video_path"] == "/assets/highlight.mp4"
    assert stored["review_approved_by"] == "tester"
    assert review["asset_manifest_sha256"] == "b" * 64
    assert db.get_highlight_job(job["id"])["state"] == "ASSETS_READY"
    assert db.get_video_by_youtube_id(_YID)["status"] == "PENDING"

def test_candidate_miner_keeps_timed_boundaries_and_returns_no_snapped_claims():
    cues = parse_webvtt_cues(_VTT)
    clips = mine_candidates(cues, max_clips=3, min_duration_sec=35, max_duration_sec=90)

    assert len(cues) == 3
    assert len(clips) == 1
    assert clips[0]["raw_start_ms"] == 0
    assert clips[0]["raw_end_ms"] == 38_000
    assert clips[0]["snapped_start_ms"] is None
    assert clips[0]["snapped_end_ms"] is None


def test_rolling_webvtt_keeps_only_new_words_in_each_timed_cue():
    cues = parse_webvtt_cues(_ROLLING_VTT)

    assert [cue.text for cue in cues] == ["Markets are never", "just numbers.", "They are stories."]
    assert [cue.start_ms for cue in cues] == [0, 1_000, 2_000]

"""英语世界短视频独立选题研究账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-21 | Codex | 覆盖候选研究、二次制作确认和通用队列隔离。 |
| 1.0.1 | 2026-08-21 | Codex | 固化 yt-dlp 搜索提取器兼容性，防止伪 URL 落入 HTTP 路径。 |
| 1.1.0 | 2026-08-23 | Codex | 覆盖英语世界成片的唯一审核身份、原子批准领取与未确认投稿收尾。 |
"""

from __future__ import annotations

import sys
import types

import pytest

from video_processing.db.database import PipelineDB
from video_processing.english_world.research import EnglishWorldResearchService, _youtube_search


def _candidate(*, title: str = "Whales return to the bay") -> dict:
    return {
        "id": "dQw4w9WgXcQ",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": title,
        "channel": "Nature Desk",
        "upload_date": "20260821",
        "duration_sec": 42,
    }


def _stored_candidate() -> dict:
    return {
        "id": "a" * 32,
        "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "youtube_id": "dQw4w9WgXcQ",
        "source_title": "Whales return to the bay",
        "source_channel": "Nature Desk",
        "upload_date": "20260821",
        "duration_sec": 42,
        "topic": "nature",
        "learning_value": "适合学习自然观察、动物与环境主题词汇。",
        "safety_note": "仅元数据预筛，制作前仍需复核。",
        "caption_status": "待制作前核验",
        "recommendation_score": 58,
    }


def test_research_job_keeps_candidates_out_of_generic_video_queue(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")

    service = EnglishWorldResearchService(db, searcher=lambda _query: [_candidate()])
    result = service.research(job["id"])

    assert result and result["state"] == "CANDIDATES_READY"
    candidates = db.get_english_world_candidates(job["id"])
    assert candidates[0]["source_title"] == "Whales return to the bay"
    assert db.get_video_by_youtube_id("dQw4w9WgXcQ") is None


def test_selected_candidate_requires_second_confirmation_before_production_request(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")
    assert db.claim_english_world_job_for_research(job["id"])
    db.complete_english_world_research(job["id"], candidates=[_stored_candidate()])

    candidate_id = db.get_english_world_candidates(job["id"])[0]["id"]
    selected = db.select_english_world_candidate(candidate_id)
    before = db.get_english_world_job(job["id"])
    requested = db.request_english_world_production(job["id"])

    assert selected["selected"] == 1
    assert before["state"] == "CANDIDATE_SELECTED"
    assert requested["state"] == "PRODUCTION_REQUESTED"
    assert db.get_video_by_youtube_id("dQw4w9WgXcQ") is None


def test_metadata_screening_rejects_explicitly_unsuitable_topics(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")
    unsafe = _candidate(title="Election war update")

    service = EnglishWorldResearchService(db, searcher=lambda _query: [unsafe])
    result = service.research(job["id"])

    assert result and result["state"] == "FAILED"
    assert "没有找到" in result["error_message"]


def test_youtube_search_uses_supported_ytsearch_extractor(monkeypatch):
    requested_urls: list[str] = []

    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, *, download):
            requested_urls.append(url)
            assert download is False
            return {"entries": []}

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    assert list(_youtube_search("BBC Earth wildlife news")) == []
    assert requested_urls == ["ytsearch8:BBC Earth wildlife news"]


def test_review_item_is_bound_to_one_artifact_and_cannot_be_auto_retried(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {name: package_dir / name for name in (
        "video.mp4", "manifest.json", "title.txt", "copy.txt", "cover.jpg", "cover_provenance.json",
    )}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")
    kwargs = {
        "artifact_sha256": "a" * 64,
        "title": "为家庭送上餐桌",
        "mp4_path": str(paths["video.mp4"]),
        "manifest_path": str(paths["manifest.json"]),
        "title_path": str(paths["title.txt"]),
        "copy_path": str(paths["copy.txt"]),
        "cover_path": str(paths["cover.jpg"]),
        "cover_provenance_path": str(paths["cover_provenance.json"]),
        "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }

    ready = db.create_english_world_review_item(**kwargs)
    assert db.create_english_world_review_item(**kwargs)["id"] == ready["id"]
    approved = db.approve_english_world_submission(ready["id"])
    assert approved["state"] == "SUBMISSION_APPROVED"
    claimed = db.claim_english_world_submission(ready["id"])
    assert claimed and claimed["state"] == "SUBMITTING"
    assert db.claim_english_world_submission(ready["id"]) is None

    completed = db.complete_english_world_submission(
        ready["id"], state="UNCERTAIN", uploader_exit_code=3, message="结果无法确认",
    )
    assert completed["state"] == "UNCERTAIN"
    with pytest.raises(ValueError, match="cannot be approved"):
        db.approve_english_world_submission(ready["id"])

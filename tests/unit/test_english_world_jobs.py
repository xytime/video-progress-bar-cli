"""英语世界短视频独立选题研究账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-21 | Codex | 覆盖候选研究、二次制作确认和通用队列隔离。 |
| 1.0.1 | 2026-08-21 | Codex | 固化 yt-dlp 搜索提取器兼容性，防止伪 URL 落入 HTTP 路径。 |
| 1.1.0 | 2026-08-23 | Codex | 覆盖英语世界成片的唯一审核身份、原子批准领取与未确认投稿收尾。 |
| 1.1.1 | 2026-08-24 | Codex | 覆盖候选搜索继承 Cookie 配置及单批次失败隔离。 |
| 1.1.2 | 2026-08-24 | Codex | 覆盖目录降级路径与新闻标题风险词预筛。 |
| 1.1.3 | 2026-08-24 | Codex | 覆盖预筛后目录降级、长来源截取边界与天气画面复核语义。 |
| 1.1.4 | 2026-08-28 | Codex | 覆盖登录前失败项只允许一次登录后自动续投，未确认状态不受影响。 |
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from video_processing.db.database import PipelineDB
from video_processing.english_world import research
from video_processing.english_world.research import EnglishWorldResearchService, _youtube_search


def _candidate(*, title: str = "Whales return to the bay", duration_sec: int = 42) -> dict:
    return {
        "id": "dQw4w9WgXcQ",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": title,
        "channel": "Nature Desk",
        "upload_date": "20260821",
        "duration": duration_sec,
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


def test_metadata_screening_rejects_explicitly_unsuitable_topics(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")
    unsafe = _candidate(title="Iran tariff victim remains update")
    monkeypatch.setattr(
        research,
        "fetch_channel_catalog",
        lambda *_args, **_kwargs: SimpleNamespace(videos=[]),
    )

    service = EnglishWorldResearchService(db, searcher=lambda _query: [unsafe])
    result = service.research(job["id"])

    assert result and result["state"] == "FAILED"
    assert "没有找到" in result["error_message"]


def test_weather_science_candidate_requires_visual_review_but_is_not_keyword_rejected(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")

    result = EnglishWorldResearchService(
        db, searcher=lambda _query: [_candidate(title="How tornadoes form in a weather lab")],
    ).research(job["id"])

    assert result and result["state"] == "CANDIDATES_READY"
    candidate = db.get_english_world_candidates(job["id"])[0]
    assert candidate["topic"] == "science"
    assert "核对无真实伤亡" in candidate["safety_note"]


def test_youtube_search_uses_supported_ytsearch_extractor(monkeypatch):
    requested_urls: list[str] = []
    requested_options: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, options):
            requested_options.append(options)

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
    assert requested_options[0]["ignoreerrors"] is True
    assert "cookiefile" in requested_options[0] or "cookiesfrombrowser" in requested_options[0]


def test_research_continues_after_one_search_batch_is_blocked(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")
    calls: list[str] = []

    def searcher(query: str):
        calls.append(query)
        if len(calls) == 1:
            raise RuntimeError("YouTube risk control")
        return [_candidate()]

    result = EnglishWorldResearchService(db, searcher=searcher).research(job["id"])

    assert result and result["state"] == "CANDIDATES_READY"
    assert len(calls) == 5


def test_research_falls_back_to_approved_channel_catalog_when_ytsearch_is_blocked(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")
    requested_channels: list[str] = []

    def fake_catalog(channel_id: str, **_kwargs):
        requested_channels.append(channel_id)
        return SimpleNamespace(videos=[SimpleNamespace(
            youtube_id="catalog-video-1",
            title="Whales return to the bay",
            upload_date="20260824",
            duration_sec=120,
        )])

    monkeypatch.setattr(research, "fetch_channel_catalog", fake_catalog)

    result = EnglishWorldResearchService(db, searcher=lambda _query: [None]).research(job["id"])

    assert result and result["state"] == "CANDIDATES_READY"
    assert requested_channels == [channel_id for channel_id, _name in research._APPROVED_SOURCE_CHANNELS]
    candidates = db.get_english_world_candidates(job["id"])
    assert candidates[0]["youtube_id"] == "catalog-video-1"
    assert candidates[0]["source_channel"] == "CBC Kids News"


def test_research_falls_back_after_search_results_fail_pre_screening(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")
    requested_channels: list[str] = []

    def fake_catalog(channel_id: str, **_kwargs):
        requested_channels.append(channel_id)
        return SimpleNamespace(videos=[SimpleNamespace(
            youtube_id=f"catalog-{channel_id[-4:]}",
            title="Whales return to the bay",
            upload_date="20260824",
            duration_sec=480,
        )])

    monkeypatch.setattr(research, "fetch_channel_catalog", fake_catalog)
    result = EnglishWorldResearchService(
        db, searcher=lambda _query: [_candidate(title="Long science update", duration_sec=601)],
    ).research(job["id"])

    assert result and result["state"] == "CANDIDATES_READY"
    assert requested_channels == [channel_id for channel_id, _name in research._APPROVED_SOURCE_CHANNELS]
    assert all(candidate["duration_sec"] == 480 for candidate in db.get_english_world_candidates(job["id"]))


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
    assert ready["_created_now"] is True
    duplicate = db.create_english_world_review_item(**kwargs)
    assert duplicate["id"] == ready["id"]
    assert duplicate["_created_now"] is False
    approved = db.approve_english_world_submission(ready["id"])
    assert approved["state"] == "SUBMISSION_APPROVED"
    assert approved["approval_source"] == "TELEGRAM_REVIEW"
    claimed = db.claim_english_world_submission(ready["id"])
    assert claimed and claimed["state"] == "SUBMITTING"
    assert db.claim_english_world_submission(ready["id"]) is None

    completed = db.complete_english_world_submission(
        ready["id"], state="UNCERTAIN", uploader_exit_code=3, message="结果无法确认",
    )
    assert completed["state"] == "UNCERTAIN"
    with pytest.raises(ValueError, match="cannot be approved"):
        db.approve_english_world_submission(ready["id"])
    reopened = db.reopen_uncertain_english_world_submission(ready["id"])
    assert reopened["state"] == "SUBMISSION_APPROVED"
    assert db.claim_english_world_submission(ready["id"])


def test_login_recovery_claims_only_one_recent_auto_policy_prelogin_failure(tmp_path):
    """扫码成功只恢复明确的登录前失败项，且同一项最多一次。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {name: package_dir / name for name in (
        "video.mp4", "manifest.json", "title.txt", "copy.txt", "cover.jpg", "cover_provenance.json",
    )}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")
    item = db.create_english_world_review_item(
        artifact_sha256="b" * 64,
        title="注意力也有能量预算",
        mp4_path=str(paths["video.mp4"]),
        manifest_path=str(paths["manifest.json"]),
        title_path=str(paths["title.txt"]),
        copy_path=str(paths["copy.txt"]),
        cover_path=str(paths["cover.jpg"]),
        cover_provenance_path=str(paths["cover_provenance.json"]),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    assert db.claim_english_world_submission(item["id"])
    failed = db.complete_english_world_submission(
        item["id"], state="LOGIN_REQUIRED", uploader_exit_code=2, message="登录前失败",
    )
    assert failed["state"] == "LOGIN_REQUIRED"

    recovered = db.claim_english_world_login_recovery(max_age_hours=12)

    assert recovered and recovered["id"] == item["id"]
    assert recovered["state"] == "SUBMISSION_APPROVED"
    assert recovered["login_recovery_attempts"] == 1
    assert db.claim_english_world_login_recovery(max_age_hours=12) is None

"""英语世界短视频独立选题研究账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.10.2 | 2026-09-04 | Codex | 覆盖首轮明确发布前拒绝被旧退出码误记为 UNCERTAIN 时的一次受控恢复。 |
| 1.7.0 | 2026-08-31 | Codex | 覆盖作品管理页确认已发布时对 CANCELED 抖音账本的受控修正及原尝试不可变。 |
| 1.0.0 | 2026-08-21 | Codex | 覆盖候选研究、二次制作确认和通用队列隔离。 |
| 1.0.1 | 2026-08-21 | Codex | 固化 yt-dlp 搜索提取器兼容性，防止伪 URL 落入 HTTP 路径。 |
| 1.1.0 | 2026-08-23 | Codex | 覆盖英语世界成片的唯一审核身份、原子批准领取与未确认投稿收尾。 |
| 1.1.1 | 2026-08-24 | Codex | 覆盖候选搜索继承 Cookie 配置及单批次失败隔离。 |
| 1.1.2 | 2026-08-24 | Codex | 覆盖目录降级路径与新闻标题风险词预筛。 |
| 1.1.3 | 2026-08-24 | Codex | 覆盖预筛后目录降级、长来源截取边界与天气画面复核语义。 |
| 1.1.4 | 2026-08-28 | Codex | 覆盖登录前失败项只允许一次登录后自动续投，未确认状态不受影响。 |
| 1.2.0 | 2026-08-29 | Codex | 覆盖 Telegram 投稿授权两小时失效及 AUTO_POLICY 延后项窗口内再领取。 |
| 1.3.0 | 2026-08-29 | Codex | 覆盖整包指纹、同源去重及多次投稿尝试的不可覆盖审计记录。 |
| 1.4.0 | 2026-08-30 | Codex | 覆盖具名补发仅授权零尝试项，过期未领取授权自动回归公共窗口队列。 |
| 1.5.0 | 2026-08-30 | Codex | 覆盖英语世界原生作品 ID 入账、节流领取与平台终态停止回查。 |
| 1.6.0 | 2026-08-30 | Codex | 覆盖英语世界独立抖音账本、不可重传尝试和可选的通用 NEW 额度兼容。 |
| 1.5.1 | 2026-08-30 | Codex | 固化英语世界原生作品 ID 只能首次绑定或相同 ID 幂等绑定。 |
| 1.8.0 | 2026-09-01 | Codex | 覆盖英语世界抖音同步可在无日额度模式下领取，仍保持单次不可重传账本。 |
| 1.9.0 | 2026-09-02 | Codex | 覆盖日更选题前读取同源投稿保护账本，避免制作后才因重复审核被拒绝。 |
| 1.10.0 | 2026-09-03 | Codex | 覆盖管理页确认删除及原创界面回读失败的受控重投资格。 |
| 1.10.1 | 2026-09-03 | Codex | 验证原创声明恢复额度持久化为一次，二次失败不得再次领取投稿授权。 |
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from video_processing.db.database import PipelineDB
from video_processing.english_world import research
from video_processing.english_world.research import EnglishWorldResearchService, _youtube_search
from video_processing.english_world.package_integrity import calculate_package_hashes, verify_package_hashes


def _stored_hashes(seed: str = "a") -> dict[str, str]:
    return {
        "manifest_sha256": seed * 64,
        "title_sha256": seed * 64,
        "copy_sha256": seed * 64,
        "cover_sha256": seed * 64,
        "cover_provenance_sha256": seed * 64,
    }


def _candidate(*, title: str = "Whales return to the bay", duration_sec: int = 42) -> dict:
    return {
        "id": "dQw4w9WgXcQ",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": title,
        "channel": "CBC Kids News",
        "channel_id": "UCWUA2W6LueNy9BSovivFVvQ",
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
        "source_channel_id": "UCWUA2W6LueNy9BSovivFVvQ",
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
    assert requested["production_state"] == "REQUESTED"
    assert db.get_video_by_youtube_id("dQw4w9WgXcQ") is None


def test_production_request_claims_selected_candidate_and_finishes_at_manual_review(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")
    assert db.claim_english_world_job_for_research(job["id"])
    db.complete_english_world_research(job["id"], candidates=[_stored_candidate()])
    candidate_id = db.get_english_world_candidates(job["id"])[0]["id"]
    db.select_english_world_candidate(candidate_id)
    requested = db.request_english_world_production(job["id"])

    claimed = db.claim_english_world_job_for_production(job["id"])
    assert claimed and claimed["production_state"] == "PRODUCING"
    assert claimed["candidate_youtube_id"] == "dQw4w9WgXcQ"
    assert db.claim_english_world_job_for_production(job["id"]) is None

    package_paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        package_paths[f"{field}_path"] = str(path)
    review = db.create_english_world_review_item(
        title="Telegram 人工审核", source_youtube_id="dQw4w9WgXcQ",
        **package_paths, **calculate_package_hashes(package_paths),
    )
    finished = db.complete_english_world_job_production(
        job["id"], review_id=review["id"],
        mp4_path=package_paths["mp4_path"], manifest_path=package_paths["manifest_path"],
    )

    assert requested["production_state"] == "REQUESTED"
    assert finished["production_state"] == "READY_FOR_REVIEW"
    assert finished["review_id"] == review["id"]
    assert review["state"] == "READY_FOR_REVIEW"


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


def test_research_rejects_unapproved_channel_even_if_display_name_is_spoofed(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(
        requested_by="telegram", source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    spoofed = _candidate()
    spoofed["channel_id"] = "UC_NOT_APPROVED"
    spoofed["channel"] = "CBC Kids News"

    result = EnglishWorldResearchService(db, inspector=lambda _url: spoofed).research(job["id"])

    assert result and result["state"] == "FAILED"
    assert "没有找到" in result["error_message"]


def test_legacy_candidate_without_channel_id_cannot_be_selected(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    job = db.create_english_world_research_job(requested_by="telegram")
    assert db.claim_english_world_job_for_research(job["id"])
    legacy = _stored_candidate()
    legacy.pop("source_channel_id")
    db.complete_english_world_research(job["id"], candidates=[legacy])
    candidate_id = db.get_english_world_candidates(job["id"])[0]["id"]

    with pytest.raises(ValueError, match="approved channel ID"):
        db.select_english_world_candidate(candidate_id)


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
        **_stored_hashes("a"),
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
    assert approved["authorization_expires_at"] is not None
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


def test_manual_english_world_authorization_expires_but_auto_policy_remains_claimable(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {name: package_dir / name for name in (
        "video.mp4", "manifest.json", "title.txt", "copy.txt", "cover.jpg", "cover_provenance.json",
    )}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")

    def create(digest: str):
        return db.create_english_world_review_item(
            artifact_sha256=digest * 64,
            **_stored_hashes(digest),
            title="两小时授权",
            mp4_path=str(paths["video.mp4"]),
            manifest_path=str(paths["manifest.json"]),
            title_path=str(paths["title.txt"]),
            copy_path=str(paths["copy.txt"]),
            cover_path=str(paths["cover.jpg"]),
            cover_provenance_path=str(paths["cover_provenance.json"]),
        )

    manual = create("c")
    approved = db.approve_english_world_submission(manual["id"])
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE english_world_review_items SET authorization_expires_at = datetime('now', '-1 minute') WHERE id = ?",
            (manual["id"],),
        )
    assert db.claim_english_world_submission(manual["id"]) is None
    expired = db.expire_english_world_submission_authorization(manual["id"])
    assert expired and expired["state"] == "READY_FOR_REVIEW"

    automatic = create("d")
    auto_approved = db.approve_english_world_submission(automatic["id"], authorization="AUTO_POLICY")
    assert auto_approved["authorization_expires_at"] is None
    assert db.get_next_auto_approved_english_world_submission()["id"] == automatic["id"]
    assert db.claim_english_world_submission(automatic["id"])["state"] == "SUBMITTING"


def test_operator_recovery_authorizes_only_unattempted_auto_policy_item(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {name: package_dir / name for name in (
        "video.mp4", "manifest.json", "title.txt", "copy.txt", "cover.jpg", "cover_provenance.json",
    )}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")
    item = db.create_english_world_review_item(
        artifact_sha256="e" * 64,
        **_stored_hashes("e"),
        title="操作员具名补发",
        mp4_path=str(paths["video.mp4"]),
        manifest_path=str(paths["manifest.json"]),
        title_path=str(paths["title.txt"]),
        copy_path=str(paths["copy.txt"]),
        cover_path=str(paths["cover.jpg"]),
        cover_provenance_path=str(paths["cover_provenance.json"]),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")

    authorized = db.authorize_english_world_operator_recovery(
        item["id"], reason="用户明确要求补发本条漏发内容",
    )

    assert authorized["approval_source"] == "OPERATOR_RECOVERY"
    assert authorized["authorization_expires_at"] is not None
    assert "用户明确要求" in authorized["error_message"]
    assert db.claim_english_world_submission(item["id"])["state"] == "SUBMITTING"
    with pytest.raises(ValueError, match="unattempted AUTO_POLICY"):
        db.authorize_english_world_operator_recovery(item["id"], reason="重复授权必须拒绝")

    deferred = db.create_english_world_review_item(
        artifact_sha256="f" * 64,
        **_stored_hashes("f"),
        title="过期授权回归队列",
        mp4_path=str(paths["video.mp4"]),
        manifest_path=str(paths["manifest.json"]),
        title_path=str(paths["title.txt"]),
        copy_path=str(paths["copy.txt"]),
        cover_path=str(paths["cover.jpg"]),
        cover_provenance_path=str(paths["cover_provenance.json"]),
    )
    db.approve_english_world_submission(deferred["id"], authorization="AUTO_POLICY")
    db.authorize_english_world_operator_recovery(deferred["id"], reason="测试未领取授权过期")
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE english_world_review_items SET authorization_expires_at = datetime('now', '-1 minute') WHERE id = ?",
            (deferred["id"],),
        )

    assert db.restore_expired_english_world_operator_recoveries() == 1
    restored = db.get_english_world_review_item(deferred["id"])
    assert restored["approval_source"] == "AUTO_POLICY"
    assert restored["authorization_expires_at"] is None
    assert db.get_next_auto_approved_english_world_submission()["id"] == deferred["id"]


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
        **_stored_hashes("b"),
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


def test_review_item_rejects_same_source_with_different_artifact(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {name: package_dir / name for name in (
        "video.mp4", "manifest.json", "title.txt", "copy.txt", "cover.jpg", "cover_provenance.json",
    )}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")

    common = {
        "title": "同一来源",
        "mp4_path": str(paths["video.mp4"]),
        "manifest_path": str(paths["manifest.json"]),
        "title_path": str(paths["title.txt"]),
        "copy_path": str(paths["copy.txt"]),
        "cover_path": str(paths["cover.jpg"]),
        "cover_provenance_path": str(paths["cover_provenance.json"]),
        "source_youtube_id": "source-123",
    }
    db.create_english_world_review_item(
        artifact_sha256="1" * 64, **_stored_hashes("1"), **common,
    )

    with pytest.raises(ValueError, match="source already has"):
        db.create_english_world_review_item(
            artifact_sha256="2" * 64, **_stored_hashes("2"), **common,
        )


def test_list_submission_protected_source_ids_returns_review_protected_source(tmp_path):
    """日更选题必须在渲染前看到与创建审核项相同的同源保护范围。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {name: package_dir / name for name in (
        "video.mp4", "manifest.json", "title.txt", "copy.txt", "cover.jpg", "cover_provenance.json",
    )}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")

    db.create_english_world_review_item(
        artifact_sha256="3" * 64,
        **_stored_hashes("3"),
        title="受保护的同源审核项",
        mp4_path=str(paths["video.mp4"]),
        manifest_path=str(paths["manifest.json"]),
        title_path=str(paths["title.txt"]),
        copy_path=str(paths["copy.txt"]),
        cover_path=str(paths["cover.jpg"]),
        cover_provenance_path=str(paths["cover_provenance.json"]),
        source_youtube_id="dQw4w9WgXcQ",
    )

    assert db.list_english_world_submission_protected_source_ids() == ["dQw4w9WgXcQ"]


def test_package_integrity_rejects_any_file_mutation(tmp_path):
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = {**paths, **calculate_package_hashes(paths)}

    verify_package_hashes(item)
    (tmp_path / "copy.bin").write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="copy_sha256"):
        verify_package_hashes(item)


def test_submission_attempts_keep_each_retry_evidence_directory(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    hashes = calculate_package_hashes(paths)
    item = db.create_english_world_review_item(
        title="不可覆盖尝试", **paths, **hashes,
    )
    db.approve_english_world_submission(item["id"])
    first = db.claim_english_world_submission(item["id"], evidence_dir="/evidence/attempt-1")
    assert first
    db.complete_english_world_submission(
        item["id"], state="UNCERTAIN", uploader_exit_code=3,
        evidence_dir="/evidence/attempt-1", attempt_id=first["_attempt_id"],
    )
    db.reopen_uncertain_english_world_submission(item["id"])
    second = db.claim_english_world_submission(item["id"], evidence_dir="/evidence/attempt-2")
    assert second
    db.complete_english_world_submission(
        item["id"], state="UNDER_REVIEW", uploader_exit_code=0,
        evidence_dir="/evidence/attempt-2", attempt_id=second["_attempt_id"],
    )

    attempts = db.list_english_world_submission_attempts(item["id"])
    assert len(attempts) == 2
    assert {attempt["evidence_dir"] for attempt in attempts} == {
        "/evidence/attempt-1", "/evidence/attempt-2",
    }


def test_english_world_platform_identity_enables_throttled_exact_reconciliation(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(
        title="原生 ID 精确回查", **paths, **calculate_package_hashes(paths),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    claimed = db.claim_english_world_submission(item["id"], evidence_dir="/evidence/submission")
    assert claimed
    completed = db.complete_english_world_submission(
        item["id"],
        state="UNDER_REVIEW",
        uploader_exit_code=6,
        evidence_dir="/evidence/submission",
        attempt_id=claimed["_attempt_id"],
        platform_post_id="export/native-item-id",
    )

    assert completed["platform_post_id"] == "export/native-item-id"
    attempts = db.list_english_world_submission_attempts(item["id"])
    assert attempts[0]["platform_post_id"] == "export/native-item-id"

    reconciliation = db.claim_next_english_world_reconciliation(
        min_interval_minutes=30, max_age_hours=72,
    )
    assert reconciliation and reconciliation["id"] == item["id"]
    assert db.claim_next_english_world_reconciliation(
        min_interval_minutes=30, max_age_hours=72,
    ) is None

    published = db.record_english_world_reconciliation(
        item["id"],
        platform_state="PUBLISHED",
        evidence_dir="/evidence/reconciliation",
        message="作品管理页按原生 ID 明确显示已发布。",
    )
    assert published["state"] == "UNDER_REVIEW"
    assert published["platform_state"] == "PUBLISHED"
    assert published["reconciliation_evidence_dir"] == "/evidence/reconciliation"
    assert db.claim_next_english_world_reconciliation(
        min_interval_minutes=5, max_age_hours=72,
    ) is None


def test_confirmed_deleted_english_world_item_can_reopen_once_with_new_identity(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(
        title="删除后重投", **paths, **calculate_package_hashes(paths),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    first = db.claim_english_world_submission(item["id"], evidence_dir="/evidence/original")
    assert first
    db.complete_english_world_submission(
        item["id"], state="UNDER_REVIEW", uploader_exit_code=0,
        evidence_dir="/evidence/original", attempt_id=first["_attempt_id"],
        platform_post_id="export/deleted-original",
    )
    db.record_english_world_reconciliation(
        item["id"], platform_state="NOT_FOUND", evidence_dir="/evidence/deleted",
        message="作品管理页按精确标题搜索显示暂无相关视频。",
    )

    reopened = db.reopen_deleted_english_world_submission(
        item["id"], deletion_evidence_dir="/evidence/deleted",
    )

    assert reopened["state"] == "SUBMISSION_APPROVED"
    assert reopened["approval_source"] == "OPERATOR_RECOVERY"
    assert reopened["platform_post_id"] is None
    assert reopened["platform_state"] is None
    assert reopened["reconciliation_evidence_dir"] == "/evidence/deleted"
    assert db.list_english_world_submission_attempts(item["id"])[0]["platform_post_id"] == "export/deleted-original"
    assert db.claim_english_world_submission(item["id"], evidence_dir="/evidence/reupload")


def test_unpublished_original_declaration_readback_failure_can_reopen_once(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(
        title="原创回读失败", **paths, **calculate_package_hashes(paths),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    failed = db.claim_english_world_submission(item["id"], evidence_dir="/evidence/original-readback")
    assert failed
    db.complete_english_world_submission(
        item["id"], state="FAILED", uploader_exit_code=1,
        evidence_dir="/evidence/original-readback", attempt_id=failed["_attempt_id"],
        message="Original declaration click completed but UI state was not confirmed; 未进入发表。",
    )

    reopened = db.reopen_failed_english_world_original_declaration(
        item["id"], failure_evidence_dir="/evidence/original-readback",
    )

    assert reopened["state"] == "SUBMISSION_APPROVED"
    assert reopened["approval_source"] == "OPERATOR_RECOVERY"
    assert reopened["original_declaration_recovery_attempts"] == 1
    retried = db.claim_english_world_submission(item["id"], evidence_dir="/evidence/retry")
    assert retried
    db.complete_english_world_submission(
        item["id"], state="FAILED", uploader_exit_code=1,
        evidence_dir="/evidence/retry", attempt_id=retried["_attempt_id"],
        message="Original declaration click completed but UI state was not confirmed; 未进入发表。",
    )

    with pytest.raises(ValueError, match="original-declaration readback failure"):
        db.reopen_failed_english_world_original_declaration(
            item["id"], failure_evidence_dir="/evidence/retry",
        )


def test_english_world_platform_identity_cannot_be_rebound(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(
        title="不可覆盖原生 ID", **paths, **calculate_package_hashes(paths),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    claimed = db.claim_english_world_submission(item["id"], evidence_dir="/evidence/submission")
    db.complete_english_world_submission(
        item["id"], state="UNDER_REVIEW", uploader_exit_code=6,
        evidence_dir="/evidence/submission", attempt_id=claimed["_attempt_id"],
    )

    first = db.bind_english_world_submission_platform_identity(
        item["id"], attempt_id=claimed["_attempt_id"], platform_post_id="export/native-a",
    )
    same = db.bind_english_world_submission_platform_identity(
        item["id"], attempt_id=claimed["_attempt_id"], platform_post_id="export/native-a",
    )
    with pytest.raises(ValueError, match="already bound to another"):
        db.bind_english_world_submission_platform_identity(
            item["id"], attempt_id=claimed["_attempt_id"], platform_post_id="export/native-b",
        )

    attempts = db.list_english_world_submission_attempts(item["id"])
    assert first["platform_post_id"] == same["platform_post_id"] == "export/native-a"
    assert attempts[0]["platform_post_id"] == "export/native-a"


def test_english_world_douyin_sync_is_isolated_single_attempt_and_shares_new_limit(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(
        title="英语世界抖音同步", source_youtube_id="english-world-source",
        **paths, **calculate_package_hashes(paths),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    wechat_attempt = db.claim_english_world_submission(item["id"], evidence_dir="/wechat")
    db.complete_english_world_submission(
        item["id"], state="UNDER_REVIEW", uploader_exit_code=6,
        evidence_dir="/wechat", attempt_id=wechat_attempt["_attempt_id"],
        platform_post_id="export/wechat-native",
    )

    candidate = db.get_next_english_world_douyin_sync_candidate()
    publication = db.ensure_english_world_douyin_publication(item["id"])
    claimed = db.claim_english_world_douyin_publication(
        item["id"], daily_limit=None, evidence_dir="/douyin/attempt-1",
    )
    completed = db.complete_english_world_douyin_publication(
        item["id"], attempt_id=claimed["_attempt_id"], state="UNDER_REVIEW",
        uploader_exit_code=6, evidence_dir="/douyin/attempt-1", message="抖音已受理",
    )

    assert candidate and candidate["id"] == item["id"]
    assert publication["state"] == "QUEUED"
    assert completed["state"] == "UNDER_REVIEW"
    assert db.claim_english_world_douyin_publication(
        item["id"], daily_limit=2, evidence_dir="/douyin/attempt-2",
    ) is None
    assert len(db.list_english_world_douyin_attempts(item["id"])) == 1
    assert db.get_video_by_youtube_id("english-world-source") is None

    assert db.add_video("generic-new", "通用新片", "channel", score=80)
    db.create_douyin_publication(
        "generic-new", "f" * 64, "/tmp/generic.mp4", source_kind="NEW",
    )
    assert db.claim_next_douyin_publication("NEW", daily_limit=1) is None

    reconciled = db.record_english_world_douyin_reconciliation(
        item["id"], platform_state="PUBLISHED", evidence_dir="/douyin/reconcile",
        message="作品管理页确认已发布",
    )
    assert reconciled["state"] == "PUBLISHED"
    assert reconciled["platform_state"] == "PUBLISHED"
    assert db.list_english_world_douyin_attempts(item["id"])[0]["state"] == "PUBLISHED"


def test_english_world_douyin_management_evidence_can_correct_canceled_publication(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(
        title="管理页外部已发布", source_youtube_id="external-published-source",
        **paths, **calculate_package_hashes(paths),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    wechat_attempt = db.claim_english_world_submission(item["id"], evidence_dir="/wechat")
    db.complete_english_world_submission(
        item["id"], state="UNDER_REVIEW", uploader_exit_code=6,
        evidence_dir="/wechat", attempt_id=wechat_attempt["_attempt_id"],
        platform_post_id="export/wechat-native",
    )
    db.ensure_english_world_douyin_publication(item["id"])
    claimed = db.claim_english_world_douyin_publication(
        item["id"], daily_limit=1, evidence_dir="/douyin/attempt-1",
    )
    db.complete_english_world_douyin_publication(
        item["id"], attempt_id=claimed["_attempt_id"], state="CANCELED",
        uploader_exit_code=3, evidence_dir="/douyin/attempt-1", message="提交前闸门未通过",
    )

    reconciled = db.record_english_world_douyin_canceled_published_reconciliation(
        item["id"], evidence_dir="/douyin/management-evidence",
        message="作品管理页按完整标题和来源链接确认已发布",
    )

    assert reconciled["state"] == "PUBLISHED"
    assert reconciled["platform_state"] == "PUBLISHED"
    assert reconciled["published_at"] is not None
    attempts = db.list_english_world_douyin_attempts(item["id"])
    assert attempts[0]["state"] == "CANCELED"
    with pytest.raises(ValueError, match="Only an attempted CANCELED"):
        db.record_english_world_douyin_canceled_published_reconciliation(
            item["id"], evidence_dir="/douyin/management-evidence", message="重复对账",
        )


def test_english_world_douyin_proven_pre_submit_uncertain_can_recover_once(tmp_path):
    """旧上传器在点击前拒绝却返回 7 时，只能凭原始证据恢复一次。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(
        title="发布前拒绝恢复", source_youtube_id="pre-submit-uncertain-source",
        **paths, **calculate_package_hashes(paths),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    wechat_attempt = db.claim_english_world_submission(item["id"], evidence_dir="/wechat")
    db.complete_english_world_submission(
        item["id"], state="UNDER_REVIEW", uploader_exit_code=6,
        evidence_dir="/wechat", attempt_id=wechat_attempt["_attempt_id"],
        platform_post_id="export/wechat-native",
    )
    db.ensure_english_world_douyin_publication(item["id"])
    claimed = db.claim_english_world_douyin_publication(
        item["id"], daily_limit=None, evidence_dir="/douyin/attempt-1",
    )
    db.complete_english_world_douyin_publication(
        item["id"], attempt_id=claimed["_attempt_id"], state="UNCERTAIN",
        uploader_exit_code=7, evidence_dir="/douyin/attempt-1",
        message="抖音作品描述填写后回读不一致，拒绝发布",
    )

    recovered = db.recover_english_world_douyin_proven_pre_submit_uncertain(
        item["id"], reason="原始证据显示最终提交前文案回读拒绝。",
    )

    assert recovered["state"] == "QUEUED"
    assert recovered["submitted_at"] is None
    assert recovered["recovery_authorized_at"] is not None
    first_attempt = db.list_english_world_douyin_attempts(item["id"])[0]
    assert first_attempt["state"] == "CANCELED"
    assert first_attempt["error_message"] == "抖音作品描述填写后回读不一致，拒绝发布"
    second_claim = db.claim_english_world_douyin_publication(
        item["id"], daily_limit=None, evidence_dir="/douyin/attempt-2",
    )
    assert second_claim is not None
    with pytest.raises(ValueError, match="Only one proven pre-submit UNCERTAIN"):
        db.recover_english_world_douyin_proven_pre_submit_uncertain(
            item["id"], reason="不得重复恢复。",
        )

"""抖音浏览器发布账本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.0.6 | 2026-09-05 | Codex | 验证启动审计可区分已启动与已取消且不返回凭据秘密。 |
| 1.0.0 | 2026-07-23 | Codex | 覆盖抖音账本去重、迁移限额和审核状态 |
| 1.1.0 | 2026-07-25 | Codex | 覆盖提交后未确认的遗留失败不会被自动重投 |
| 1.2.0 | 2026-07-29 | Codex | 覆盖含未确认反证的抖音 PUBLISHED 写入会保守降级且不参与去重 |
| 1.3.0 | 2026-08-07 | Codex | 覆盖发布前闸门和页面校准旧失败的安全停用迁移 |
| 1.4.0 | 2026-08-07 | Codex | 覆盖 CANCELED 抖音账本人工重入队且保留历史记录 |
| 1.5.0 | 2026-08-08 | Codex | 覆盖缺失抖音投递产物的旧失败在恢复前安全停用 |
| 1.6.0 | 2026-08-08 | Codex | 覆盖 NEW 每日领取上限与跨进程浏览器动作节流账本 |
| 1.7.0 | 2026-08-30 | Codex | 覆盖视频号未确认造成的抖音 shadow 候选且保证不创建任务 |
| 1.8.0 | 2026-08-30 | Codex | 覆盖同阶段 UI 连续失败跨进程累计、录屏阈值和证据化清除审计 |
| 1.9.0 | 2026-08-30 | Codex | 覆盖抖音 NEW 门禁开关双模式且解耦模式不复活任何历史账本 |
| 2.0.0 | 2026-09-01 | Codex | 覆盖 HISTORY 在无日额度时仍可安全逐条领取，保留不可重传终态。 |
| 2.0.2 | 2026-09-02 | Codex | 覆盖通用、英语世界和配音投稿的数据库签发一次性浏览器启动凭据，拒绝来源伪造与重复启动。 |
| 2.0.3 | 2026-09-02 | Codex | 覆盖启动凭据一旦绑定完整投稿包即不可改写，替换标题、文案或封面都会在浏览器前拒绝。 |
| 2.0.4 | 2026-09-02 | Codex | 覆盖领取后浏览器未启动的票据仅可超时安全取消；已启动记录绝不自动回收或重传。 |
| 2.0.5 | 2026-09-02 | Codex | 覆盖已知子进程在浏览器前失败时可立即撤销通用票据，避免超时误卡 UNCERTAIN。 |
| 2.0.5 | 2026-09-02 | Codex | 覆盖 NEW 候选查询拒绝无时间或无批次边界的调用，防止未来绕过巡航守卫扫描历史。 |
"""

import hashlib
from pathlib import Path

import pytest

from video_processing.core.douyin_launch_context import douyin_submission_payload_sha256
from video_processing.db.database import PipelineDB


def _add_video(db: PipelineDB, youtube_id: str) -> None:
    assert db.add_video(youtube_id, "测试视频", "test-channel", score=80)


@pytest.mark.parametrize(
    ("lookback_hours", "limit"),
    ((None, 10), (0, 10), (24, None), (24, 0)),
)
def test_douyin_new_candidate_query_rejects_unbounded_discovery(
    tmp_path: Path,
    lookback_hours: int | None,
    limit: int | None,
):
    """NEW 查询没有有限的时间和批次边界时，必须在 DAL 处 fail closed。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))

    with pytest.raises(ValueError):
        db.get_unqueued_douyin_new_videos(
            lookback_hours=lookback_hours,
            limit=limit,
            require_wechat_public_confirmation=False,
        )


def test_douyin_ledger_only_deduplicates_assets_after_published(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "video-one")
    _add_video(db, "video-two")
    _add_video(db, "video-three")
    digest = "a" * 64

    first = db.create_douyin_publication("video-one", digest, "/tmp/one.mp4", source_kind="HISTORY")
    retryable = db.create_douyin_publication("video-two", digest, "/tmp/two.mp4", source_kind="HISTORY")
    assert retryable["id"] != first["id"]

    assert db.update_douyin_publication_state(first["id"], "PUBLISHED")
    duplicate = db.create_douyin_publication("video-three", digest, "/tmp/three.mp4", source_kind="HISTORY")

    assert duplicate["id"] == first["id"]
    assert db.get_douyin_publication("video-one")["state"] == "PUBLISHED"
    assert db.get_douyin_publication("video-two")["state"] == "QUEUED"


def test_douyin_published_with_unconfirmed_evidence_is_not_success_dedup(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "video-one")
    _add_video(db, "video-two")
    digest = "8" * 64

    first = db.create_douyin_publication("video-one", digest, "/tmp/one.mp4", source_kind="HISTORY")
    assert db.update_douyin_publication_state(
        first["id"],
        "PUBLISHED",
        error_message="抖音已接受发布提交，当前按审核中处理；等待作品管理回查校准后确认最终发布。",
    )
    second = db.create_douyin_publication("video-two", digest, "/tmp/two.mp4", source_kind="HISTORY")

    first_row = db.get_douyin_publication("video-one")
    assert first_row["state"] == "UNDER_REVIEW"
    assert first_row["published_at"] is None
    assert second["id"] != first["id"]
    assert db.get_douyin_publication("video-two")["state"] == "QUEUED"


def test_douyin_same_video_can_create_a_new_attempt_after_failure(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "retry-video")
    digest = "d" * 64

    first = db.create_douyin_publication("retry-video", digest, "/tmp/retry.mp4", source_kind="HISTORY")
    assert db.update_douyin_publication_state(first["id"], "RETRYABLE_FAILED")
    second = db.create_douyin_publication("retry-video", digest, "/tmp/retry.mp4", source_kind="HISTORY")

    assert second["attempt_number"] == 2
    assert second["state"] == "QUEUED"


def test_douyin_history_claim_respects_daily_limit_and_uncertain_never_requeues(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "history-one")
    _add_video(db, "history-two")
    db.create_douyin_publication("history-one", "b" * 64, "/tmp/one.mp4", source_kind="HISTORY")
    db.create_douyin_publication("history-two", "c" * 64, "/tmp/two.mp4", source_kind="HISTORY")

    claimed = db.claim_next_douyin_history_publication(daily_limit=1)
    assert claimed is not None
    assert claimed["state"] == "UPLOADING"
    assert db.claim_next_douyin_history_publication(daily_limit=1) is None

    assert db.update_douyin_publication_state(claimed["id"], "UNCERTAIN", error_message="页面关闭前未确认")
    assert db.claim_next_douyin_history_publication(daily_limit=2) is not None
    assert db.claim_next_douyin_history_publication(daily_limit=2) is None


def test_douyin_history_claim_has_no_daily_cap_when_limit_is_none(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "history-one")
    _add_video(db, "history-two")
    db.create_douyin_publication("history-one", "b" * 64, "/tmp/one.mp4", source_kind="HISTORY")
    db.create_douyin_publication("history-two", "c" * 64, "/tmp/two.mp4", source_kind="HISTORY")

    first = db.claim_next_douyin_publication("HISTORY", daily_limit=None)
    assert first is not None
    assert db.update_douyin_publication_state(first["id"], "UNDER_REVIEW")

    second = db.claim_next_douyin_publication("HISTORY", daily_limit=None)

    assert second is not None
    assert second["youtube_id"] == "history-two"


def test_douyin_history_candidates_only_include_wechat_published_and_non_blacklisted(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "published-video")
    _add_video(db, "pending-video")
    _add_video(db, "blocked-video")
    db.update_video_status("published-video", "PUBLISHED")
    db.update_video_status("blocked-video", "PUBLISHED")
    assert db.add_to_blacklist("blocked-video", "wechat_takedown_prohibited")

    candidates = db.get_unqueued_douyin_history_videos()

    assert [candidate["youtube_id"] for candidate in candidates] == ["published-video"]


def test_douyin_under_review_is_a_terminal_submission_state_not_a_duplicate_retry(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "under-review-video")
    publication = db.create_douyin_publication(
        "under-review-video", "0" * 64, "/tmp/review.mp4", source_kind="HISTORY"
    )
    assert db.update_douyin_publication_state(publication["id"], "UNDER_REVIEW")

    assert db.get_douyin_publication("under-review-video")["state"] == "UNDER_REVIEW"
    assert db.claim_next_douyin_history_publication(daily_limit=10) is None


def test_unconfirmed_douyin_failure_is_not_claimed_again(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "maybe-submitted")
    publication = db.create_douyin_publication(
        "maybe-submitted", "1" * 64, "/tmp/maybe.mp4", source_kind="NEW"
    )
    assert db.update_douyin_publication_state(
        publication["id"],
        "RETRYABLE_FAILED",
        error_message="抖音提交后未能在作品管理确认可见；请先人工核对，勿切换视频。",
    )

    assert db.claim_next_douyin_publication("NEW") is None


def test_pre_submit_gate_failures_are_canceled_without_touching_review_states(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "pre-submit-gate")
    _add_video(db, "uncalibrated")
    _add_video(db, "missing-assets")
    _add_video(db, "under-review")
    gate = db.create_douyin_publication(
        "pre-submit-gate", "3" * 64, "/tmp/gate.mp4", source_kind="HISTORY"
    )
    calibration = db.create_douyin_publication(
        "uncalibrated", "4" * 64, "/tmp/calibration.mp4", source_kind="HISTORY"
    )
    missing_assets = db.create_douyin_publication(
        "missing-assets", "6" * 64, "/tmp/missing-assets.mp4", source_kind="NEW"
    )
    review = db.create_douyin_publication(
        "under-review", "5" * 64, "/tmp/review.mp4", source_kind="HISTORY"
    )
    assert db.update_douyin_publication_state(
        gate["id"], "RETRYABLE_FAILED", error_message="发布前元信息、封面或自主声明闸门未能确认；本次未提交。"
    )
    assert db.update_douyin_publication_state(
        calibration["id"], "RETRYABLE_FAILED", error_message="抖音上传器尚未完成页面校准；本次没有触发发布。"
    )
    assert db.update_douyin_publication_state(
        missing_assets["id"], "RETRYABLE_FAILED", error_message="抖音投递产物缺失：video=True copy=True title=True cover=False"
    )
    assert db.update_douyin_publication_state(review["id"], "UNDER_REVIEW")

    assert db.cancel_douyin_pre_submit_gate_failures() == 3

    assert db.get_douyin_publication("pre-submit-gate")["state"] == "CANCELED"
    assert db.get_douyin_publication("uncalibrated")["state"] == "CANCELED"
    assert db.get_douyin_publication("missing-assets")["state"] == "CANCELED"
    assert db.get_douyin_publication("under-review")["state"] == "UNDER_REVIEW"
    assert db.cancel_douyin_pre_submit_gate_failures() == 0


def test_canceled_douyin_publication_requeues_as_a_new_attempt(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "requeue-video")
    original = db.create_douyin_publication(
        "requeue-video", "6" * 64, "/tmp/requeue.mp4", source_kind="NEW"
    )
    assert db.update_douyin_publication_state(original["id"], "CANCELED")

    requeued = db.requeue_canceled_douyin_publication(original["id"])

    assert requeued["id"] != original["id"]
    assert requeued["attempt_number"] == 2
    assert requeued["state"] == "QUEUED"
    assert db.get_douyin_publication_by_id(original["id"])["state"] == "CANCELED"


def test_douyin_new_video_claim_is_not_limited_by_historical_daily_quota(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "new-video")
    publication = db.create_douyin_publication(
        "new-video", "e" * 64, "/tmp/new.mp4", source_kind="NEW"
    )

    claimed = db.claim_next_douyin_publication("NEW")

    assert claimed is not None
    assert claimed["id"] == publication["id"]
    assert claimed["youtube_id"] == "new-video"


def test_new_douyin_claim_issues_one_time_browser_ticket_and_history_cannot_consume_it(tmp_path: Path):
    """浏览器启动能力必须来自 NEW 领取账本，而不是 CLI 的 source_kind 文本。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "new-video")
    _add_video(db, "history-video")
    new_video = tmp_path / "new.mp4"
    history_video = tmp_path / "history.mp4"
    new_video.write_bytes(b"new-video")
    history_video.write_bytes(b"history-video")
    new_copy = tmp_path / "new-copy.txt"
    new_title = tmp_path / "new-title.txt"
    new_cover = tmp_path / "new-cover.jpg"
    history_copy = tmp_path / "history-copy.txt"
    history_title = tmp_path / "history-title.txt"
    history_cover = tmp_path / "history-cover.jpg"
    for path, content in (
        (new_copy, b"new-copy"), (new_title, b"new-title"), (new_cover, b"new-cover"),
        (history_copy, b"history-copy"), (history_title, b"history-title"), (history_cover, b"history-cover"),
    ):
        path.write_bytes(content)
    new_digest = hashlib.sha256(new_video.read_bytes()).hexdigest()
    history_digest = hashlib.sha256(history_video.read_bytes()).hexdigest()
    new_publication = db.create_douyin_publication(
        "new-video", new_digest, str(new_video.resolve()), source_kind="NEW",
    )
    history_publication = db.create_douyin_publication(
        "history-video", history_digest, str(history_video.resolve()), source_kind="HISTORY",
    )

    new_claim = db.claim_douyin_publication(new_publication["id"])
    history_claim = db.claim_douyin_publication(history_publication["id"])

    assert new_claim is not None
    assert history_claim is not None
    new_payload = douyin_submission_payload_sha256(
        video_path=new_video, copy_path=new_copy, title_path=new_title, cover_path=new_cover,
    )
    history_payload = douyin_submission_payload_sha256(
        video_path=history_video, copy_path=history_copy, title_path=history_title, cover_path=history_cover,
    )
    assert new_payload and history_payload
    assert db.bind_douyin_browser_launch_ticket_payload(
        new_claim["_douyin_launch_ticket_id"],
        new_claim["_douyin_launch_token"],
        payload_sha256=new_payload,
    )
    assert db.bind_douyin_browser_launch_ticket_payload(
        history_claim["_douyin_launch_ticket_id"],
        history_claim["_douyin_launch_token"],
        payload_sha256=history_payload,
    )
    history_title.write_bytes(b"history-title-tampered")
    tampered_history_payload = douyin_submission_payload_sha256(
        video_path=history_video,
        copy_path=history_copy,
        title_path=history_title,
        cover_path=history_cover,
    )
    assert tampered_history_payload and tampered_history_payload != history_payload
    # 签发后既不能把 ticket 重绑到新的包，也不能携带替换后的包启动浏览器。
    assert not db.bind_douyin_browser_launch_ticket_payload(
        history_claim["_douyin_launch_ticket_id"],
        history_claim["_douyin_launch_token"],
        payload_sha256=tampered_history_payload,
    )
    assert not db.begin_douyin_browser_launch(
        history_claim["_douyin_launch_ticket_id"],
        history_claim["_douyin_launch_token"],
        video_path=str(history_video.resolve()),
        asset_sha256=history_digest,
        payload_sha256=tampered_history_payload,
        require_new_source=False,
    )
    assert db.begin_douyin_browser_launch(
        new_claim["_douyin_launch_ticket_id"],
        new_claim["_douyin_launch_token"],
        video_path=str(new_video.resolve()),
        asset_sha256=new_digest,
        payload_sha256=new_payload,
        require_new_source=True,
    )
    # 一次性 ticket 不可重放；没有可执行的第二次浏览器启动。
    assert not db.begin_douyin_browser_launch(
        new_claim["_douyin_launch_ticket_id"],
        new_claim["_douyin_launch_token"],
        video_path=str(new_video.resolve()),
        asset_sha256=new_digest,
        payload_sha256=new_payload,
        require_new_source=True,
    )
    # HISTORY 即使持有其自身签发的 ticket，也绝不能跨过纯管理页熔断。
    assert not db.begin_douyin_browser_launch(
        history_claim["_douyin_launch_ticket_id"],
        history_claim["_douyin_launch_token"],
        video_path=str(history_video.resolve()),
        asset_sha256=history_digest,
        payload_sha256=history_payload,
        require_new_source=True,
    )


def test_stale_unstarted_generic_douyin_ticket_is_canceled_but_started_ticket_is_preserved(
    tmp_path: Path,
):
    """父进程在打开浏览器前消失可恢复；任何已开始记录仍必须留在不确定边界。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    for youtube_id in ("prelaunch-generic", "started-generic"):
        _add_video(db, youtube_id)
    fixtures = []
    for stem in ("prelaunch", "started"):
        video = tmp_path / f"{stem}.mp4"
        copy = tmp_path / f"{stem}-copy.txt"
        title = tmp_path / f"{stem}-title.txt"
        cover = tmp_path / f"{stem}-cover.jpg"
        for path, content in (
            (video, f"{stem}-video".encode()),
            (copy, b"copy"),
            (title, b"title"),
            (cover, b"cover"),
        ):
            path.write_bytes(content)
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        publication = db.create_douyin_publication(
            f"{stem}-generic", digest, str(video.resolve()), source_kind="NEW",
        )
        claim = db.claim_douyin_publication(publication["id"])
        payload = douyin_submission_payload_sha256(
            video_path=video, copy_path=copy, title_path=title, cover_path=cover,
        )
        assert claim and payload
        assert db.bind_douyin_browser_launch_ticket_payload(
            claim["_douyin_launch_ticket_id"], claim["_douyin_launch_token"], payload_sha256=payload,
        )
        fixtures.append((video, digest, payload, publication, claim))

    started_video, started_digest, started_payload, _, started_claim = fixtures[1]
    assert db.begin_douyin_browser_launch(
        started_claim["_douyin_launch_ticket_id"],
        started_claim["_douyin_launch_token"],
        video_path=str(started_video.resolve()),
        asset_sha256=started_digest,
        payload_sha256=started_payload,
        require_new_source=True,
    )

    assert db.cancel_stale_generic_douyin_prelaunch_attempts(
        min_age_seconds=0,
        reason="父进程已退出，浏览器从未启动。",
    ) == 1
    prelaunch_video, prelaunch_digest, prelaunch_payload, prelaunch_publication, prelaunch_claim = fixtures[0]
    canceled = db.get_douyin_publication_by_id(prelaunch_publication["id"])
    assert canceled["state"] == "CANCELED"
    assert "浏览器从未启动" in str(canceled["last_error_message"])
    assert not db.begin_douyin_browser_launch(
        prelaunch_claim["_douyin_launch_ticket_id"],
        prelaunch_claim["_douyin_launch_token"],
        video_path=str(prelaunch_video.resolve()),
        asset_sha256=prelaunch_digest,
        payload_sha256=prelaunch_payload,
        require_new_source=True,
    )
    assert db.get_douyin_publication_by_id(fixtures[1][3]["id"])["state"] == "UPLOADING"
    launch_status = db.get_douyin_publication_launch_status(fixtures[1][3]["id"])
    assert len(launch_status) == 1
    assert launch_status[0]["launch_started_at"]
    assert "token_sha256" not in launch_status[0]
    assert "_douyin_launch_token" not in launch_status[0]
    canceled_status = db.get_douyin_publication_launch_status(prelaunch_publication["id"])
    assert canceled_status[0]["prelaunch_canceled_at"]
    assert canceled_status[0]["launch_started_at"] is None
    assert db.cancel_stale_generic_douyin_prelaunch_attempts(
        min_age_seconds=0,
        reason="重复回收不得改变已启动记录。",
    ) == 0


def test_known_generic_prelaunch_failure_cancels_ticket_before_marking_submission_uncertain(
    tmp_path: Path,
):
    """父进程掌握 ticket 时无需等 TTL；只要未启动即可精确取消，而非错误保留 UNCERTAIN。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "known-prelaunch")
    video = tmp_path / "known-prelaunch.mp4"
    copy = tmp_path / "known-prelaunch-copy.txt"
    title = tmp_path / "known-prelaunch-title.txt"
    cover = tmp_path / "known-prelaunch-cover.jpg"
    for path, content in ((video, b"video"), (copy, b"copy"), (title, b"title"), (cover, b"cover")):
        path.write_bytes(content)
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    payload = douyin_submission_payload_sha256(
        video_path=video, copy_path=copy, title_path=title, cover_path=cover,
    )
    assert payload
    publication = db.create_douyin_publication(
        "known-prelaunch", digest, str(video.resolve()), source_kind="NEW",
    )
    claim = db.claim_douyin_publication(publication["id"])
    assert claim
    assert db.bind_douyin_browser_launch_ticket_payload(
        claim["_douyin_launch_ticket_id"], claim["_douyin_launch_token"], payload_sha256=payload,
    )

    assert db.cancel_douyin_publication_pre_launch_failure(
        publication["id"],
        ticket_id=claim["_douyin_launch_ticket_id"],
        reason="子进程在进入上传器前超时。",
    )
    canceled = db.get_douyin_publication_by_id(publication["id"])
    assert canceled["state"] == "CANCELED"
    assert "浏览器未启动" in str(canceled["last_error_message"])
    assert not db.begin_douyin_browser_launch(
        claim["_douyin_launch_ticket_id"],
        claim["_douyin_launch_token"],
        video_path=str(video.resolve()),
        asset_sha256=digest,
        payload_sha256=payload,
        require_new_source=True,
    )


def test_dubbing_douyin_launch_ticket_claims_once_and_completes_without_double_count(tmp_path: Path):
    """配音必须先原子领取平台账本；启动/完成同一次尝试不能被记成两次上传。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "dubbing-source")
    db.update_video_status("dubbing-source", "PUBLISHED")
    video = tmp_path / "dubbing.mp4"
    video.write_bytes(b"dubbing-video")
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    copy = tmp_path / "copy.txt"
    title = tmp_path / "title.txt"
    cover = tmp_path / "cover.jpg"
    for path, content in ((copy, b"copy"), (title, b"title"), (cover, b"cover")):
        path.write_bytes(content)
    payload = douyin_submission_payload_sha256(
        video_path=video, copy_path=copy, title_path=title, cover_path=cover,
    )
    assert payload
    job = db.create_dubbing_job(
        "dubbing-source",
        model="test-model",
        voice_id="test-voice",
        requested_platforms=["douyin"],
    )
    db.update_dubbing_job(
        job["id"],
        "PUBLISHING",
        output_video_path=str(video.resolve()),
        asset_sha256=digest,
    )

    claim = db.claim_dubbing_douyin_publication_launch(job["id"], payload_sha256=payload)

    assert claim is not None
    assert claim["state"] == "UPLOADING"
    assert claim["attempt_count"] == 1
    assert not db.begin_douyin_browser_launch(
        claim["_douyin_launch_ticket_id"],
        "wrong-token",
        video_path=str(video.resolve()),
        asset_sha256=digest,
        payload_sha256=payload,
        require_new_source=True,
    )
    assert db.begin_douyin_browser_launch(
        claim["_douyin_launch_ticket_id"],
        claim["_douyin_launch_token"],
        video_path=str(video.resolve()),
        asset_sha256=digest,
        payload_sha256=payload,
        require_new_source=True,
    )
    completed = db.complete_dubbing_douyin_publication_launch(
        claim["id"],
        "CANCELED",
        error_message="发布前闸门未通过",
    )

    assert completed["state"] == "CANCELED"
    assert completed["attempt_count"] == 1
    assert not db.begin_douyin_browser_launch(
        claim["_douyin_launch_ticket_id"],
        claim["_douyin_launch_token"],
        video_path=str(video.resolve()),
        asset_sha256=digest,
        payload_sha256=payload,
        require_new_source=True,
    )


def test_stale_unstarted_dubbing_douyin_ticket_is_canceled_without_touching_started_launch(
    tmp_path: Path,
):
    """配音同样只回收可证明未打开浏览器的领取，保留原尝试审计。"""
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "dubbing-prelaunch")
    db.update_video_status("dubbing-prelaunch", "PUBLISHED")
    video = tmp_path / "dubbing-prelaunch.mp4"
    copy = tmp_path / "dubbing-prelaunch-copy.txt"
    title = tmp_path / "dubbing-prelaunch-title.txt"
    cover = tmp_path / "dubbing-prelaunch-cover.jpg"
    for path, content in ((video, b"video"), (copy, b"copy"), (title, b"title"), (cover, b"cover")):
        path.write_bytes(content)
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    payload = douyin_submission_payload_sha256(
        video_path=video, copy_path=copy, title_path=title, cover_path=cover,
    )
    assert payload
    job = db.create_dubbing_job(
        "dubbing-prelaunch", model="test-model", voice_id="test-voice", requested_platforms=["douyin"],
    )
    db.update_dubbing_job(
        job["id"], "PUBLISHING", output_video_path=str(video.resolve()), asset_sha256=digest,
    )
    claim = db.claim_dubbing_douyin_publication_launch(job["id"], payload_sha256=payload)
    assert claim

    assert db.cancel_stale_dubbing_douyin_prelaunch_attempts(
        min_age_seconds=0,
        reason="人工投稿进程在浏览器启动前中断。",
    ) == 1
    publications = db.get_dubbing_publications(job["id"])
    assert len(publications) == 1
    assert publications[0]["state"] == "CANCELED"
    assert "浏览器启动前" in str(publications[0]["last_error_message"])
    assert not db.begin_douyin_browser_launch(
        claim["_douyin_launch_ticket_id"],
        claim["_douyin_launch_token"],
        video_path=str(video.resolve()),
        asset_sha256=digest,
        payload_sha256=payload,
        require_new_source=True,
    )


def test_douyin_new_video_claim_respects_its_own_daily_quota(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _add_video(db, "new-video-one")
    _add_video(db, "new-video-two")
    db.create_douyin_publication("new-video-one", "a" * 64, "/tmp/one.mp4", source_kind="NEW")
    db.create_douyin_publication("new-video-two", "b" * 64, "/tmp/two.mp4", source_kind="NEW")

    first = db.claim_next_douyin_publication("NEW", daily_limit=1)

    assert first is not None
    assert db.claim_next_douyin_publication("NEW", daily_limit=1) is None


def test_douyin_upstream_shadow_is_read_only_and_excludes_other_cancellations(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    for yid in ("blocked-without-ledger", "blocked-canceled", "content-canceled"):
        _add_video(db, yid)
        db.record_wechat_submission_acceptance(
            yid,
            evidence_path=None,
            error_message="视频号已受理，等待公开确认",
            final_title="测试标题",
        )
    upstream = db.create_douyin_publication(
        "blocked-canceled", "8" * 64, "/tmp/upstream.mp4", source_kind="NEW"
    )
    db.update_douyin_publication_state(
        upstream["id"], "CANCELED", error_message="视频号仅确认提交、尚未确认公开发布；已取消下游未提交队列。"
    )
    content = db.create_douyin_publication(
        "content-canceled", "9" * 64, "/tmp/content.mp4", source_kind="NEW"
    )
    db.update_douyin_publication_state(
        content["id"], "CANCELED", error_message="抖音上传前内容安全审查缺少可读字幕正文。"
    )

    snapshot = db.get_douyin_upstream_shadow_snapshot(limit=5)
    gated_candidates = db.get_unqueued_douyin_new_videos(
        lookback_hours=24,
        limit=5,
        require_wechat_public_confirmation=True,
    )
    independent_candidates = db.get_unqueued_douyin_new_videos(
        lookback_hours=24,
        limit=5,
        require_wechat_public_confirmation=False,
    )

    assert snapshot["count"] == 2
    assert snapshot["without_ledger_count"] == 1
    assert snapshot["independent_eligible_count"] == 1
    assert {row["youtube_id"] for row in snapshot["items"]} == {
        "blocked-without-ledger", "blocked-canceled"
    }
    assert db.get_douyin_publication("blocked-without-ledger") is None
    assert db.get_douyin_publication_by_id(upstream["id"])["state"] == "CANCELED"
    assert gated_candidates == []
    assert [row["youtube_id"] for row in independent_candidates] == ["blocked-without-ledger"]
    assert db.get_douyin_publication_by_id(upstream["id"])["state"] == "CANCELED"


def test_douyin_browser_action_slot_persists_the_interval(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))

    assert db.reserve_douyin_browser_action_slot(120, "first", now_epoch=1_000) == 0
    assert db.reserve_douyin_browser_action_slot(120, "second", now_epoch=1_050) == 70
    assert db.reserve_douyin_browser_action_slot(120, "third", now_epoch=1_120) == 0


def test_douyin_ui_failure_streak_persists_and_clears_with_evidence(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))

    first = db.record_platform_ui_failure(
        "douyin", "publish_pre_submit", "未定位自主声明", recording_threshold=2
    )
    second = db.record_platform_ui_failure(
        "douyin",
        "publish_pre_submit",
        "未定位自主声明",
        evidence_path="/tmp/douyin_self_declaration_failed_controls.json",
        recording_threshold=2,
    )

    assert first["consecutive_failures"] == 1
    assert first["recording_requested_at"] is None
    assert second["consecutive_failures"] == 2
    assert second["active"] == 1
    assert second["recording_requested_at"] is not None
    assert second["evidence_path"].endswith("douyin_self_declaration_failed_controls.json")

    assert db.clear_platform_ui_failure_streak(
        "douyin", "publish_pre_submit", "/tmp/douyin_ready_to_submit_controls.json"
    )
    cleared = db.get_platform_ui_failure_streaks("douyin")[0]
    assert cleared["active"] == 0
    assert cleared["consecutive_failures"] == 0
    assert cleared["cleared_at"] is not None
    assert cleared["clear_evidence_path"].endswith("douyin_ready_to_submit_controls.json")

    restarted = db.record_platform_ui_failure(
        "douyin", "publish_pre_submit", "页面再次漂移", recording_threshold=2
    )
    assert restarted["active"] == 1
    assert restarted["consecutive_failures"] == 1

"""英语世界抖音浏览器启动前失败恢复测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-02 | Codex | 覆盖未启动票据的审计取消、显式恢复和过期进程崩溃收口边界。 |
"""

from __future__ import annotations

from pathlib import Path

from video_processing.core.douyin_launch_context import douyin_submission_payload_sha256
from video_processing.db.database import PipelineDB
from video_processing.english_world.package_integrity import calculate_package_hashes


def _claim_english_world_douyin(db: PipelineDB, tmp_path: Path) -> tuple[dict, dict, dict[str, str]]:
    paths: dict[str, str] = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        paths[f"{field}_path"] = str(path)
    item = db.create_english_world_review_item(
        title="浏览器启动前恢复", source_youtube_id="prelaunch-recovery-source",
        **paths, **calculate_package_hashes(paths),
    )
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    wechat_claim = db.claim_english_world_submission(item["id"], evidence_dir="/wechat")
    db.complete_english_world_submission(
        item["id"], state="UNDER_REVIEW", uploader_exit_code=6,
        evidence_dir="/wechat", attempt_id=wechat_claim["_attempt_id"],
        platform_post_id="export/wechat-native",
    )
    db.ensure_english_world_douyin_publication(item["id"])
    claimed = db.claim_english_world_douyin_publication(
        item["id"], daily_limit=None, evidence_dir="/douyin/attempt-1",
    )
    assert claimed is not None
    return item, claimed, paths


def _payload(paths: dict[str, str]) -> str:
    payload = douyin_submission_payload_sha256(
        video_path=paths["mp4_path"],
        copy_path=paths["copy_path"],
        title_path=paths["title_path"],
        cover_path=paths["cover_path"],
    )
    assert payload
    return payload


def test_english_world_prelaunch_failure_is_canceled_audited_and_explicitly_recoverable(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    item, claimed, paths = _claim_english_world_douyin(db, tmp_path)

    canceled = db.cancel_english_world_douyin_pre_launch_failure(
        item["id"],
        attempt_id=claimed["_attempt_id"],
        ticket_id=claimed["_douyin_launch_ticket_id"],
        evidence_dir="/douyin/prelaunch-failure",
        message="投稿包位级校验失败",
    )

    assert canceled and canceled["state"] == "CANCELED"
    assert "发布前浏览器未启动" in canceled["last_error_message"]
    attempts = db.list_english_world_douyin_attempts(item["id"])
    assert len(attempts) == 1
    assert attempts[0]["state"] == "CANCELED"
    assert attempts[0]["finished_at"] is not None
    with db.get_connection() as conn:
        ticket = conn.execute(
            "SELECT prelaunch_canceled_at, prelaunch_cancel_reason FROM douyin_browser_launch_tickets WHERE ticket_id = ?",
            (claimed["_douyin_launch_ticket_id"],),
        ).fetchone()
    assert ticket and ticket["prelaunch_canceled_at"] is not None
    assert "发布前浏览器未启动" in ticket["prelaunch_cancel_reason"]
    # CANCELED 不会被日常领取自动重投；必须走既有的具名恢复入口。
    assert db.claim_english_world_douyin_publication(
        item["id"], daily_limit=None, evidence_dir="/douyin/automatic-retry",
    ) is None
    assert not db.begin_douyin_browser_launch(
        claimed["_douyin_launch_ticket_id"],
        claimed["_douyin_launch_token"],
        video_path=paths["mp4_path"],
        asset_sha256=claimed["artifact_sha256"],
        payload_sha256=_payload(paths),
        require_new_source=False,
    )

    recovered = db.authorize_english_world_douyin_pre_submit_recovery(
        item["id"], reason="修复本地投稿包后人工确认恢复",
    )
    assert recovered["state"] == "QUEUED"
    assert db.claim_english_world_douyin_publication(
        item["id"], daily_limit=None, evidence_dir="/douyin/explicit-recovery",
    ) is not None


def test_english_world_prelaunch_recovery_never_cancels_a_ticket_after_launch_started(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    item, claimed, paths = _claim_english_world_douyin(db, tmp_path)
    payload = _payload(paths)
    assert db.bind_douyin_browser_launch_ticket_payload(
        claimed["_douyin_launch_ticket_id"],
        claimed["_douyin_launch_token"],
        payload_sha256=payload,
    )
    assert db.begin_douyin_browser_launch(
        claimed["_douyin_launch_ticket_id"],
        claimed["_douyin_launch_token"],
        video_path=paths["mp4_path"],
        asset_sha256=claimed["artifact_sha256"],
        payload_sha256=payload,
        require_new_source=False,
    )

    canceled = db.cancel_english_world_douyin_pre_launch_failure(
        item["id"],
        attempt_id=claimed["_attempt_id"],
        ticket_id=claimed["_douyin_launch_ticket_id"],
        evidence_dir="/douyin/late-failure",
        message="浏览器启动后的异常",
    )

    assert canceled is None
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE douyin_browser_launch_tickets SET issued_at = datetime('now', '-20 minutes') WHERE ticket_id = ?",
            (claimed["_douyin_launch_ticket_id"],),
        )
        conn.commit()
    assert db.cancel_stale_english_world_douyin_pre_launch_failure(
        item["id"], stale_after_seconds=60, evidence_dir="/douyin/stale-after-launch",
    ) is None
    assert db.get_english_world_douyin_publication(item["id"])["state"] == "SUBMITTING"
    assert db.list_english_world_douyin_attempts(item["id"])[0]["state"] == "SUBMITTING"


def test_stale_english_world_prelaunch_ticket_is_canceled_without_automatic_retry(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    item, claimed, _paths = _claim_english_world_douyin(db, tmp_path)
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE douyin_browser_launch_tickets SET issued_at = datetime('now', '-20 minutes') WHERE ticket_id = ?",
            (claimed["_douyin_launch_ticket_id"],),
        )
        conn.commit()

    canceled = db.cancel_stale_english_world_douyin_pre_launch_failure(
        item["id"], stale_after_seconds=60, evidence_dir="/douyin/stale-prelaunch",
    )

    assert canceled and canceled["state"] == "CANCELED"
    assert "超过 60 秒" in canceled["last_error_message"]
    assert db.claim_english_world_douyin_publication(
        item["id"], daily_limit=None, evidence_dir="/douyin/automatic-retry",
    ) is None

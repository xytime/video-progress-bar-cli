"""上传零进度恢复、退避和交付统计的隔离回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-21 | Codex | 覆盖提交边界、凭据重放、退避领取、次数上限及历史回填统计。 |
"""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import wechat_uploader
from config.settings import settings
from video_processing.core.wechat_upload_recovery import (
    RECEIPT_NAME, is_zero_progress_upload,
)
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager


class UploadPage:
    """最小上传页；如果等待路径尝试点击、填文案等操作会直接失败。"""

    def __init__(self, text="0%\n取消上传", screenshot_ok=True):
        self.text = text
        self.first = self
        self.waits = 0
        self.screenshot_ok = screenshot_ok

    def wait_for_timeout(self, milliseconds):
        assert milliseconds == 5000
        self.waits += 1

    def content(self):
        return self.text

    def locator(self, selector):
        assert selector in ("body", "button:has-text('发表')")
        return self

    def inner_text(self):
        return self.text

    def count(self):
        return 1

    def get_attribute(self, name):
        return "disabled"

    def screenshot(self, path, full_page):
        if not self.screenshot_ok:
            raise OSError("screenshot unavailable")
        Path(path).write_bytes(b"png")


def manager_and_proof(tmp_path, attempt="attempt-1"):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    if not manager.db.get_video_by_youtube_id("zero-upload"):
        manager.db.add_video("zero-upload", "title", "channel", score=80)
    manager.db.update_video_status("zero-upload", "PUBLISHING")
    directory = tmp_path / "wechat_evidence" / "zero-upload" / attempt
    video = tmp_path / "zero-upload_vertical.mp4"
    video.write_bytes(b"rendered-video")
    page = UploadPage()
    assert wechat_uploader._wait_for_video_upload(page, directory, str(video)) == 7
    assert page.waits == 60
    return manager, directory, video


def recover(manager, directory, video):
    return manager._requeue_wechat_upload_timeout(
        "zero-upload", slice_index=0, evidence_dir=directory, video_path=str(video),
    )


@pytest.mark.parametrize("text", ["10% 取消上传", "100% 取消上传", "0.5% 取消上传", "0%", "取消上传", "0% 取消上传 审核中", "0% 取消上传 50%"])
def test_uncertain_or_nonzero_progress_is_not_retryable(text):
    assert not is_zero_progress_upload(text)


@pytest.mark.parametrize("text,code", [("0% 取消上传", 7), ("20% 取消上传", 1), ("上传完成", 0)])
def test_upload_wait_preserves_success_and_classifies_only_zero_timeout(tmp_path, text, code):
    page = UploadPage(text)
    assert wechat_uploader._wait_for_video_upload(page, tmp_path / "attempt", "video.mp4") == code
    assert page.waits == (1 if code == 0 else 60)


def test_missing_screenshot_cannot_authorize_retry(tmp_path):
    assert wechat_uploader._wait_for_video_upload(
        UploadPage(screenshot_ok=False), tmp_path / "attempt", "video.mp4",
    ) == 1


def test_delay_is_persistent_and_blocks_selection_and_atomic_claim(tmp_path):
    manager, directory, video = manager_and_proof(tmp_path)
    assert recover(manager, directory, video)
    row = manager.db.get_video_by_youtube_id("zero-upload")
    assert (row["status"], row["retry_count"]) == ("PENDING", 1)
    assert row["preparation_ready"] == 1
    assert video.read_bytes() == b"rendered-video"
    reopened = PipelineDB(str(tmp_path / "pipeline.db"))
    assert reopened.get_high_score_pending_videos() == []
    assert reopened.get_high_score_preparation_candidates() == []
    assert not reopened.claim_video_for_processing("zero-upload")
    with reopened.get_connection() as conn:
        delay = conn.execute("SELECT (julianday(next_attempt_at)-julianday(created_at))*1440 FROM wechat_upload_retries").fetchone()[0]
        assert delay == pytest.approx(10, abs=0.01)
        conn.execute("UPDATE wechat_upload_retries SET next_attempt_at = datetime('now','-1 second')")
    assert len(reopened.get_high_score_pending_videos()) == 1
    assert reopened.claim_video_for_processing("zero-upload")


def test_receipt_single_use_and_two_retry_limit(tmp_path):
    manager, directory, video = manager_and_proof(tmp_path)
    assert recover(manager, directory, video)
    manager.db.update_video_status("zero-upload", "PUBLISHING")
    assert not recover(manager, directory, video)
    manager, second, video = manager_and_proof(tmp_path, "attempt-2")
    assert recover(manager, second, video)
    with manager.db.get_connection() as conn:
        delay = conn.execute("SELECT (julianday(next_attempt_at)-julianday(created_at))*1440 FROM wechat_upload_retries WHERE attempt_number=2").fetchone()[0]
        assert delay == pytest.approx(30, abs=0.01)
    manager, third, video = manager_and_proof(tmp_path, "attempt-3")
    assert not recover(manager, third, video)
    assert manager.db.get_video_by_youtube_id("zero-upload")["retry_count"] == 2


@pytest.mark.parametrize("state", ["FAILED", "PENDING", "UNCERTAIN", "PUBLISHED", "UNDER_REVIEW"])
def test_no_historical_or_uncertain_task_recovery(tmp_path, state):
    manager, directory, video = manager_and_proof(tmp_path)
    manager.db.update_video_status("zero-upload", state)
    assert not recover(manager, directory, video)
    assert manager.db.get_video_by_youtube_id("zero-upload")["status"] == state


@pytest.mark.parametrize("barrier", ["ledger", "archive", "attempt", "screenshot", "receipt"])
def test_all_submission_evidence_blocks_retry(tmp_path, barrier):
    manager, directory, video = manager_and_proof(tmp_path)
    if barrier in {"ledger", "archive"}:
        manager.db.record_wechat_publication_confirmation("zero-upload", evidence_path=None, state="UNCERTAIN")
        if barrier == "archive":
            manager.db.archive_wechat_publication_as_historical_unresolved("zero-upload", reason="test archive")
            manager.db.update_video_status("zero-upload", "PUBLISHING")
    elif barrier == "attempt":
        manager.db.record_wechat_submission_attempt("zero-upload", evidence_path="prior.png", final_title="title")
    else:
        prior = directory.parent / "prior-attempt"
        prior.mkdir()
        (prior / ("post_list_after_submission.png" if barrier == "screenshot" else "submission_receipt.json")).write_text("evidence")
    assert not recover(manager, directory, video)
    assert manager.db.get_video_by_youtube_id("zero-upload")["retry_count"] == 0


@pytest.mark.parametrize("field,value", [("attempt_id", "other"), ("video_path", "other.mp4"), ("submit_attempted", True), ("visible_text", "30% 取消上传"), ("stage", "PUBLISHING")])
def test_mismatched_receipt_is_fail_closed(tmp_path, field, value):
    manager, directory, video = manager_and_proof(tmp_path)
    path = directory / RECEIPT_NAME
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    assert not recover(manager, directory, video)


def test_generic_publish_failure_stays_non_retryable(tmp_path):
    manager, _, _ = manager_and_proof(tmp_path)
    assert not manager._requeue_transient_pre_submission_failure("zero-upload", "title", "HTTP error 500")


def test_slice_retry_is_scoped_to_actual_s_prefix(tmp_path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.db.add_video("sliced", "parent", "channel", score=80)
    parent_id = manager.db.get_video_by_youtube_id("sliced")["id"]
    manager.db.add_video("sliced", "slice", "channel", score=80, slice_index=1, parent_id=parent_id)
    manager.db.update_video_status("sliced", "PUBLISHING", slice_index=1)
    directory = tmp_path / "wechat_evidence" / "sliced_s1" / "attempt"
    video = tmp_path / "sliced_s1_vertical.mp4"
    video.write_bytes(b"slice")
    assert wechat_uploader._wait_for_video_upload(UploadPage(), directory, str(video)) == 7
    assert manager._requeue_wechat_upload_timeout("sliced", slice_index=1, evidence_dir=directory, video_path=str(video))
    assert manager.db.get_video_by_youtube_id("sliced", slice_index=1)["retry_count"] == 1
    assert manager.db.get_video_by_youtube_id("sliced")["retry_count"] == 0


def test_parallel_receipt_consumers_schedule_only_once(tmp_path):
    manager, directory, video = manager_and_proof(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: recover(manager, directory, video), range(2)))
    assert sorted(results) == [False, True]
    assert manager.db.get_video_by_youtube_id("zero-upload")["retry_count"] == 1


def test_retry_record_and_status_rollback_together(tmp_path):
    manager, directory, video = manager_and_proof(tmp_path)
    with manager.db.get_connection() as conn:
        conn.execute("""CREATE TRIGGER fail_requeue BEFORE UPDATE ON processed_videos
                     WHEN NEW.status = 'PENDING' BEGIN SELECT RAISE(ABORT, 'rollback probe'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="rollback probe"):
        recover(manager, directory, video)
    with manager.db.get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM wechat_upload_retries").fetchone()[0] == 0
    assert manager.db.get_video_by_youtube_id("zero-upload")["status"] == "PUBLISHING"


def test_daily_counts_ignore_bulk_updated_at_and_use_beijing_day(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("old", "old", "channel", score=80)
    db.update_video_status("old", "PUBLISHED")
    db.record_wechat_publication_confirmation("old", evidence_path="old.png", state="PUBLISHED")
    db.record_wechat_submission_attempt("old", evidence_path="old.png", final_title="old")
    health = db.read_daily_ops_health(db.db_path)
    start = health["day_start_utc"]
    assert start.endswith("16:00:00")
    bj = timezone(timedelta(hours=8))
    expected = datetime.now(bj).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    assert start == expected.strftime("%Y-%m-%d %H:%M:%S")
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_submission_attempts SET created_at = datetime(?,'-1 second')", (start,))
        conn.execute("UPDATE wechat_publications SET confirmed_at = datetime(?,'-1 second')", (start,))
    health = db.read_daily_ops_health(db.db_path)
    assert health["accepted_today"] == health["confirmed_today"] == 0
    db.add_video("new", "new", "channel", score=80)
    db.record_wechat_submission_acceptance("new", evidence_path="new.png", final_title="new", error_message="accepted")
    health = db.read_daily_ops_health(db.db_path)
    assert health["accepted_today"] == 1
    assert health["confirmed_today"] == 0
    db.record_wechat_publication_confirmation("new", evidence_path="new.png", state="PUBLISHED")
    assert db.read_daily_ops_health(db.db_path)["confirmed_today"] == 1


def test_queue_excludes_discovery_and_existing_ledger(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("discovery", "title", "channel", score=90, source="DISCOVERY")
    db.add_video("accepted", "title", "channel", score=90)
    db.record_wechat_publication_confirmation("accepted", evidence_path=None, state="UNCERTAIN")
    assert db.get_high_score_pending_videos() == []
    assert db.read_daily_ops_health(db.db_path)["queue"] == 0


def test_delivery_alert_fires_for_drained_queue_and_is_silent_after_acceptance(tmp_path, monkeypatch):
    manager, directory, video = manager_and_proof(tmp_path)
    assert recover(manager, directory, video)
    monkeypatch.setattr(settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(settings, "enable_public_publish_windows", False)
    messages = []
    monkeypatch.setattr("video_processing.pipeline_manager.send_telegram_text", lambda **kwargs: messages.append(kwargs))
    manager._check_wechat_delivery_health()
    assert len(messages) == 1
    assert messages[0]["cooldown_seconds"] == 14400
    assert messages[0]["priority"] == "P1"
    manager.db.record_wechat_submission_acceptance("zero-upload", evidence_path="accepted.png", final_title="title", error_message="accepted")
    manager._check_wechat_delivery_health()
    assert len(messages) == 1


def test_four_hour_alert_uses_delivery_dedupe_receipts(tmp_path, monkeypatch):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager.telegram_token, manager.telegram_chat_id = "test-token", "test-chat"
    manager.db.add_video("old-accepted", "title", "channel", score=80)
    manager.db.record_wechat_submission_acceptance("old-accepted", evidence_path="old.png", final_title="title", error_message="accepted")
    with manager.db.get_connection() as conn:
        conn.execute("UPDATE wechat_submission_attempts SET created_at=datetime('now','-5 hours')")
    monkeypatch.setattr(settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(settings, "enable_public_publish_windows", False)
    calls = []

    class Response:
        ok = True
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"message_id": 42}}

    def fake_post(*_args, **kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr("video_processing.telegram_delivery.requests.post", fake_post)
    manager._check_wechat_delivery_health()
    manager._check_wechat_delivery_health()
    assert len(calls) == 1
    assert "超过 4 小时" in calls[0]["json"]["text"]
    monkeypatch.setattr(settings, "wechat_publishing_paused", True)
    manager._check_wechat_delivery_health()
    assert len(calls) == 1

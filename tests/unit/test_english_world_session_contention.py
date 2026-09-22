"""真实会话锁与临时账本联合验证：评论占用不是投稿失败。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 覆盖领取前占用、子进程竞争及具名旧故障恢复边界。 |
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import submit_english_world_review as submitter, wechat_uploader
from video_processing.core.wechat_session_lock import EXIT_WECHAT_SESSION_BUSY, WeChatSessionLock
from video_processing.db.database import PipelineDB
from video_processing.english_world.package_integrity import calculate_package_hashes


def package(tmp_path):
    paths = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / field
        path.write_text(field)
        paths[field + "_path"] = str(path)
    db = PipelineDB(str(tmp_path / "output/pipeline.db"))
    item = db.create_english_world_review_item(title="会话锁测试", **paths, **calculate_package_hashes(paths))
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    db.authorize_english_world_operator_recovery(item["id"], reason="隔离测试的具名授权")
    return db, db.get_english_world_review_item(item["id"])


def test_uploader_busy_has_distinct_code_and_never_starts_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(wechat_uploader.settings, "enable_wechat_comment_interaction", True)
    def forbidden_browser():
        raise AssertionError("会话忙时不得启动浏览器")
    monkeypatch.setattr(wechat_uploader, "sync_playwright", forbidden_browser)
    state = tmp_path / "state.json"
    with WeChatSessionLock(state):
        assert wechat_uploader.run_uploader(state_path=str(state)) == EXIT_WECHAT_SESSION_BUSY


def test_submitter_busy_does_not_claim_or_upload(tmp_path, monkeypatch):
    db, item = package(tmp_path)
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter.settings, "enable_wechat_comment_interaction", True)
    monkeypatch.setattr(submitter.settings, "wechat_publishing_paused", False)
    with WeChatSessionLock(tmp_path / "output/wechat_state.json"):
        assert submitter.submit(item["id"]) == submitter.EXIT_DEFERRED
    assert db.list_english_world_submission_attempts(item["id"]) == []
    assert db.get_english_world_review_item(item["id"])["state"] == "SUBMISSION_APPROVED"


def test_session_race_after_claim_preserves_queue_and_capability(tmp_path, monkeypatch):
    db, item = package(tmp_path)
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter, "_require_publish_package", lambda _item: False)
    monkeypatch.setattr(submitter.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=EXIT_WECHAT_SESSION_BUSY, stderr=""))
    assert submitter.submit(item["id"]) == submitter.EXIT_DEFERRED
    saved = db.get_english_world_review_item(item["id"])
    assert saved["state"] == "SUBMISSION_APPROVED"
    assert saved["submission_started_at"] is None and saved["platform_post_id"] is None
    assert saved["authorization_expires_at"] == item["authorization_expires_at"]
    attempts = db.list_english_world_submission_attempts(item["id"])
    assert len(attempts) == 1 and attempts[0]["uploader_exit_code"] == EXIT_WECHAT_SESSION_BUSY
    assert db.claim_english_world_submission(item["id"], evidence_dir=str(tmp_path / "next"))


@pytest.mark.parametrize("artifact", ["submission_receipt.json", "upload.png"])
def test_session_deferral_refuses_any_browser_evidence(tmp_path, artifact):
    db, item = package(tmp_path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    claimed = db.claim_english_world_submission(item["id"], evidence_dir=str(evidence))
    (evidence / artifact).write_text("observed")
    with pytest.raises(ValueError, match="untouched"):
        db.defer_english_world_session_busy(item["id"], attempt_id=claimed["_attempt_id"], evidence_dir=str(evidence))
    assert db.get_english_world_review_item(item["id"])["state"] == "SUBMITTING"


@pytest.mark.parametrize("invalid", [None, "audit", "evidence", "identity", "expired"])
def test_legacy_recovery_needs_named_audit_and_preserves_original_attempt(tmp_path, invalid):
    db, item = package(tmp_path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    claimed = db.claim_english_world_submission(item["id"], evidence_dir=str(evidence))
    db.complete_english_world_submission(item["id"], attempt_id=claimed["_attempt_id"],
        state="FAILED", uploader_exit_code=1, evidence_dir=str(evidence), message="legacy failure")
    original = db.list_english_world_submission_attempts(item["id"])
    audit = {"state": "PRE_BROWSER_FAILURE_CONFIRMED", "review_id": item["id"],
             "attempt_id": claimed["_attempt_id"], "operator": "test", "reason": "fixture audit",
             "submit_attempted": False, "evidence": ["synthetic test evidence"]}
    if invalid == "audit": audit.pop("reason")
    if invalid == "evidence": (evidence / "browser.png").write_text("observed")
    if invalid == "identity":
        import sqlite3
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE english_world_review_items SET platform_post_id = 'native' WHERE id = ?", (item["id"],))
    if invalid == "expired":
        import sqlite3
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE english_world_review_items SET authorization_expires_at = datetime('now','-1 minute') WHERE id = ?", (item["id"],))
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit))
    def recover():
        return db.reopen_english_world_audited_prelaunch_failure(item["id"],
                    attempt_id=claimed["_attempt_id"], audit_path=str(audit_file))
    if invalid:
        with pytest.raises(ValueError): recover()
    else:
        assert recover()["state"] == "SUBMISSION_APPROVED"
        with pytest.raises(ValueError): recover()
    assert db.list_english_world_submission_attempts(item["id"]) == original

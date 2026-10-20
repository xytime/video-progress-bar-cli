"""只恢复有明确上传前限流证据的原包；已投稿、结果不明与二次失败禁止重发。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 真实临时账本和文件哈希验证具名恢复，保留旧失败尝试。 |
"""
import hashlib
import json
from pathlib import Path

import pytest
from tests.unit.test_english_world_session_contention import package


@pytest.mark.parametrize("invalid", [None, "intent", "accepted", "phase", "artifact", "audit", "unknown_file", "protected"])
def test_named_preupload_rate_limit_recovery_is_narrow_and_preserves_history(tmp_path, invalid):
    db, item = package(tmp_path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    claimed = db.claim_english_world_submission(item["id"], evidence_dir=str(evidence))
    rate = {"state": "UNCERTAIN", "reason": "PLATFORM_RATE_LIMITED", "business_code": -360, "phase": "PRE_UPLOAD"}
    progress = {"version": 1, "video": str(Path(item["mp4_path"]).resolve()), "submit_intent": False}
    if invalid == "intent":
        progress["submit_intent"] = True
    if invalid == "phase":
        rate["phase"] = "READBACK"
    if invalid == "accepted":
        (evidence / "submission_receipt.json").write_text("{}")
    if invalid == "unknown_file":
        (evidence / "upload.png").write_text("after upload")
    rate_file, progress_file = evidence / "management_rate_limit.json", evidence / "submission_progress.json"
    rate_file.write_text(json.dumps(rate))
    progress_file.write_text(json.dumps(progress))
    db.complete_english_world_submission(item["id"], attempt_id=claimed["_attempt_id"],
        state="UNDER_REVIEW" if invalid == "protected" else "FAILED", uploader_exit_code=1,
        evidence_dir=str(evidence), message="pre-upload limit fixture")
    original = db.list_english_world_submission_attempts(item["id"])
    audit = {"state": "PLATFORM_PRE_UPLOAD_RATE_LIMIT_CONFIRMED", "operator": "unit-test", "reason": "fixture",
             "review_id": item["id"], "attempt_id": claimed["_attempt_id"], "artifact_sha256": item["artifact_sha256"],
             "rate_receipt_sha256": hashlib.sha256(rate_file.read_bytes()).hexdigest(),
             "progress_sha256": hashlib.sha256(progress_file.read_bytes()).hexdigest()}
    if invalid == "audit":
        audit["attempt_id"] = "other-attempt"
    if invalid == "artifact":
        Path(item["mp4_path"]).write_text("different video")
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit))

    def recover():
        return db.authorize_english_world_preupload_rate_limit_recovery(item["id"],
            attempt_id=claimed["_attempt_id"], audit_path=str(audit_file))

    if invalid:
        with pytest.raises(ValueError):
            recover()
    else:
        assert recover()["state"] == "SUBMISSION_APPROVED"
        with pytest.raises(ValueError):
            recover()
        second_evidence = tmp_path / "second"
        second_evidence.mkdir()
        second = db.claim_english_world_submission(item["id"], evidence_dir=str(second_evidence))
        db.complete_english_world_submission(item["id"], attempt_id=second["_attempt_id"],
            state="FAILED", uploader_exit_code=1, evidence_dir=str(second_evidence), message="second failure")
        with pytest.raises(ValueError):
            recover()
    persisted = {row["attempt_id"]: row for row in db.list_english_world_submission_attempts(item["id"])}
    assert persisted[claimed["_attempt_id"]] == original[0]

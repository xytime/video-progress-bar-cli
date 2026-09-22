"""声明策略 → 投稿器 → DAL 的隔离回执测试，不调用平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 覆盖声明包绑定、未知状态阻断及审核/尝试账本原生 ID 持久化。 |
"""
import json
from pathlib import Path

import pytest

from scripts import submit_english_world_review as submitter
from scripts import wechat_uploader
from video_processing.db.database import PipelineDB
from video_processing.english_world.package_integrity import calculate_package_hashes


def _package(tmp_path, policy="DO_NOT_DECLARE"):
    item = {}
    for field in ("mp4", "manifest", "title", "copy", "cover", "cover_provenance"):
        path = tmp_path / f"{field}.bin"
        path.write_text(field, encoding="utf-8")
        item[f"{field}_path"] = str(path)
    manifest = {"content_type": "ENGLISH_WORLD_SHORT"}
    if policy is not None:
        manifest["wechat_original_declaration"] = policy
    Path(item["manifest_path"]).write_text(json.dumps(manifest), encoding="utf-8")
    return {**item, **calculate_package_hashes(item)}


@pytest.mark.parametrize("policy,required", [(None, True), ("REQUIRE_ORIGINAL", True), ("DO_NOT_DECLARE", False)])
def test_policy_is_bound_to_manifest(tmp_path, policy, required):
    item = _package(tmp_path, policy)
    assert submitter._original_declaration_required(item) is required
    command = submitter._english_world_uploader_command(
        item, tmp_path / "evidence", require_original_declaration=required,
    )
    assert ("--require-original-declaration" in command) is required
    assert ("--no-original-declaration" in command) is not required
    Path(item["manifest_path"]).write_text('{"wechat_original_declaration":"DO_NOT_DECLARE"}')
    with pytest.raises(ValueError, match="hash mismatch"):
        submitter._original_declaration_required(item)


@pytest.mark.parametrize("policy", ["", False, "OPTIONAL", [], {}])
def test_unknown_policy_is_rejected(tmp_path, policy):
    with pytest.raises(ValueError, match="policy is invalid"):
        submitter._original_declaration_required(_package(tmp_path, policy))


@pytest.mark.parametrize("ui_state,allowed", [(None, False), ("UNKNOWN", False), ("DECLARED", False), ("NOT_DECLARED", True)])
def test_no_original_requires_explicit_unchecked_evidence(tmp_path, ui_state, allowed):
    wechat_uploader._write_original_declaration_receipt(
        tmp_path, required=False, requested=False, applied=ui_state == "DECLARED", ui_state=ui_state,
    )
    assert submitter._original_declaration_receipt_is_confirmed(
        tmp_path, require_original_declaration=False,
    ) is allowed
    assert not submitter._original_declaration_receipt_is_confirmed(tmp_path)
    assert wechat_uploader._original_declaration_publish_allowed(
        declare_original=False, require_original_declaration=False,
        declaration_applied=ui_state == "DECLARED", declaration_absent_confirmed=ui_state == "NOT_DECLARED",
    ) is allowed


def _accepted_receipt(evidence_dir):
    evidence_dir.mkdir(exist_ok=True)
    (evidence_dir / "submission_receipt.json").write_text(json.dumps({
        "matched_by": "same_session_before_after_unique_post_list_object_id_delta",
        "platform_post_id": "export/current-attempt", "platform_url": "https://channels.weixin.qq.com/platform/post/list",
    }))


@pytest.mark.parametrize("code,ui_state,expected", [
    (0, "NOT_DECLARED", "UNDER_REVIEW"), (6, "NOT_DECLARED", "UNDER_REVIEW"),
    (0, None, "UNCERTAIN"), (6, "DECLARED", "UNCERTAIN"),
    (1, "NOT_DECLARED", "UNCERTAIN"), (124, "NOT_DECLARED", "UNCERTAIN"),
])
def test_native_id_is_preserved_in_review_and_attempt_ledgers(tmp_path, code, ui_state, expected):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    item = db.create_english_world_review_item(title="临时测试稿件", **_package(tmp_path))
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    evidence_dir = tmp_path / "evidence"
    claimed = db.claim_english_world_submission(item["id"], evidence_dir=str(evidence_dir))
    _accepted_receipt(evidence_dir)
    if ui_state is not None:
        wechat_uploader._write_original_declaration_receipt(
            evidence_dir, required=False, requested=False, applied=ui_state == "DECLARED", ui_state=ui_state,
        )
    state, _ = submitter._record_submission_result(
        db, item["id"], attempt_id=claimed["_attempt_id"], code=code,
        evidence_dir=evidence_dir, require_original_declaration=False,
    )
    assert state == expected
    saved = db.get_english_world_review_item(item["id"])
    attempt = db.list_english_world_submission_attempts(item["id"])[0]
    for record in (saved, attempt):
        assert record["state"] == expected
        assert record["platform_post_id"] == "export/current-attempt"
    central = db.get_wechat_publication_for_subject(f"english_world:{item['id']}")
    assert central["platform_post_id"] == "export/current-attempt"
    assert central["state"] == ("SUBMITTED_BOUND" if expected == "UNDER_REVIEW" else "UNCERTAIN")
    assert db.claim_english_world_submission(item["id"]) is None
    if expected == "UNCERTAIN":
        assert db.get_next_english_world_douyin_sync_candidate() is None


@pytest.mark.parametrize("code,expected", [(6, "UNCERTAIN"), (124, "UNCERTAIN"), (1, "FAILED")])
def test_missing_receipts_do_not_invent_acceptance(tmp_path, code, expected):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    item = db.create_english_world_review_item(title="无平台回执", **_package(tmp_path))
    db.approve_english_world_submission(item["id"], authorization="AUTO_POLICY")
    claimed = db.claim_english_world_submission(item["id"])
    state, _ = submitter._record_submission_result(
        db, item["id"], attempt_id=claimed["_attempt_id"], code=code,
        evidence_dir=tmp_path / "missing", require_original_declaration=False,
    )
    assert state == expected
    assert db.get_english_world_review_item(item["id"])["platform_post_id"] is None


def test_submitter_passes_approved_policy_to_uploader(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    item = db.create_english_world_review_item(title="单条策略传递", **_package(tmp_path))
    db.approve_english_world_submission(item["id"], authorization="TELEGRAM_REVIEW")
    calls = []

    def uploader(command, **kwargs):
        calls.append(command)
        assert "--no-original-declaration" in command
        assert "--require-original-declaration" not in command
        evidence_dir = Path(command[command.index("--evidence-dir") + 1])
        _accepted_receipt(evidence_dir)
        wechat_uploader._write_original_declaration_receipt(
            evidence_dir, required=False, requested=False, applied=False, ui_state="NOT_DECLARED",
        )
        return type("Result", (), {"returncode": 6, "stderr": ""})()

    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    # 仅替代媒体质检；策略读取及其哈希验证仍走真实代码。
    monkeypatch.setattr(submitter, "_require_publish_package", submitter._original_declaration_required)
    monkeypatch.setattr(submitter.subprocess, "run", uploader)
    assert submitter.submit(item["id"]) == 0
    assert len(calls) == 1
    saved = db.get_english_world_review_item(item["id"])
    assert saved["state"] == "UNDER_REVIEW" and saved["platform_post_id"] == "export/current-attempt"

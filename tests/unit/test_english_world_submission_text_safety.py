"""实际发布载荷命中必须在领取和浏览器之前停止。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-22 | Codex | 真实账本验证拒绝入账、后续排队及在途/已受理保护。 |
| 1.0.0 | 2026-09-22 | Codex | 真实纯规则引擎、临时文件与一个账本替身验证投稿前置门禁。 |
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import submit_english_world_review as submitter
from video_processing.db.database import PipelineDB
from video_processing.english_world.package_integrity import calculate_package_hashes
from video_processing.english_world.safety_gate import (
    EnglishWorldSafetyGateError, require_submission_text_safety,
)


def package(tmp_path):
    timeline = tmp_path / "timeline.json"
    timeline.write_text(json.dumps({"english_text": "Children learn about science.",
                                    "translation_zh": "孩子们学习科学。"}), encoding="utf-8")
    manifest = {"content_type": "ENGLISH_WORLD_SHORT", "timeline": str(timeline)}
    item = {"id": "test-review", "state": "SUBMISSION_APPROVED", "approval_source": "OPERATOR_RECOVERY",
            "authorization_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")}
    for field, text in {"title_path": "科学英语", "copy_path": "跟随原声学习科学。",
                        "mp4_path": "synthetic fixture", "manifest_path": json.dumps(manifest),
                        "cover_path": "synthetic fixture", "cover_provenance_path": "{}"}.items():
        path = tmp_path / field
        path.write_text(text, encoding="utf-8")
        item[field] = str(path)
    return item, manifest, timeline


def register(db, item, *, operator=True):
    paths = {key: value for key, value in item.items() if key.endswith("_path")}
    saved = db.create_english_world_review_item(title="安全门测试", **paths, **calculate_package_hashes(paths))
    db.approve_english_world_submission(saved["id"], authorization="AUTO_POLICY")
    if operator:
        db.authorize_english_world_operator_recovery(saved["id"], reason="测试具名授权")
    return db.get_english_world_review_item(saved["id"])


@pytest.mark.parametrize("target", ["title_path", "copy_path", "english_text", "translation_zh"])
def test_submission_blocks_unsafe_actual_text_before_claim_or_upload(tmp_path, monkeypatch, target):
    item, manifest, timeline = package(tmp_path)
    if target.endswith("_path"):
        Path(item[target]).write_text("习近平", encoding="utf-8")
    else:
        content = json.loads(timeline.read_text())
        content[target] = "xi jinping" if target == "english_text" else "习近平"
        timeline.write_text(json.dumps(content), encoding="utf-8")

    db = PipelineDB(str(tmp_path / "output/pipeline.db"))
    item = register(db, item)
    uploader = Mock(side_effect=AssertionError("安全门命中不得上传"))
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter.subprocess, "run", uploader)
    assert submitter.submit(item["id"]) == 1
    uploader.assert_not_called()
    saved = db.get_english_world_review_item(item["id"])
    assert saved["state"] == "FAILED" and "投稿前校验拒绝" in saved["error_message"]
    assert saved["submission_started_at"] is None and saved["uploader_exit_code"] is None
    assert db.list_english_world_submission_attempts(item["id"]) == []
    assert submitter.submit(item["id"]) == 0
    uploader.assert_not_called()


def test_rejected_preflight_releases_queue_head_without_submitting_next(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / "output/pipeline.db"))
    items = []
    for name in ("blocked", "next"):
        folder = tmp_path / name
        folder.mkdir()
        item, _, _ = package(folder)
        Path(item["mp4_path"]).write_text("distinct synthetic video " + name)
        if name == "blocked":
            Path(item["title_path"]).write_text("习近平", encoding="utf-8")
        items.append(register(db, item, operator=False))
    with db.get_connection() as conn:
        conn.execute("UPDATE english_world_review_items SET approved_at = datetime('now','-1 minute') WHERE id = ?",
                     (items[0]["id"],))
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(type(submitter.settings), "is_english_world_publish_window", lambda self: True)
    assert db.get_next_auto_approved_english_world_submission()["id"] == items[0]["id"]
    assert submitter.submit(items[0]["id"]) == 1
    assert db.get_next_auto_approved_english_world_submission()["id"] == items[1]["id"]
    assert all(db.list_english_world_submission_attempts(item["id"]) == [] for item in items)


@pytest.mark.parametrize("protected", ["SUBMITTING", "UNDER_REVIEW", "UNCERTAIN", "native_id", "platform_state"])
def test_preflight_failure_cannot_overwrite_submission_facts(tmp_path, protected):
    db = PipelineDB(str(tmp_path / "output/pipeline.db"))
    item, _, _ = package(tmp_path)
    item = register(db, item)
    with db.get_connection() as conn:
        if protected == "native_id":
            conn.execute("UPDATE english_world_review_items SET platform_post_id = 'export/native' WHERE id = ?", (item["id"],))
        elif protected == "platform_state":
            conn.execute("UPDATE english_world_review_items SET platform_state = 'UNKNOWN' WHERE id = ?", (item["id"],))
        else:
            conn.execute("UPDATE english_world_review_items SET state = ? WHERE id = ?", (protected, item["id"]))
    before = db.get_english_world_review_item(item["id"])
    with pytest.raises(ValueError, match="cannot overwrite"):
        db.fail_english_world_submission_preflight(item["id"], message="synthetic rejection")
    assert db.get_english_world_review_item(item["id"]) == before


def test_submission_text_gate_rechecks_changes_and_missing_subtitles(tmp_path):
    item, manifest, timeline = package(tmp_path)
    assert require_submission_text_safety(item, manifest)["state"] == "PASS"
    timeline.write_text("{}", encoding="utf-8")
    with pytest.raises(EnglishWorldSafetyGateError, match="字幕不完整"):
        require_submission_text_safety(item, manifest)


def test_versioned_submission_cannot_omit_source_evidence(tmp_path):
    item, manifest, timeline = package(tmp_path)
    content = json.loads(timeline.read_text())
    content["language_contract"] = "english-world-language-v1"
    timeline.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(EnglishWorldSafetyGateError, match="无法读取"):
        require_submission_text_safety(item, manifest)


@pytest.mark.parametrize("changed", [None, "title_path", "copy_path", "cover"])
def test_fulltext_policy_binds_actual_publication_text(tmp_path, changed):
    from video_processing.english_world.safety_gate import FULLTEXT_SAFETY_POLICY
    item, manifest, timeline = package(tmp_path)
    content = json.loads(timeline.read_text())
    content.update(safety_policy=FULLTEXT_SAFETY_POLICY,
                   publication_text={"title": Path(item["title_path"]).read_text(),
                                     "copy": Path(item["copy_path"]).read_text(),
                                     "cover_payload": {"headline": "科学英语"}})
    timeline.write_text(json.dumps(content))
    cover = tmp_path / "cover_payload.json"
    cover.write_text(json.dumps(content["publication_text"]["cover_payload"]))
    if changed == "cover":
        cover.write_text(json.dumps({"headline": "后改的封面"}))
    elif changed:
        Path(item[changed]).write_text("未经过全文安全审核的新内容")
    if changed:
        with pytest.raises(EnglishWorldSafetyGateError, match="全文安全审核"):
            require_submission_text_safety(item, manifest)
    else:
        assert require_submission_text_safety(item, manifest)["state"] == "PASS"

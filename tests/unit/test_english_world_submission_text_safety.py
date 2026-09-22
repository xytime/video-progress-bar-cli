"""实际发布载荷命中必须在领取和浏览器之前停止。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 真实纯规则引擎、临时文件与一个账本替身验证投稿前置门禁。 |
"""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest

from scripts import submit_english_world_review as submitter
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


@pytest.mark.parametrize("target", ["title_path", "copy_path", "english_text", "translation_zh"])
def test_submission_blocks_unsafe_actual_text_before_claim_or_upload(tmp_path, monkeypatch, target):
    item, manifest, timeline = package(tmp_path)
    if target.endswith("_path"):
        from pathlib import Path
        Path(item[target]).write_text("习近平", encoding="utf-8")
    else:
        content = json.loads(timeline.read_text())
        content[target] = "xi jinping" if target == "english_text" else "习近平"
        timeline.write_text(json.dumps(content), encoding="utf-8")

    class DB:
        def get_english_world_review_item(self, _review_id):
            return item

        def claim_english_world_submission(self, *_args, **_kwargs):
            raise AssertionError("安全门命中前不得领取")

    uploader = Mock(side_effect=AssertionError("安全门命中不得上传"))
    monkeypatch.setattr(submitter, "PipelineDB", DB)
    monkeypatch.setattr(submitter, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter.subprocess, "run", uploader)
    with pytest.raises(EnglishWorldSafetyGateError):
        submitter.submit(item["id"])
    uploader.assert_not_called()


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

"""抖音单条只读回查入口测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 覆盖只读命令边界、显式回账和非明确结果不改账 |
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.reconcile_douyin_publication import reconcile_publication
from video_processing.db.database import PipelineDB


def _fixture(tmp_path: Path, state: str = "UNCERTAIN") -> tuple[PipelineDB, dict]:
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("verify-one", "测试视频", "test-channel", score=80)
    publication = db.create_douyin_publication(
        "verify-one", "a" * 64, str(tmp_path / "verify-one_vertical.mp4"), source_kind="NEW"
    )
    db.update_douyin_publication_state(publication["id"], state, error_message="等待人工核验")
    (tmp_path / "verify-one_copy.txt").write_text("足够长且唯一的测试正文" * 8, encoding="utf-8")
    (tmp_path / "verify-one_title.txt").write_text("唯一测试标题", encoding="utf-8")
    return db, publication


def test_reconcile_default_is_verify_only_and_does_not_change_ledger(tmp_path: Path):
    db, publication = _fixture(tmp_path)
    runner = MagicMock(return_value=subprocess.CompletedProcess([], 0, "published", ""))

    outcome = reconcile_publication(
        db, publication["id"], project_root=tmp_path, output_dir=tmp_path,
        python_executable="python", no_headless=False, runner=runner, env_builder=dict,
    )

    command = runner.call_args.args[0]
    assert "--verify-only" in command
    assert "--publish" not in command
    assert "--video" not in command
    assert outcome["observed_state"] == "PUBLISHED"
    assert outcome["ledger_applied"] is False
    assert db.get_douyin_publication_by_id(publication["id"])["state"] == "UNCERTAIN"


def test_reconcile_applies_only_explicit_platform_state(tmp_path: Path):
    db, publication = _fixture(tmp_path)
    runner = MagicMock(return_value=subprocess.CompletedProcess([], 6, "", "under review"))

    outcome = reconcile_publication(
        db, publication["id"], apply_ledger=True, project_root=tmp_path, output_dir=tmp_path,
        python_executable="python", no_headless=False, runner=runner, env_builder=dict,
    )

    assert outcome["observed_state"] == "UNDER_REVIEW"
    assert outcome["ledger_applied"] is True
    assert db.get_douyin_publication_by_id(publication["id"])["state"] == "UNDER_REVIEW"


def test_reconcile_unconfirmed_never_mutates_ledger(tmp_path: Path):
    db, publication = _fixture(tmp_path)
    runner = MagicMock(return_value=subprocess.CompletedProcess([], 7, "", "not found"))

    outcome = reconcile_publication(
        db, publication["id"], apply_ledger=True, project_root=tmp_path, output_dir=tmp_path,
        python_executable="python", no_headless=False, runner=runner, env_builder=dict,
    )

    assert outcome["observed_state"] == "UNCONFIRMED"
    assert outcome["ledger_applied"] is False
    assert db.get_douyin_publication_by_id(publication["id"])["state"] == "UNCERTAIN"


def test_reconcile_refuses_non_review_state_before_browser(tmp_path: Path):
    db, publication = _fixture(tmp_path, state="CANCELED")
    runner = MagicMock()

    with pytest.raises(ValueError, match="仅允许回查"):
        reconcile_publication(
            db, publication["id"], project_root=tmp_path, output_dir=tmp_path, runner=runner
        )

    runner.assert_not_called()

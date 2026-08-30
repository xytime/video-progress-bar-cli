"""抖音 UI 熔断运维入口测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 覆盖状态只读、越界/过期证据拒绝和有效校准证据清除 |
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.douyin_ui_guard import clear_guard_after_calibration, get_guard_status
from video_processing.db.database import PipelineDB


def _write_controls(path: Path, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "page": {"url": url, "title": "抖音创作者中心"},
            "controls": [{"tag": "button", "text": "发布"}],
        }),
        encoding="utf-8",
    )


def test_ui_guard_status_is_read_only(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.record_platform_ui_failure("douyin", "publish_pre_submit", "selector 漂移")

    snapshot = get_guard_status(db)

    assert snapshot["platform"] == "douyin"
    assert snapshot["stages"][0]["consecutive_failures"] == 1
    assert db.get_platform_ui_failure_streaks("douyin")[0]["active"] == 1


def test_ui_guard_refuses_evidence_outside_calibration_directory(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.record_platform_ui_failure("douyin", "publish_pre_submit", "selector 漂移")
    outside = tmp_path / "outside" / "douyin_ready_to_submit_controls.json"
    _write_controls(outside, "https://creator.douyin.com/creator-micro/content/upload")

    with pytest.raises(ValueError, match="douyin_calibration"):
        clear_guard_after_calibration(
            db,
            "publish_pre_submit",
            outside,
            calibration_dir=tmp_path / "douyin_calibration",
        )

    assert db.get_platform_ui_failure_streaks("douyin")[0]["active"] == 1


def test_ui_guard_refuses_stale_calibration_evidence(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.record_platform_ui_failure("douyin", "management_verify", "管理页 selector 漂移")
    calibration_dir = tmp_path / "douyin_calibration"
    evidence = calibration_dir / "douyin_management_evidence_controls.json"
    _write_controls(evidence, "https://creator.douyin.com/creator-micro/content/manage")

    with pytest.raises(ValueError, match="最近 24 小时"):
        clear_guard_after_calibration(
            db,
            "management_verify",
            evidence,
            calibration_dir=calibration_dir,
            now_epoch=evidence.stat().st_mtime + 24 * 60 * 60 + 1,
        )

    assert db.get_platform_ui_failure_streaks("douyin")[0]["active"] == 1


def test_ui_guard_clears_only_with_matching_fresh_controls(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.record_platform_ui_failure("douyin", "management_verify", "管理页 selector 漂移")
    calibration_dir = tmp_path / "douyin_calibration"
    evidence = calibration_dir / "douyin_management_evidence_controls.json"
    _write_controls(evidence, "https://creator.douyin.com/creator-micro/content/manage")
    now_epoch = evidence.stat().st_mtime + 10

    result = clear_guard_after_calibration(
        db,
        "management_verify",
        evidence,
        calibration_dir=calibration_dir,
        now_epoch=now_epoch,
    )

    assert result["cleared"] is True
    row = db.get_platform_ui_failure_streaks("douyin")[0]
    assert row["active"] == 0
    assert row["consecutive_failures"] == 0
    assert row["clear_evidence_path"] == str(evidence.resolve())

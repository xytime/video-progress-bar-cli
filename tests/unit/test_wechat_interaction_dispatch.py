"""主管线的互动派发只做有界委托，关闭及派发异常不影响发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-20 | Antigravity | 新增视频号上传受理（SUBMITTED_BOUND）且具备原生 post_id 时触发互动派发的回归测试。 |
| 1.0.1 | 2026-09-20 | Antigravity | 修正 mock 目标为模块级 _build_subprocess_env，杜绝实例属性假阳性 |
| 1.0.0 | 2026-09-19 | Codex | 默认关闭零派发及异步启动失败隔离回归 |
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager


@pytest.mark.parametrize("enabled,spawn_error", [(False, False), (True, False), (True, True)])
def test_dispatch_is_disabled_or_nonblocking_and_failure_is_contained(tmp_path, enabled, spawn_error):
    manager = PipelineManager.__new__(PipelineManager)
    manager._OUT_DIR = tmp_path / "output"
    manager._PRJ_ROOT = tmp_path
    manager._VENV_PYTHON = "/fixture/venv/python"
    with patch("video_processing.pipeline_manager.settings.enable_wechat_comment_interaction", enabled), patch(
        "video_processing.pipeline_manager._build_subprocess_env",
        return_value={"PYTHONPATH": "src"},
    ), patch(
        "video_processing.pipeline_manager.subprocess.Popen",
        return_value=SimpleNamespace(pid=123),
        side_effect=OSError("fixture spawn failure") if spawn_error else None,
    ) as spawn:
        manager._dispatch_wechat_interaction_worker()
        if not enabled:
            spawn.assert_not_called()
            assert not manager._OUT_DIR.exists()
        else:
            spawn.assert_called_once()
            assert spawn.call_args.kwargs["start_new_session"] is True
            assert spawn.call_args.kwargs["cwd"] == str(tmp_path)
            assert spawn.call_args.kwargs["stdout"].closed
            assert spawn.call_args.kwargs["stdout"].name == str(manager._OUT_DIR / "wechat_interaction_worker.log")
            # 返回对象没有 wait/communicate，证明主管线不等待 worker 完成。


def test_mark_submission_under_review_triggers_interaction_when_bound(tmp_path: Path):
    """受理成功且包含原生 post_id 时，必须触发互动派发（彻底与回查解耦）。"""
    db_path = tmp_path / "pipeline.db"
    db = PipelineDB(str(db_path))
    db.add_video("wc-bound-test", "Title", "Channel", score=88)

    manager = PipelineManager.__new__(PipelineManager)
    manager.db = db
    manager._OUT_DIR = tmp_path / "output"
    manager._OUT_DIR.mkdir(parents=True, exist_ok=True)
    manager.send_telegram_msg = MagicMock()
    manager._send_wechat_submission_review_material = MagicMock()
    manager._trigger_wechat_interaction = MagicMock()

    evidence_dir = tmp_path / "wechat_evidence" / "wc-bound-test" / "12345"
    evidence_dir.mkdir(parents=True)
    receipt_file = evidence_dir / "submission_receipt.json"
    receipt_file.write_text(json.dumps({"platform_post_id": "export/UzFfTestBoundPostId"}), encoding="utf-8")
    evidence_img = evidence_dir / "post_list_after_submission.png"
    evidence_img.write_bytes(b"png")

    manager._mark_wechat_submission_under_review(
        "wc-bound-test",
        "wc-bound-test",
        evidence_path=evidence_img,
        reason="platform acceptance confirmed",
        slice_index=0,
        submission_confirmed=True,
    )

    manager._trigger_wechat_interaction.assert_called_once_with(
        "export/UzFfTestBoundPostId", yid="wc-bound-test", slice_index=0
    )


def test_mark_submission_under_review_does_not_trigger_interaction_when_unconfirmed(tmp_path: Path):
    """未确认受理（如超时、异常）或未提取到原生 post_id 时，绝不派发互动。"""
    db_path = tmp_path / "pipeline.db"
    db = PipelineDB(str(db_path))
    db.add_video("wc-unconfirmed-test", "Title", "Channel", score=88)

    manager = PipelineManager.__new__(PipelineManager)
    manager.db = db
    manager._OUT_DIR = tmp_path / "output"
    manager._OUT_DIR.mkdir(parents=True, exist_ok=True)
    manager.send_telegram_msg = MagicMock()
    manager._send_wechat_submission_review_material = MagicMock()
    manager._trigger_wechat_interaction = MagicMock()

    # 1. submission_confirmed = False
    manager._mark_wechat_submission_under_review(
        "wc-unconfirmed-test",
        "wc-unconfirmed-test",
        evidence_path=None,
        reason="upload timed out",
        slice_index=0,
        submission_confirmed=False,
    )
    manager._trigger_wechat_interaction.assert_not_called()

    # 2. submission_confirmed = True 但没有 evidence / receipt (无 post_id)
    manager._mark_wechat_submission_under_review(
        "wc-unconfirmed-test",
        "wc-unconfirmed-test",
        evidence_path=None,
        reason="platform accepted without receipt",
        slice_index=0,
        submission_confirmed=True,
    )
    manager._trigger_wechat_interaction.assert_not_called()

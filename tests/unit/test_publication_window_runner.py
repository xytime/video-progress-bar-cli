"""自动发布巡航入口测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 覆盖窗口外跳过与窗口内单次完整流水线调用 |
| 1.0.1 | 2026-07-31 | Codex | 按 Pydantic Settings 的类方法替身方式隔离窗口判定 |
| 1.0.2 | 2026-07-31 | Codex | 覆盖已有巡航任务持锁时跳过重叠完整流水线 |
| 1.1.0 | 2026-08-02 | Codex | 覆盖关闭发布时段等待后的任意时刻巡航 |
| 1.2.0 | 2026-08-04 | Codex | 覆盖运行版本和完成状态记录，避免 Git revision 与活动实例混淆 |
| 1.3.0 | 2026-08-04 | Codex | 覆盖管线阶段回调写入巡航状态 |
"""

import fcntl
import json
from pathlib import Path
from unittest.mock import ANY, MagicMock

import scripts.run_publication_window as runner


def _configure_runner_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "LOCK_PATH", tmp_path / "runner.lock")
    monkeypatch.setattr(runner, "RUN_STATUS_PATH", tmp_path / "runner-status.json")


def test_runner_executes_pipeline_without_consulting_publication_window(monkeypatch, tmp_path: Path):
    _configure_runner_paths(monkeypatch, tmp_path)
    manager = MagicMock()
    pipeline_manager = MagicMock(return_value=manager)
    monkeypatch.setattr(runner, "PipelineManager", pipeline_manager)

    assert runner.run_publication_window() == 0
    pipeline_manager.assert_called_once_with(status_reporter=ANY)
    manager.run_daily_job.assert_called_once_with()


def test_runner_executes_pipeline_inside_publication_window(monkeypatch, tmp_path: Path):
    _configure_runner_paths(monkeypatch, tmp_path)
    manager = MagicMock()
    pipeline_manager = MagicMock(return_value=manager)
    monkeypatch.setattr(runner, "PipelineManager", pipeline_manager)

    assert runner.run_publication_window() == 0
    pipeline_manager.assert_called_once_with(status_reporter=ANY)
    manager.run_daily_job.assert_called_once_with()


def test_runner_skips_when_previous_window_run_holds_lock(monkeypatch, tmp_path: Path):
    lock_path = tmp_path / "runner.lock"
    lock_path.touch()
    _configure_runner_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "LOCK_PATH", lock_path)
    pipeline_manager = MagicMock()
    monkeypatch.setattr(runner, "PipelineManager", pipeline_manager)

    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        assert runner.run_publication_window() == 0

    pipeline_manager.assert_not_called()


def test_runner_records_running_instance_revision_and_completion(monkeypatch, tmp_path: Path):
    _configure_runner_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "_git_revision", lambda: "test-revision")
    manager = MagicMock()
    monkeypatch.setattr(runner, "PipelineManager", MagicMock(return_value=manager))

    assert runner.run_publication_window() == 0

    status = json.loads(runner.RUN_STATUS_PATH.read_text(encoding="utf-8"))
    assert status["state"] == "COMPLETED"
    assert status["git_revision"] == "test-revision"
    assert status["pid"] > 0
    assert status["started_at"] <= status["last_heartbeat_at"] == status["ended_at"]


def test_runner_records_pipeline_stage_context(monkeypatch, tmp_path: Path):
    _configure_runner_paths(monkeypatch, tmp_path)
    manager = MagicMock()

    def pipeline_factory(*, status_reporter):
        status_reporter({
            "current_video": "video-id",
            "current_slice_index": 0,
            "stage": "RENDERING",
            "preparation_only": False,
        })
        return manager

    monkeypatch.setattr(runner, "PipelineManager", pipeline_factory)

    assert runner.run_publication_window() == 0

    status = json.loads(runner.RUN_STATUS_PATH.read_text(encoding="utf-8"))
    assert status["current_video"] == "video-id"
    assert status["stage"] == "RENDERING"
    assert status["stage_started_at"] <= status["ended_at"]

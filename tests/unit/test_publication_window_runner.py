"""发布窗口巡航入口测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 覆盖窗口外跳过与窗口内单次完整流水线调用 |
| 1.0.1 | 2026-07-31 | Codex | 按 Pydantic Settings 的类方法替身方式隔离窗口判定 |
"""

from pathlib import Path
from unittest.mock import MagicMock

import scripts.run_publication_window as runner


def test_runner_skips_pipeline_outside_publication_window(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(runner, "LOCK_PATH", tmp_path / "runner.lock")
    monkeypatch.setattr(type(runner.settings), "is_public_publish_window", lambda self: False)
    pipeline_manager = MagicMock()
    monkeypatch.setattr(runner, "PipelineManager", pipeline_manager)

    assert runner.run_publication_window() == 0
    pipeline_manager.assert_not_called()


def test_runner_executes_pipeline_inside_publication_window(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(runner, "LOCK_PATH", tmp_path / "runner.lock")
    monkeypatch.setattr(type(runner.settings), "is_public_publish_window", lambda self: True)
    manager = MagicMock()
    pipeline_manager = MagicMock(return_value=manager)
    monkeypatch.setattr(runner, "PipelineManager", pipeline_manager)

    assert runner.run_publication_window() == 0
    pipeline_manager.assert_called_once_with()
    manager.run_daily_job.assert_called_once_with()

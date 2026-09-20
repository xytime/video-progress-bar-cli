"""主管线的互动派发只做有界委托，关闭及派发异常不影响发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-09-20 | Antigravity | 修正 mock 目标为模块级 _build_subprocess_env，杜绝实例属性假阳性 |
| 1.0.0 | 2026-09-19 | Codex | 默认关闭零派发及异步启动失败隔离回归 |
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

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

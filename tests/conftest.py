"""测试全局夹具。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-08 | Codex | 业务配置导入前检查一次性源码根和实际沙盒拒绝，禁止裸 pytest 触碰正式库 |
| 1.0.0 | 2026-07-28 | Codex | 默认关闭公开视频提交窗口守卫，避免发布类单测依赖当前时钟 |
"""

import json
from pathlib import Path

import pytest


def _require_test_sandbox():
    root = Path(__file__).resolve().parents[1]
    try:
        marker = json.loads((root / ".test-sandbox.json").read_text())
        if marker["schema"] != 1 or Path(marker["repo"]) != root or (root / ".env").exists():
            raise ValueError("测试根或配置不符合隔离契约")
        run_root = Path(marker["run_root"])
        canary = Path(marker["canary"])
        if (root != run_root / "repo" or run_root.name != "sandbox"
                or not run_root.parent.name.startswith("video-pytest-")
                or canary != run_root.parent / "outside-canary.txt"):
            raise ValueError("不是测试工具创建的独立目录")
        if not canary.is_file():
            raise ValueError("缺少外部边界探针")
        try:
            canary.read_bytes()
        except PermissionError:
            return
        raise ValueError("进程未被限制读取隔离根以外的数据")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise pytest.UsageError(
            "请使用 .venv/bin/python scripts/run_isolated_tests.py -- <pytest 参数>；"
            "测试收集前必须完成进程隔离。"
        ) from exc


_require_test_sandbox()

from config.settings import settings


@pytest.fixture(autouse=True)
def disable_public_publish_windows_by_default():
    previous = settings.enable_public_publish_windows
    settings.enable_public_publish_windows = False
    try:
        yield
    finally:
        settings.enable_public_publish_windows = previous

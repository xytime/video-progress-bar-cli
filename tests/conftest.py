"""测试全局夹具。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-10-31 | Codex | 每例隔离账户退避账本，同时保留例内跨进程共用的原生路径与锁。 |
| 1.2.0 | 2026-10-12 | Codex | 既有业务测试显式初始化独立维护状态，不改变生产缺失闭锁 |
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
def isolated_account_request_ledger():
    """例间不能继承 429；例内的子进程仍读写同一账户，风控逻辑不替换。"""
    root = Path(__file__).resolve().parents[1]
    paths = [root / 'output' / name for name in (
        '.wechat_state.json.requests.json', '.wechat_state.json.requests.jsonl')]
    saved = {path: path.read_bytes() if path.exists() else None for path in paths}
    for path in paths:
        path.unlink(missing_ok=True)
    try:
        yield
    finally:
        for path, data in saved.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)


@pytest.fixture(autouse=True)
def isolated_running_maintenance(tmp_path, monkeypatch):
    from video_processing.core.maintenance import MaintenanceGate
    path = tmp_path / "maintenance" / "state.json"
    monkeypatch.setattr(settings, "maintenance_state_path", path)
    monkeypatch.setenv("MAINTENANCE_STATE_PATH", str(path))
    control = MaintenanceGate(path)
    version = control.enter("隔离测试显式初始化")["version"]
    control.resume(version, validated=True)
    return control


@pytest.fixture(autouse=True)
def disable_public_publish_windows_by_default():
    previous = settings.enable_public_publish_windows
    settings.enable_public_publish_windows = False
    try:
        yield
    finally:
        settings.enable_public_publish_windows = previous


@pytest.fixture(autouse=True)
def isolate_ffmpeg_slot(tmp_path, monkeypatch):
    """真实媒体单测也必须使用隔离锁，不能接触或等待生产队列。"""
    import sys
    slot_dir = tmp_path / "ffmpeg-slot"
    for name in ["video_processing.core.ffmpeg_slot", "src.video_processing.core.ffmpeg_slot"]:
        if name in sys.modules:
            monkeypatch.setattr(sys.modules[name], "_DIRECTORY", slot_dir)
    try:
        from video_processing.core import ffmpeg_slot
        monkeypatch.setattr(ffmpeg_slot, "_DIRECTORY", slot_dir)
    except Exception:
        pass

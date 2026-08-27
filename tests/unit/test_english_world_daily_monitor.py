"""英语世界日更窗口后监测器测试。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-08-27 | Codex | 覆盖回执成功、运行中、已失败不重跑和缺席窗口自愈。 |
"""

from __future__ import annotations

import importlib.util
import json
import plistlib
import sys
from datetime import datetime, time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "monitor_english_world_daily.py"
PLIST = PROJECT_ROOT / "scripts" / "com.videopipeline.english-world-monitor.plist"
SPEC = importlib.util.spec_from_file_location("english_world_daily_monitor", SCRIPT)
assert SPEC and SPEC.loader
monitor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)


def _paths(tmp_path: Path) -> monitor.MonitorPaths:
    project_root = tmp_path / "project"
    log_dir = project_root / "output" / "english_world_daily"
    return monitor.MonitorPaths(
        project_root=project_root,
        log_dir=log_dir,
        lock_dir=project_root / "output" / "locks" / "english_world_daily.lock",
        python_bin=Path(sys.executable),
        daily_runner=tmp_path / "runner.py",
    )


def _receipt(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": "review", "status": "ACCEPTED"}), encoding="utf-8")


def test_accepted_receipt_marks_slot_delivered_without_recovery(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    receipt = paths.log_dir / "manual_recovery.delivery.json"
    _receipt(receipt)

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 0
    assert result["state"] == "DELIVERED"
    assert result["delivery_receipt"] == str(receipt)


def test_active_lock_marks_slot_in_progress_and_never_recovers(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    paths.lock_dir.mkdir(parents=True)
    (paths.lock_dir / "owner.json").write_text("not-json", encoding="utf-8")

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 0
    assert result["state"] == "IN_PROGRESS"
    assert result["recovery_attempted"] is False


def test_scheduled_run_without_delivery_is_reported_but_not_rerun(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    paths.log_dir.mkdir(parents=True)
    (paths.log_dir / f"run_{now:%F}_070005.log").write_text("failed", encoding="utf-8")

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 1
    assert result["state"] == "RUN_COMPLETED_WITHOUT_DELIVERY"
    assert result["recovery_attempted"] is False


def test_missing_window_runs_one_recovery_and_requires_new_receipt(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    paths.project_root.mkdir()
    receipt = paths.log_dir / "manual_recovery.delivery.json"
    paths.daily_runner.write_text(
        "from pathlib import Path\n"
        f"path = Path({str(receipt)!r})\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text('{\\\"kind\\\": \\\"review\\\", \\\"status\\\": \\\"ACCEPTED\\\"}')\n",
        encoding="utf-8",
    )

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 0
    assert result["state"] == "RECOVERED_DELIVERED"
    assert result["recovery_attempted"] is True


def test_monitor_plist_runs_after_both_production_windows():
    with PLIST.open("rb") as stream:
        configuration = plistlib.load(stream)

    assert configuration["Label"] == "com.videopipeline.english-world-monitor"
    assert configuration["StartCalendarInterval"] == [
        {"Hour": 9, "Minute": 15},
        {"Hour": 19, "Minute": 0},
    ]
    assert configuration["ProgramArguments"][-3:] == ["--slot", "07:00", "--recover-missing"]

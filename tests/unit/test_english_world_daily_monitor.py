"""英语世界日更窗口后监测器测试。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-08-27 | Codex | 覆盖回执成功、运行中、已失败不重跑和缺席窗口自愈。 |
# | 1.1.0 | 2026-08-29 | Codex | 测试显式固定窗口后回执 mtime，不再依赖执行测试时是否已过 07:00。 |
# | 1.2.0 | 2026-08-29 | Codex | 固化计划任务早晚触发分别映射 07:00 与 16:30，禁止单一固定 slot 掩盖下午缺席。 |
# | 1.3.0 | 2026-08-30 | Codex | 覆盖生产失败通知与成片交付的独立监控状态。 |
# | 1.4.0 | 2026-08-30 | Codex | 覆盖五层证据输出，锁定 Telegram 接受、提交执行与公开可见不得互相越级。 |
# | 1.5.0 | 2026-08-30 | Codex | 固化监测 LaunchAgent 使用项目 venv，而非缺依赖的宿主 pyenv。 |
# | 1.6.0 | 2026-08-30 | Codex | 固化监测 LaunchAgent 使用安装时渲染的可迁移路径模板。 |
"""

from __future__ import annotations

import importlib.util
import json
import os
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


def _receipt(path: Path, changed_at: datetime, *, kind: str = "review") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": kind, "status": "ACCEPTED"}), encoding="utf-8")
    timestamp = changed_at.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_accepted_receipt_marks_slot_delivered_without_recovery(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    receipt = paths.log_dir / "manual_recovery.delivery.json"
    _receipt(receipt, now.replace(hour=8))

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 0
    assert result["state"] == "DELIVERED"
    assert result["delivery_receipt"] == str(receipt)
    assert result["evidence_layers"]["public_visibility"] == {"state": "NOT_VERIFIED"}
    persisted = json.loads((paths.log_dir / f"monitor_{now:%F}_0700.json").read_text(encoding="utf-8"))
    assert persisted["evidence_layers"] == {
        "scheduled_window": {"state": "EXECUTED"},
        "artifact": {"state": "REVIEW_PACKAGE_REPORTED"},
        "telegram": {"state": "API_ACCEPTED"},
        "platform_submission": {"state": "NOT_SUBMITTED_OR_UNVERIFIED"},
        "public_visibility": {"state": "NOT_VERIFIED"},
    }


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


def test_accepted_failure_notice_is_reported_separately_from_missing_delivery(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    receipt = paths.log_dir / f"run_{now:%F}_070005.delivery.json"
    _receipt(receipt, now.replace(hour=7, minute=5), kind="failure_notice")

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 1
    assert result["state"] == "PRODUCTION_FAILED_REPORTED"
    assert result["failure_receipt"] == str(receipt)
    assert result["recovery_attempted"] is False
    persisted = json.loads((paths.log_dir / f"monitor_{now:%F}_0700.json").read_text(encoding="utf-8"))
    assert persisted["evidence_layers"]["artifact"]["state"] == "FAILED_REPORTED"
    assert persisted["evidence_layers"]["public_visibility"]["state"] == "NOT_VERIFIED"


def test_monitor_keeps_local_submission_report_separate_from_public_visibility(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    receipt = paths.log_dir / "auto_submission.delivery.json"
    _receipt(receipt, now.replace(hour=8), kind="review_and_auto_submission")
    receipt.write_text(json.dumps({
        "kind": "review_and_auto_submission",
        "status": "ACCEPTED",
        "submission_result": "submission_worker_exit=0; state=UNDER_REVIEW",
    }), encoding="utf-8")
    timestamp = now.replace(hour=8).timestamp()
    os.utime(receipt, (timestamp, timestamp))

    exit_code, _ = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 0
    persisted = json.loads((paths.log_dir / f"monitor_{now:%F}_0700.json").read_text(encoding="utf-8"))
    assert persisted["evidence_layers"]["platform_submission"] == {
        "state": "LOCAL_WORKER_REPORTED",
        "detail": "submission_worker_exit=0; state=UNDER_REVIEW",
    }
    assert persisted["evidence_layers"]["public_visibility"] == {"state": "NOT_VERIFIED"}


def test_successful_delivery_takes_precedence_over_earlier_failure_notice(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    _receipt(
        paths.log_dir / f"run_{now:%F}_070005.delivery.json",
        now.replace(hour=7, minute=5),
        kind="failure_notice",
    )
    delivered = paths.log_dir / "manual_recovery.delivery.json"
    _receipt(delivered, now.replace(hour=8), kind="review")

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 0
    assert result["state"] == "DELIVERED"
    assert result["delivery_receipt"] == str(delivered)


def test_missing_window_runs_one_recovery_and_requires_new_receipt(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    paths.project_root.mkdir()
    receipt = paths.log_dir / "manual_recovery.delivery.json"
    recovery_timestamp = now.replace(hour=8).timestamp()
    paths.daily_runner.write_text(
        "import os\n"
        "from pathlib import Path\n"
        f"path = Path({str(receipt)!r})\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text('{\\\"kind\\\": \\\"review\\\", \\\"status\\\": \\\"ACCEPTED\\\"}')\n"
        f"os.utime(path, ({recovery_timestamp!r}, {recovery_timestamp!r}))\n",
        encoding="utf-8",
    )

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 0
    assert result["state"] == "RECOVERED_DELIVERED"
    assert result["recovery_attempted"] is True


def test_missing_window_recovery_that_reports_production_failure_is_not_called_missing(tmp_path: Path):
    paths = _paths(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    paths.project_root.mkdir()
    receipt = paths.log_dir / "recovered_failure.delivery.json"
    recovery_timestamp = now.replace(hour=8).timestamp()
    paths.daily_runner.write_text(
        "import os\n"
        "from pathlib import Path\n"
        f"path = Path({str(receipt)!r})\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text('{\\\"kind\\\": \\\"failure_notice\\\", \\\"status\\\": \\\"ACCEPTED\\\"}')\n"
        f"os.utime(path, ({recovery_timestamp!r}, {recovery_timestamp!r}))\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )

    exit_code, result = monitor.monitor_slot(paths, slot=time(7, 0), now=now, recover_missing=True)

    assert exit_code == 1
    assert result["state"] == "RECOVERED_PRODUCTION_FAILED_REPORTED"
    assert result["failure_receipt"] == str(receipt)
    assert result["recovery_attempted"] is True
    assert result["recovery_exit_code"] == 1


def test_monitor_plist_runs_after_both_production_windows():
    with PLIST.open("rb") as stream:
        configuration = plistlib.load(stream)

    assert configuration["Label"] == "com.videopipeline.english-world-monitor"
    assert configuration["ProgramArguments"][:2] == [
        "__VENV_PYTHON__", "__PROJECT_ROOT__/scripts/monitor_english_world_daily.py",
    ]
    assert configuration["WorkingDirectory"] == "__PROJECT_ROOT__"
    assert configuration["EnvironmentVariables"]["PYTHONPATH"] == "__PROJECT_ROOT__/src"
    assert configuration["StartCalendarInterval"] == [
        {"Hour": 9, "Minute": 15},
        {"Hour": 19, "Minute": 0},
    ]
    assert configuration["ProgramArguments"][-1:] == ["--recover-missing"]
    assert "--slot" not in configuration["ProgramArguments"]


def test_monitor_infers_each_production_slot_from_observation_time():
    morning = datetime(2026, 8, 29, 9, 15).astimezone()
    evening = datetime(2026, 8, 29, 19, 0).astimezone()

    assert monitor._slot_for_observation(morning) == time(7, 0)
    assert monitor._slot_for_observation(evening) == time(16, 30)

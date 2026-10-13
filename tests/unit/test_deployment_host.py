"""D04/D05/D11：宿主边界反例，不使用真实 launchd 或生产 API。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | PID 复用、退出等待、来源拒绝和备份前置门禁 |
"""
from types import SimpleNamespace
from pathlib import Path
import os
import signal
import subprocess
import sys

import pytest
from video_processing.core.deployment import DeploymentDenied
from video_processing.core import deployment_host as host
from video_processing.core.maintenance_runtime import process_birth


def test_d04_waits_for_real_process_exit():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    owner = {"pid": process.pid, "birth": process_birth(process.pid)}
    try:
        process.terminate()
        host.HostDeployment.wait_exit(owner)
    finally:
        process.wait(timeout=5)


def test_d04_pid_reuse_never_treated_as_original_exit(monkeypatch):
    monkeypatch.setattr(host, "process_birth", lambda pid: "new-birth")
    with pytest.raises(DeploymentDenied, match="PID_REUSED"):
        host.HostDeployment.wait_exit({"pid": 123, "birth": "old-birth"})


def test_d04_stop_timeout_never_escalates_signal(monkeypatch):
    monkeypatch.setattr(host, "process_birth", lambda pid: "birth")
    ticks = iter([0, 20])
    monkeypatch.setattr(host.time, "monotonic", lambda: next(ticks))
    with pytest.raises(DeploymentDenied, match="NORMAL_STOP_TIMEOUT"):
        host.HostDeployment.wait_exit({"pid": 123, "birth": "birth"})


def test_d04_changed_owner_prevents_stop(monkeypatch, tmp_path):
    instance = host.HostDeployment.__new__(host.HostDeployment)
    instance.control = SimpleNamespace(path=tmp_path / "control.json")
    monkeypatch.setattr(host, "read_lease_owner", lambda path: {"pid": 456, "birth": "different"})
    with pytest.raises(DeploymentDenied, match="PROCESS_OWNER_CHANGED"):
        instance.owner_check("ui", {"pid": 123, "birth": "old"})


@pytest.mark.parametrize("reason", ["LEGACY_WORKER", "UNTRACKED_BUSINESS_LOCK", "UNREGISTERED_PROCESS", "INSPECTION_UNKNOWN"])
def test_d05_unknown_inspection_never_generates_source_proof(monkeypatch, tmp_path, reason):
    instance = host.HostDeployment.__new__(host.HostDeployment)
    instance.directory = tmp_path
    instance.control = object()
    instance.plan = {"schedules": {}}
    instance.protections = lambda: None
    instance.schedules = SimpleNamespace(frozen=lambda plan, **kw: None)
    before = set(tmp_path.iterdir())
    monkeypatch.setattr(host, "inspection", lambda control: {"active": [], "unknown": [{"code": reason}], "workers": {}})
    with pytest.raises(DeploymentDenied, match="MAINTENANCE_NOT_IDLE"):
        instance.safe()
    assert set(tmp_path.iterdir()) == before


def test_d03_adopt_preflight_requires_backup_and_no_workers(tmp_path):
    instance = host.HostDeployment.__new__(host.HostDeployment)
    instance.directory = tmp_path
    instance.plan = {"schedules": {}}
    instance.protections = lambda: None
    instance.sources = SimpleNamespace(baseline=lambda: None)
    instance.safe = lambda: {"workers": {}}
    instance.schedules = SimpleNamespace(service=lambda label: {"loaded": False})
    with pytest.raises(DeploymentDenied, match="RECEIPT_UNREADABLE"):
        instance.preflight("adopt")


def test_d07_partial_adoption_recovery_is_unknown_not_repeated(tmp_path):
    instance = host.HostDeployment.__new__(host.HostDeployment)
    instance.directory = tmp_path
    instance.protections = lambda: None
    def refused(step, result):
        raise DeploymentDenied("TARGET_RUNTIME_MISMATCH")
    instance.verify = refused
    assert instance.reconcile({"pending": "adopt"}) == "UNKNOWN"


@pytest.mark.parametrize('flag',['topic_scheduler_enabled','topic_admission_enabled'])
def test_keyword_flags_in_off_adoption_protection(monkeypatch,flag):
    from config.settings import settings
    instance=host.HostDeployment.__new__(host.HostDeployment)
    instance.plan={'protections':host.protection_snapshot()}
    monkeypatch.setattr(settings,flag,True)
    with pytest.raises(DeploymentDenied,match='PROTECTION_DRIFT'):
        instance.protections()
    instance.plan={'protections':host.protection_snapshot()}
    with pytest.raises(DeploymentDenied,match='SEARCH_CLOSURE_UNCONFIRMED'):
        instance.protections()

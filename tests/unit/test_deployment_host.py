"""D04/D05/D11：宿主边界反例，不使用真实 launchd 或生产 API。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | PID 复用、退出等待、来源拒绝和备份前置门禁 |
| 1.1.0 | 2026-10-15 | Codex | 真实旧角色锁的已完成部署证明、维护限定、身份漂移与在途保护 |
"""
from types import SimpleNamespace
from pathlib import Path
import os
import signal
import subprocess
import sys
import json

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


@pytest.mark.parametrize('flag',['topic_scheduler_enabled','topic_admission_enabled','topic_trial_mode','topic_quota_verified'])
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


def completed_previous(directory, owner):
    from video_processing.core.deployment import STEPS, digest, write_json
    from config.settings import settings
    plan = {"schema": 1, "root": str(settings.project_root), "sources": {"target": "previous"}}
    write_json(directory / "plan.json", plan)
    write_json(directory / "journal.json", {"schema": 1, "plan": digest(plan), "state": "COMPLETE",
                                            "done": list(STEPS), "pending": None})
    write_json(directory / "adopt.json", {"ok": True, "target": "previous", "source_hash": owner["source_hash"]})
    write_json(directory / "start.json", {"ok": True, "inspection": {"safe": True, "workers": {"ui": owner}}})


def test_only_exact_proven_old_worker_retires_in_maintenance(tmp_path, monkeypatch, isolated_running_maintenance):
    from config.settings import settings
    from video_processing.core import maintenance_runtime as runtime
    from video_processing.core.task_lease import read_lease_owner
    # lsof 扫描进程被测试沙盒禁止；真实角色锁/birth 保留，仅模拟 cwd 观察。
    def observe_cwd(command, **kwargs):
        assert command[1:] == ['-a', '-p', str(os.getpid()), '-d', 'cwd', '-Fn']
        return subprocess.CompletedProcess(command, 0, 'n' + str(Path.cwd()) + '\n', '')
    monkeypatch.setattr(runtime.subprocess, 'run', observe_cwd)
    monkeypatch.setattr(runtime, 'code_hash', lambda: 'a' * 64)
    with runtime.role_lease('ui'):
        owner = read_lease_owner(settings.maintenance_state_path.with_suffix('.workers') / 'ui.lock')
        previous = tmp_path / 'previous'
        completed_previous(previous, owner)
        proof = host.retirement_snapshot(settings.project_root, previous)
        monkeypatch.setattr(runtime, 'code_hash', lambda: 'b' * 64)
        options = {'process_pids': {os.getpid()}, 'retiring_workers': host.retirement_owners(proof)}
        assert {'code': 'LEGACY_WORKER', 'role': 'ui'} in runtime.inspection(isolated_running_maintenance, **options)['unknown']
        with isolated_running_maintenance.admit('video', 'new-video:0') as ticket:
            ticket.start()
            isolated_running_maintenance.enter('等待当前任务')
            monkeypatch.chdir(tmp_path)
            assert not runtime.inspection(isolated_running_maintenance, **options)['workers']
            monkeypatch.chdir(settings.project_root)
            active = runtime.inspection(isolated_running_maintenance, **options)
            assert active['workers'].get('ui') == owner, active
            assert active['active'] and not active['safe']
        checked = runtime.inspection(isolated_running_maintenance, **options)
        assert checked['workers']['ui'] == owner
        assert checked['unknown'] == [{'code': 'SOURCES_NOT_VERIFIED'}]
        assert {'code': 'LEGACY_WORKER', 'role': 'ui'} in runtime.inspection(
            isolated_running_maintenance, process_pids={os.getpid()})['unknown']
        changed = dict(owner, birth='reused-pid')
        refused = runtime.inspection(isolated_running_maintenance, process_pids={os.getpid()}, retiring_workers={'ui': changed})
        assert not refused['workers']
        assert {'code': 'UNREGISTERED_PROCESS', 'pid': os.getpid()} in refused['unknown']
        unknown = runtime.inspection(isolated_running_maintenance, process_pids={os.getpid(), 99999999},
                                     retiring_workers=proof['owners'])
        assert {'code': 'UNREGISTERED_PROCESS', 'pid': 99999999} in unknown['unknown']
        (previous / 'adopt.json').write_text('{}')
        with pytest.raises(DeploymentDenied, match='RETIREMENT_PROOF_DRIFT'):
            host.retirement_owners(proof)


@pytest.mark.parametrize('fault', ['incomplete', 'source', 'owner', 'root'])
def test_retirement_requires_completed_matching_deployment(tmp_path, monkeypatch, isolated_running_maintenance, fault):
    from config.settings import settings
    from video_processing.core import maintenance_runtime as runtime
    from video_processing.core.task_lease import read_lease_owner
    with runtime.role_lease('ui'):
        owner = read_lease_owner(settings.maintenance_state_path.with_suffix('.workers') / 'ui.lock')
        completed_previous(tmp_path, owner)
        name = {'incomplete': 'journal', 'source': 'adopt', 'owner': 'start', 'root': 'plan'}[fault] + '.json'
        path = tmp_path / name
        value = json.loads(path.read_text())
        if fault == 'incomplete':
            value.update(state='FAILED', done=[], pending=None)
        elif fault == 'source':
            value['source_hash'] = 'f' * 64
        elif fault == 'owner':
            value['inspection']['workers']['ui']['birth'] = 'other'
        else:
            value['root'] = str(tmp_path)
        path.write_text(json.dumps(value))
        with pytest.raises(DeploymentDenied):
            host.retirement_snapshot(settings.project_root, tmp_path)

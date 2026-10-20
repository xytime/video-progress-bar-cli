"""全局 header 扫描边界；隔离维护状态及子进程，不访问真实视频源。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 扫描仅执行采集、互斥、失败与维护竞态释放 |
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from video_processing.core.maintenance import MaintenanceGate, MaintenanceDenied
from video_processing.core.task_lease import read_lease_owner
from web import app as web_app
from web import console_header as header


@pytest.fixture
def control(tmp_path, monkeypatch):
    gate = MaintenanceGate(tmp_path / 'maintenance.json')
    state = gate.enter('header test')
    monkeypatch.setattr(header, 'gate', lambda: gate)
    monkeypatch.setattr(web_app, 'gate', lambda: gate)
    monkeypatch.setattr(header, '_lock_path', lambda: tmp_path / 'scan.lock')
    return gate, state


def test_maintenance_rejects_scan_without_starting(control, monkeypatch):
    monkeypatch.setattr(header, 'spawn_admitted', lambda *a, **k: pytest.fail('不得启动线程'))
    with TestClient(web_app.app) as client:
        assert client.get('/api/console/header').json()['state'] == 'MAINTENANCE'
        assert client.post('/api/console/scan-channels').status_code == 503
    assert not read_lease_owner(header._lock_path())


def test_scan_command_never_runs_pipeline(control, monkeypatch):
    gate, state = control
    gate.resume(state['version'], validated=True)
    commands = []
    monkeypatch.setattr(header, 'run_admitted', lambda cmd, **kw: commands.append(cmd) or SimpleNamespace(returncode=0))
    header._scan_channels()
    assert len(commands) == 1
    assert commands[0][-2:] == [str(header.settings.project_root / 'scripts/monitor_channels.py'), '--bootstrap']
    assert header.header_status()['channel_scan']['outcome'] == 'complete'
    monkeypatch.setattr(header, 'run_admitted', lambda *a, **k: SimpleNamespace(returncode=2))
    header._scan_channels()
    assert header.header_status()['channel_scan']['outcome'] == 'error'


def test_dispatch_failure_releases_lock(control, monkeypatch):
    gate, state = control
    gate.resume(state['version'], validated=True)
    def denied(*args, **kwargs):
        raise MaintenanceDenied()
    monkeypatch.setattr(header, 'spawn_admitted', denied)
    with pytest.raises(MaintenanceDenied):
        header.scan_channels()
    assert not read_lease_owner(header._lock_path())


def test_queued_scan_rechecks_maintenance_and_releases(control, monkeypatch):
    gate, state = control
    gate.resume(state['version'], validated=True)
    queued = []
    def queue(target, **kw):
        ticket = gate._acquire(kw['role'], kw['object_key'])
        def deferred():
            try:
                with ticket.bind():
                    target()
            finally:
                ticket.close()
        queued.append(deferred)
    monkeypatch.setattr(header, 'spawn_admitted', queue)
    assert header.scan_channels()['started']
    with pytest.raises(Exception) as conflict:
        header.scan_channels()
    assert conflict.value.status_code == 409
    gate.enter('race')
    with pytest.raises(MaintenanceDenied):
        queued.pop()()
    assert not read_lease_owner(header._lock_path())

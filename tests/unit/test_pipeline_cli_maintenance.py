"""真实命令入口的维护退出不得掩盖业务错误或未知控制状态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 跨解释器复现直接入口堆栈，验证正常排空、触发源、未知状态及真实失败。 |
"""
import subprocess
import sys

import pytest

from video_processing import pipeline_manager as manager
from video_processing.core.maintenance import MaintenanceDenied


def test_actual_module_cli_exits_normally_in_maintenance(isolated_running_maintenance):
    isolated_running_maintenance.enter('native deployment drain')
    result = subprocess.run([sys.executable, '-m', 'video_processing.pipeline_manager',
                             '--trigger-source', 'dashboard_scheduler'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-2500:]
    assert 'Traceback' not in result.stderr
    assert '维护' in result.stderr
    assert isolated_running_maintenance.status()['active'] == []


def test_closed_gate_does_not_construct_manager(monkeypatch, isolated_running_maintenance):
    isolated_running_maintenance.enter('no new work')
    def forbidden(**kwargs): raise AssertionError('manager must not start')
    monkeypatch.setattr(manager, 'PipelineManager', forbidden)
    assert manager.main([]) == 0


def test_direct_cli_preserves_trigger_and_normal_result(monkeypatch):
    calls = []
    class Manager:
        def __init__(self, **kwargs): calls.append(kwargs)
        def run_daily_job(self): calls.append('completed'); return True
    monkeypatch.setattr(manager, 'PipelineManager', Manager)
    assert manager.main(['--trigger-source', 'dashboard_manual_full']) == 0
    assert calls == [dict(trigger_source='dashboard_manual_full'), 'completed']


def test_direct_cli_drains_after_accepted_work(monkeypatch, isolated_running_maintenance):
    calls = []
    class Manager:
        def __init__(self, **kwargs): pass
        def run_daily_job(self):
            calls.append('accepted_video_finished')
            isolated_running_maintenance.enter('work finished')
            raise MaintenanceDenied()
    monkeypatch.setattr(manager, 'PipelineManager', Manager)
    assert manager.main([]) == 0
    assert calls == ['accepted_video_finished']
    assert isolated_running_maintenance.status()['active'] == []


@pytest.mark.parametrize('failure', [MaintenanceDenied(), ValueError('real business failure')])
def test_running_gate_preserves_business_failures(monkeypatch, failure):
    class Manager:
        def __init__(self, **kwargs): pass
        def run_daily_job(self): raise failure
    monkeypatch.setattr(manager, 'PipelineManager', Manager)
    with pytest.raises(type(failure)) as raised: manager.main([])
    assert raised.value is failure


def test_unknown_gate_is_failure_not_normal_drain(isolated_running_maintenance):
    isolated_running_maintenance.path.write_text('{broken')
    with pytest.raises(MaintenanceDenied) as raised: manager.main([])
    assert raised.value.code == 'UNKNOWN'


def test_window_cli_unknown_gate_must_fail(isolated_running_maintenance):
    import scripts.run_publication_window as runner
    isolated_running_maintenance.path.write_text('{broken')
    with pytest.raises(MaintenanceDenied) as raised: runner.cli_main()
    assert raised.value.code == 'UNKNOWN'


def test_window_run_records_unknown_control_as_failure(tmp_path, monkeypatch, isolated_running_maintenance):
    import json
    import scripts.run_publication_window as runner
    monkeypatch.setattr(runner, 'LOCK_PATH', tmp_path / 'runner.lock')
    monkeypatch.setattr(runner, 'RUN_STATUS_PATH', tmp_path / 'status.json')
    class Manager:
        def run_daily_job(self):
            isolated_running_maintenance.path.write_text('{broken')
            raise MaintenanceDenied('UNKNOWN')
    monkeypatch.setattr(runner, 'PipelineManager', lambda **kwargs: Manager())
    with pytest.raises(MaintenanceDenied) as raised: runner.run_publication_window()
    assert raised.value.code == 'UNKNOWN'
    status = json.loads(runner.RUN_STATUS_PATH.read_text())
    assert status['state'] == 'FAILED' and status['ended_at']

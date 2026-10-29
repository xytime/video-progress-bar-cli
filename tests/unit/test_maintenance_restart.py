"""真实临时闸门/账本/flock 验证维护接管；不访问宿主 launchd 或线上数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-30 | Codex | 排空门禁、锁外退出、精确失主及闭闸调度恢复/显式接续。 |
"""
import fcntl
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from tests.unit.test_deployment_schedules import scheduling  # noqa: F401
from video_processing.core import maintenance_restart as restart
from video_processing.core.deployment import Deployment, DeploymentDenied, STEPS, digest, read_json, write_json
from video_processing.core.deployment_schedules import UI

UI_ROLES = ('ui', 'auto-pipeline', 'queue-runner', 'ready-supervisor', 'keepalive-watchdog')


def database(root):
    path = root / 'output/pipeline.db'
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE processed_videos (id INTEGER PRIMARY KEY, status TEXT)')
        connection.execute("INSERT INTO processed_videos VALUES (1,'PENDING')")
    return path


def unlocked(control):
    with control.path.with_suffix('.lock').open('rb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(stream, fcntl.LOCK_UN)


def row(control, *, pid=99999999, role='subprocess'):
    identity = 'a' * 32
    control.directory.mkdir(exist_ok=True)
    value = dict(id=identity, pid=pid, role=role, object='bounded-child', phase='ACTIVE', at=1.0)
    path = control.directory / (identity + '.json')
    path.write_text(json.dumps(value) + '\n')
    return identity, path


@pytest.fixture
def retiring(tmp_path, isolated_running_maintenance, monkeypatch):
    control = isolated_running_maintenance
    root, directory = tmp_path / 'root', tmp_path / 'audit'
    root.mkdir(); directory.mkdir()
    db = database(root)
    control.enter('健康度修复：接管已有维护')
    ui = dict(pid=99999999, birth='ui-birth', role='ui', cwd=str(root), source_hash='a' * 64)
    owners = dict(boot='boot-A', workers={'ui': ui}, processes={})
    state = dict(boot='boot-A', workers={'ui': ui}, extra=[])
    events = []
    instance = restart.RestartHost.__new__(restart.RestartHost)
    instance.root, instance.directory, instance.control = root, directory, control
    instance.plan = dict(id='restart', schedules={}, restart=dict(control=control._read(), owners=owners, deferred=[]))
    instance.protections = lambda: None
    instance.sources = SimpleNamespace(baseline=lambda: None, final=lambda: None)
    instance.web_readback = lambda **kwargs: dict(maintenance=control._read()['state'])
    instance.schedules = SimpleNamespace(
        domain='gui/test', baseline=lambda plan: None, frozen=lambda plan, **kw: None,
        require_operational_intent=lambda: None, service=lambda label: dict(pid=ui['pid']),
        runner=SimpleNamespace(run=lambda command: events.append(command)), wait_unloaded=lambda label: None)
    monkeypatch.setattr(restart, 'boot_identity', lambda: state['boot'])
    def observed(control, root, bound, allow_missing=False):
        if not allow_missing and state['workers'] != bound['workers']:
            raise DeploymentDenied('OWNER_SNAPSHOT_CHANGED')
        return dict(bound, workers=state['workers'])
    monkeypatch.setattr(restart, 'verify_owners', observed)
    def inspection(control, **kwargs):
        current = control.status()
        return dict(current, workers=state['workers'], unknown=[{'code': 'SOURCES_NOT_VERIFIED'}] + state['extra'])
    monkeypatch.setattr(restart, 'inspection', inspection)
    return SimpleNamespace(host=instance, state=state, events=events, db=db)


@pytest.mark.parametrize('fault', ['active', 'ledger', 'unknown', 'gate', 'boot'])
def test_unverified_retirement_never_writes_stop_intent_or_calls_service_manager(retiring, fault):
    p, host = retiring, retiring.host
    if fault == 'ledger':
        with sqlite3.connect(p.db) as connection:
            connection.execute("UPDATE processed_videos SET status='PUBLISHING'")
    elif fault == 'unknown':
        p.state['extra'] = [dict(code='UNTRACKED_BUSINESS_LOCK', role='pipeline')]
    elif fault == 'gate':
        host.control.resume(host.control._read()['version'], validated=True)
        host.control.enter('另一维护')
    elif fault == 'boot':
        p.state['boot'] = 'boot-B'
    if fault == 'active':
        host.control.resume(host.control._read()['version'], validated=True)
        with host.control.admit('video', 'still-running') as ticket:
            ticket.start()
            host.control.enter('健康度修复：接管已有维护')
            host.plan['restart']['control'] = host.control._read()
            with pytest.raises(DeploymentDenied, match='ACTIVE_WORK'):
                host.stop()
    else:
        with pytest.raises(DeploymentDenied):
            host.stop()
    assert p.events == [] and not (host.directory / 'stop-intent.json').exists()
    assert host.control._read()['state'] == 'MAINTENANCE'


def test_deferred_records_are_exact_non_destructive_and_real_flock_blocks(retiring):
    host = retiring.host
    identity, path = row(host.control)
    before = path.read_bytes()
    selected = restart.deferred_records(host.control, [identity], 99999999)
    assert selected[0]['row']['id'] == identity and path.read_bytes() == before
    with path.open('rb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DeploymentDenied, match='ADMISSION_HELD'):
            restart.deferred_records(host.control, [identity], 99999999)
    assert path.read_bytes() == before
    host.plan['restart']['deferred'] = selected
    retiring.state['extra'] = [dict(id=identity, code='ABANDONED_ADMISSION')]
    path.write_bytes(before + b' ')
    with pytest.raises(DeploymentDenied, match='DEFERRED_CHANGED'):
        host.stop()
    assert retiring.events == [] and path.exists()


def test_ui_exit_runs_outside_control_lock_and_partial_stop_can_resume(retiring):
    p, host = retiring, retiring.host
    before = host.control.path.read_bytes()
    crashed = [False]
    def owner_check(role, owner):
        unlocked(host.control)
        assert role == 'ui' and owner == host.plan['restart']['owners']['workers']['ui']
    def wait_exit(owner):
        unlocked(host.control)
        p.state['workers'] = {}
        if not crashed[0]:
            crashed[0] = True
            raise OSError('exit observed before archive receipt')
    host.owner_check, host.wait_exit = owner_check, wait_exit
    host.archive_deferred = lambda: unlocked(host.control)
    host.safe = lambda **kwargs: dict(workers={})
    with pytest.raises(OSError):
        host.stop()
    assert (host.directory / 'stop-intent.json').exists()
    assert host.reconcile(dict(pending='stop')) == 'NOT_STARTED'
    host.preflight('stop')  # Deployment.run(recover=True) performs this after reconcile.
    assert host.stop()['ok'] is True
    assert len([call for call in p.events if call[1] == 'bootout']) == 1
    assert host.control.path.read_bytes() == before


def test_stop_recovery_rejects_changed_intent_before_any_service_call(retiring):
    host = retiring.host
    write_json(host.directory / 'stop-intent.json', dict(plan='another-plan', owners={}))
    with pytest.raises(DeploymentDenied, match='STOP_INTENT_CHANGED'):
        host.reconcile(dict(pending='stop'))
    with pytest.raises(DeploymentDenied, match='STOP_INTENT_CHANGED'):
        host.stop()
    assert retiring.events == []


def test_archive_requires_old_ui_absent_and_keeps_exact_bytes(tmp_path, isolated_running_maintenance, monkeypatch):
    from video_processing.core import maintenance_recovery
    control = isolated_running_maintenance
    control.enter('archive only after exact old UI exits')
    identity, path = row(control)
    raw = path.read_bytes()
    host = restart.RestartHost.__new__(restart.RestartHost)
    host.control, host.directory = control, tmp_path / 'audit'
    host.directory.mkdir()
    host.plan = dict(restart=dict(control=control._read(), owners=dict(boot='boot-A', workers=dict(ui=dict(pid=99999999))),
                                  deferred=restart.deferred_records(control, [identity], 99999999)))
    monkeypatch.setattr(restart, 'boot_identity', lambda: 'boot-A')
    live = [True]
    monkeypatch.setattr(maintenance_recovery, 'process_identity',
                        lambda pid: dict(state='PRESENT', birth='same') if live[0] else dict(state='ABSENT'))
    real_recovery = maintenance_recovery.MaintenanceRecovery
    monkeypatch.setattr(restart, 'MaintenanceRecovery', lambda gate, directory: real_recovery(
        gate, directory, boot_reader=lambda: 'boot-A', process_reader=lambda pid: dict(state='ABSENT')))
    before = control.path.read_bytes()
    with pytest.raises(DeploymentDenied, match='OLD_UI_STILL_PRESENT'):
        host.archive_deferred()
    assert path.read_bytes() == raw and not (host.directory / 'deferred-archive').exists()
    live[0] = False
    result = host.archive_deferred()
    assert result['count'] == 1 and result['task_outcome'] == 'NOT_ASSESSED'
    assert not path.exists()
    assert (host.directory / 'deferred-archive' / (identity + '.lease.json')).read_bytes() == raw
    assert control.path.read_bytes() == before


@pytest.fixture
def restoring(scheduling, isolated_running_maintenance, monkeypatch):
    schedules, commands, plan = scheduling
    control = isolated_running_maintenance
    database(schedules.root)
    control.enter('闭闸恢复原调度')
    schedules.freeze(plan)
    # 对应原生 start：新 UI 已在维护中启动且 enable，其余来源仍冻结。
    commands.run(['launchctl', 'enable', schedules.domain + '/' + UI])
    commands.services[UI]['pid'] = 456
    instance = restart.RestartHost.__new__(restart.RestartHost)
    instance.root, instance.directory, instance.control = schedules.root, schedules.directory, control
    instance.plan = dict(id='restart-restore', root=str(schedules.root), schedules=plan,
                         restart=dict(control=control._read(), owners=dict(boot='boot-A', workers={
                             'ui': dict(pid=123, birth='old-ui-birth', source_hash='a' * 64, cwd=str(schedules.root))})))
    workers = {role: dict(role=role, pid=456, birth='new-ui-birth', source_hash='b' * 64,
                          protocol=1, cwd=str(schedules.root)) for role in UI_ROLES}
    instance.schedules, instance.keyword = schedules, None
    instance.lock_path = schedules.root / 'output/deployment.lock'
    instance.protections = lambda: None
    instance.sources = SimpleNamespace(final=lambda: None)
    instance.backup_valid = lambda: None
    events, failure = [], [False]
    real_run = commands.run
    def run(arguments, **kwargs):
        if arguments[:2] == ['crontab', '-'] or len(arguments) > 1 and arguments[1] in {'enable', 'disable', 'bootstrap'}:
            assert control._read()['state'] == 'MAINTENANCE'
            events.append(arguments)
        if failure[0] and arguments[:2] == ['launchctl', 'bootstrap']:
            raise OSError('injected bootstrap failure')
        return real_run(arguments, **kwargs)
    commands.run = run
    def readback(maintenance=None):
        assert control._read()['state'] == maintenance
        return dict(maintenance=maintenance)
    instance.web_readback = readback
    def safe(**kwargs):
        schedules.frozen(plan, ui_started=True)
        assert control._read()['state'] == 'MAINTENANCE'
        return dict(safe=True, workers=workers)
    instance.safe = safe
    instance.final_status = lambda: (schedules.restored(plan), readback('RUNNING'))[1]
    monkeypatch.setattr(restart, 'boot_identity', lambda: 'boot-A')
    monkeypatch.setattr(restart, 'code_hash', lambda: 'b' * 64)
    monkeypatch.setattr(restart, 'inspection', lambda gate: dict(gate.status(), workers=workers,
                                                                unknown=[dict(code='SOURCES_NOT_VERIFIED')]))
    resume = control.resume
    def checked_resume(version, **kwargs):
        assert control._read()['state'] == 'MAINTENANCE'
        schedules.restored(plan)
        schedules.require_operational_intent()
        assert read_json(instance.directory / 'restore-closed.json')['complete'] is True
        events.append('resume')
        return resume(version, **kwargs)
    control.resume = checked_resume
    return SimpleNamespace(host=instance, commands=commands, events=events, failure=failure, workers=workers)


def test_original_schedules_and_operational_intent_are_verified_before_resume(restoring):
    host = restoring.host
    original_version = host.closed()['version']
    result = host.action('resume')
    assert result['schedules_restored_before_resume'] is True
    assert restoring.events[-1] == 'resume'
    assert host.control._read()['version'] == original_version + 1
    host.schedules.restored(host.plan['schedules'])
    assert read_json(host.directory / 'resume-intent.json') == dict(plan=digest(host.plan), version=original_version)


@pytest.mark.parametrize('role', UI_ROLES)
def test_missing_ui_role_cannot_resume(restoring, role):
    p, host = restoring, restoring.host
    del p.workers[role]
    before = host.control.path.read_bytes()
    with pytest.raises(DeploymentDenied, match='RESUME_ROLES_INCOMPLETE'):
        host.action('resume')
    assert host.control.path.read_bytes() == before and 'resume' not in p.events
    assert host.control._read()['state'] == 'MAINTENANCE'
    assert not (host.directory / 'resume-intent.json').exists()


@pytest.mark.parametrize('fault', ['split-pid', 'split-birth', 'split-cwd', 'old-hash', 'old-ui'])
def test_noncurrent_or_split_ui_identity_cannot_resume(restoring, fault):
    p, host = restoring, restoring.host
    if fault.startswith('split-'):
        field = fault.removeprefix('split-')
        p.workers['queue-runner'][field] = 789 if field == 'pid' else 'different-' + field
    elif fault == 'old-hash':
        for owner in p.workers.values():
            owner['source_hash'] = 'a' * 64
    else:
        old = host.plan['restart']['owners']['workers']['ui']
        for owner in p.workers.values():
            owner.update(pid=old['pid'], birth=old['birth'])
    before = host.control.path.read_bytes()
    with pytest.raises(DeploymentDenied, match='RESUME_UI_IDENTITY_MISMATCH|RESUME_OLD_UI'):
        host.action('resume')
    assert host.control.path.read_bytes() == before and 'resume' not in p.events
    assert host.control._read()['state'] == 'MAINTENANCE'
    assert not (host.directory / 'resume-intent.json').exists()


def test_partial_restore_stays_closed_and_only_explicit_deployment_recover_continues(restoring):
    p, host = restoring, restoring.host
    row = dict(schema=1, plan=digest(host.plan), done=list(STEPS[:6]), pending='resume', state='FAILED')
    write_json(host.directory / 'journal.json', row)
    deploy = Deployment(host.plan, host.directory, host)
    p.failure[0] = True
    before = host.control.path.read_bytes()
    with pytest.raises(OSError):
        deploy.run(recover=True)
    assert host.control.path.read_bytes() == before and 'resume' not in p.events
    assert not (host.directory / 'resume-intent.json').exists()
    assert read_json(host.directory / 'restore-closed.json')['pending'] is not None
    p.failure[0] = False
    with pytest.raises(DeploymentDenied, match='RECOVERY_REQUIRED'):
        deploy.run()
    assert deploy.run(recover=True)['state'] == 'COMPLETE'
    assert p.events.count('resume') == 1 and host.control._read()['state'] == 'RUNNING'


@pytest.mark.parametrize('fault', ['cron', 'loaded-definition', 'extra-label', 'ledger'])
def test_restore_or_final_readback_conflicts_never_open_gate(restoring, fault):
    p, host = restoring, restoring.host
    if fault == 'cron':
        p.commands.crontab += b'operator-edit\n'
    elif fault == 'loaded-definition':
        Path(p.commands.services[UI]['path']).write_bytes(b'changed definition')
    elif fault == 'extra-label':
        p.commands.services['com.videopipeline.unknown'] = dict(path=Path('/unknown'), pid=None)
    else:
        with sqlite3.connect(host.root / 'output/pipeline.db') as connection:
            connection.execute("UPDATE processed_videos SET status='RENDERING'")
    before = host.control.path.read_bytes()
    with pytest.raises((DeploymentDenied, ValueError)):
        host.action('resume')
    assert host.control.path.read_bytes() == before and 'resume' not in p.events
    assert not (host.directory / 'resume-intent.json').exists()

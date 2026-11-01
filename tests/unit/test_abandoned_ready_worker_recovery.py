"""真实子进程、角色锁和失主登记验证维护退役；业务和身份未知仍拒绝。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 真实SIGTERM及原生失主归档，验证在途、子进程、身份、版本和业务账本拒绝。 |
"""
import json
import subprocess
import sys
import time
from types import MethodType

import pytest

from scripts.recover_abandoned_ready_worker import retire_abandoned_ready_worker
from tests.unit.test_deployment_partial_freeze import partial  # noqa: F401
from tests.unit.test_deployment_schedules import scheduling  # noqa: F401
from video_processing.core import deployment_host
from video_processing.core.deployment import DeploymentDenied, digest, write_json
from video_processing.core.maintenance_runtime import process_birth
from video_processing.core.task_lease import read_lease_owner


@pytest.fixture
def abandoned(partial):
    p = partial
    role = 'ready-worker'
    identity = 'a' * 32
    lock = p.host.control.path.with_suffix('.workers') / (role + '.lock')
    path = p.host.control.directory / (identity + '.json')
    path.parent.mkdir(exist_ok=True)
    script = ("import json,os,sys,subprocess; from pathlib import Path; "
              "from video_processing.core.task_lease import TaskLease; "
              "lease=TaskLease(Path(sys.argv[1])); lease.__enter__(); "
              "Path(sys.argv[2]).write_text(json.dumps(dict(id=sys.argv[3],pid=os.getpid(),"
              "role='delivery-recovery-launch',object='delivery-recovery-launch',phase='ACTIVE',at=1.0))); "
              "print('ready',flush=True)\n"
              "if sys.stdin.readline().strip() == 'zombie':\n"
              " child=subprocess.Popen([sys.executable,'-c','pass']); print(child.pid,flush=True); sys.stdin.readline()\n")
    child = subprocess.Popen([sys.executable, '-c', script, str(lock), str(path), identity],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == 'ready'
    owner = dict(read_lease_owner(lock), role=role, birth=process_birth(child.pid))
    # 原生角色核对需要锁内的完整身份；更新文件时保持子进程的真实 flock。
    lock.write_text(json.dumps(owner))
    p.host.plan['retirement']['owners'][role] = owner
    p.injection['workers'][role] = owner
    p.injection['unknown'] = [{'id': identity, 'code': 'ABANDONED_ADMISSION'}, {'code': 'SOURCES_NOT_VERIFIED'}]
    p.row['plan'] = digest(p.host.plan)
    write_json(p.host.directory / 'journal.json', p.row)
    p.host.owner_check = MethodType(deployment_host.HostDeployment.owner_check, p.host)
    p.host.wait_exit = deployment_host.HostDeployment.wait_exit
    p.identity, p.child, p.record_path = identity, child, path
    try:
        yield p
    finally:
        child.communicate('exit\n', timeout=10)


def test_idle_original_ready_worker_is_stopped_then_native_archived_with_gate_and_journal_unchanged(abandoned):
    p = abandoned
    before = p.host.control.path.read_bytes()
    journal = (p.host.directory / 'journal.json').read_bytes()
    record = p.record_path.read_bytes()
    result = retire_abandoned_ready_worker(p.host, p.version, p.identity, process_reader=lambda: '')
    assert result['stopped'] and result['archive']['count'] == 1
    assert result['task_outcome'] == 'NOT_ASSESSED' and not result['maintenance_resumed']
    assert p.host.control.path.read_bytes() == before
    assert (p.host.directory / 'journal.json').read_bytes() == journal
    assert not p.record_path.exists()
    assert (p.host.directory / 'abandoned-ready-admission' / (p.identity + '.lease.json')).read_bytes() == record
    assert p.child.wait(timeout=5) == -15


@pytest.mark.parametrize('fault', ['version', 'role', 'pid', 'unknown', 'owner', 'policy', 'ledger', 'children'])
def test_unproven_or_busy_worker_is_never_stopped(abandoned, fault, monkeypatch):
    p = abandoned
    version = p.version
    if fault == 'version':
        version += 1
    elif fault in {'role', 'pid'}:
        row = json.loads(p.record_path.read_text())
        row[fault] = 'pipeline' if fault == 'role' else p.child.pid + 1
        p.record_path.write_text(json.dumps(row))
    elif fault == 'unknown':
        p.injection['unknown'].append({'code': 'UNREGISTERED_PROCESS', 'pid': 999})
    elif fault == 'owner':
        p.injection['workers']['ready-worker'] = dict(p.injection['workers']['ready-worker'], pid=1)
    elif fault == 'policy':
        p.policy.write_text('changed')
    elif fault == 'ledger':
        import sqlite3
        with sqlite3.connect(p.host.root / 'output/pipeline.db') as c:
            c.execute("UPDATE processed_videos SET status='PUBLISHING'")
    with pytest.raises(DeploymentDenied):
        retire_abandoned_ready_worker(p.host, version, p.identity,
            process_reader=lambda: f'{p.child.pid} {p.child.pid}\n' if fault == 'children' else '')
    assert p.child.poll() is None
    assert p.record_path.exists()
    assert not (p.host.directory / 'abandoned-ready-worker-stop.json').exists()


def test_held_admission_remains_active_and_is_never_archived(abandoned):
    import fcntl
    p = abandoned
    with p.record_path.open('rb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # 独立观察并未谎报空闲：真实准入集合在最终检查中仍拒绝。
        with pytest.raises(DeploymentDenied, match='ACTIVE_OR_UNEXPECTED_UNKNOWN'):
            retire_abandoned_ready_worker(p.host, p.version, p.identity, process_reader=lambda: '')
    assert p.child.poll() is None and p.record_path.exists()


def test_kernel_confirmed_exited_child_does_not_block_idle_parent_retirement(abandoned):
    p = abandoned
    p.child.stdin.write('zombie\n'); p.child.stdin.flush()
    child_pid = int(p.child.stdout.readline())
    deadline = time.monotonic() + 5
    while True:
        try:
            process_birth(child_pid)
        except ProcessLookupError:
            break
        assert time.monotonic() < deadline
        time.sleep(.02)
    result = retire_abandoned_ready_worker(p.host, p.version, p.identity,
        process_reader=lambda: f'{child_pid} {p.child.pid}\n')
    assert result['exited_children'] == [child_pid]
    assert result['stopped'] and not p.record_path.exists()

"""部分冻结中，受控退役持失主启动登记的空闲巡检；随后原生归档登记。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 精确绑定原部署、维护版本、角色锁与启动登记，排除业务和子进程后正常退役。 |
"""
from pathlib import Path
import argparse
import fcntl
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys


def retire_abandoned_ready_worker(host, version, identity, *, process_reader=None):
    from video_processing.core.deployment import Deployment, digest, read_json, require, project_lock, write_json
    from video_processing.core.deployment_host import retirement_owners
    from video_processing.core.maintenance_runtime import inspection, process_birth
    from video_processing.core.maintenance_recovery import MaintenanceRecovery
    from video_processing.db.database import PipelineDB

    require(len(identity) == 32 and all(c in '0123456789abcdef' for c in identity), 'RECORD_INVALID')
    receipt = host.directory / 'abandoned-ready-worker-stop.json'
    with project_lock(host.lock_path):
        row = Deployment(host.plan, host.directory, host).status()
        require(row['done'] == ['baseline'] and row['pending'] == 'freeze'
                and row['error'] == 'SCHEDULE_DAEMON_NOT_DRAINED', 'PARTIAL_FREEZE_STAGE_INVALID')
        host.protections()
        host.sources.baseline()
        host.schedules.baseline(host.plan['schedules'])
        host.schedules.require_operational_intent()
        owners = retirement_owners(host.plan.get('retirement'))
        owner = owners.get('ready-worker')
        require(bool(owner), 'READY_OWNER_UNPROVEN')
        raw = inspection(host.control, retiring_workers=owners)
        expected_unknown = [{'id': identity, 'code': 'ABANDONED_ADMISSION'}, {'code': 'SOURCES_NOT_VERIFIED'}]
        require(raw['state'] == 'MAINTENANCE' and raw['version'] == version
                and raw['reason'] == '部署 ' + host.plan['id'], 'PARTIAL_FREEZE_CONTROL_DRIFT')
        require(not raw['active'] and sorted(raw['unknown'], key=digest) == sorted(expected_unknown, key=digest),
                'ACTIVE_OR_UNEXPECTED_UNKNOWN')
        require(raw['workers'].get('ui') == owners.get('ui') and raw['workers'].get('ready-worker') == owner
                and all(owners.get(role) == worker for role, worker in raw['workers'].items()), 'OWNER_DRIFT')
        path = host.control.directory / (identity + '.json')
        with host.control._locked(), os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'RECORD_NOT_REGULAR')
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = stream.read()
            admission = json.loads(data)
            require(admission.get('id') == identity and admission.get('pid') == owner['pid']
                    and admission.get('role') == 'delivery-recovery-launch'
                    and admission.get('object') == 'delivery-recovery-launch'
                    and admission.get('phase') == 'ACTIVE', 'RECORD_OWNER_OR_ROLE_INVALID')
            state = host.control._read()
            active, unknown = host.control._leases()
            require(state['state'] == 'MAINTENANCE' and state['version'] == version
                    and state['reason'] == '部署 ' + host.plan['id'], 'PARTIAL_FREEZE_CONTROL_DRIFT')
            # 本工具临时持有待归档记录锁；唯一可见 active 必须恰好是该原始登记。
            require(active == [admission] and not unknown, 'ADMISSION_SET_CHANGED')
            require(not PipelineDB.maintenance_active_work(host.root / 'output/pipeline.db'), 'UNFINISHED_LEDGER')
            processes = (process_reader() if process_reader is not None else
                         subprocess.check_output(['ps', '-axo', 'pid=,ppid='], text=True, timeout=2))
            exited_children = []
            for line in processes.splitlines():
                if not line.strip() or int(line.split()[1]) != owner['pid']:
                    continue
                child_pid = int(line.split()[0])
                try:
                    process_birth(child_pid)
                except ProcessLookupError:
                    # 内核确认已退出的僵尸不再执行业务；活跃或无法确认的子进程仍拒绝。
                    exited_children.append(child_pid)
                else:
                    require(False, 'READY_WORKER_HAS_CHILDREN')
            require((path.lstat().st_dev, path.lstat().st_ino) == (info.st_dev, info.st_ino), 'RECORD_REPLACED')
            intent = dict(schema=1, plan=digest(host.plan), version=version, owner=owner,
                          record=identity, sha256=hashlib.sha256(data).hexdigest(),
                          exited_children=exited_children, task_outcome='NOT_ASSESSED', maintenance_resumed=False)
            require(not receipt.exists(), 'STOP_INTENT_ALREADY_EXISTS')
            write_json(receipt, intent)
            host.owner_check('ready-worker', owner)
            os.kill(owner['pid'], signal.SIGTERM)
        host.wait_exit(owner)
        recovery = MaintenanceRecovery(host.control, host.directory / 'abandoned-ready-admission')
        plan = recovery.plan([identity])
        archived = recovery.apply(expected_plan=digest(plan))
        result = dict(intent, stopped=True, archive=archived)
        write_json(host.directory / 'abandoned-ready-worker-complete.json', result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--expected-maintenance-version', type=int, required=True)
    parser.add_argument('--record', required=True)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    plan = json.loads((directory / 'plan.json').read_text())
    root = Path(plan['root']).resolve()
    if directory.is_relative_to(root):
        raise ValueError('PRIVATE_DIRECTORY_REQUIRED')
    sys.path.insert(0, str(root / 'src'))
    from video_processing.core.deployment_host import HostDeployment
    try:
        result = retire_abandoned_ready_worker(HostDeployment(plan, directory), args.expected_maintenance_version, args.record)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(dict(ok=False, code=getattr(exc, 'code', type(exc).__name__), maintenance_resumed=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

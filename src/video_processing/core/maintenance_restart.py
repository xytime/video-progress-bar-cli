"""接管既有维护的空闲重启；精确旧身份仅用于退休，不伪造安全来源回执。"""
from contextlib import ExitStack
from pathlib import Path
import fcntl
import hashlib
import json
import os
import signal
import stat

from .deployment import require, write_json, read_json, digest, DeploymentDenied
from .deployment_host import HostDeployment
from .deployment_schedules import UI
from .maintenance_recovery import MaintenanceRecovery, boot_identity
from .maintenance_runtime import inspection, code_hash
from .maintenance_restart_probe import verify_owners
from .maintenance_restart_schedules import restore_closed
from .maintenance_restart_freeze import freeze_closed
from ..db.database import PipelineDB


def deferred_records(control, identities, ui_pid):
    """仅保存明确旧 UI 的无锁登记；此时不删除、不认可为 safe。"""
    require(len(identities) == len(set(identities)), 'RECORD_IDS_INVALID')
    records = []
    with control._locked(), ExitStack() as stack:
        for identity in sorted(identities):
            require(len(identity) == 32 and all(c in '0123456789abcdef' for c in identity), 'RECORD_IDS_INVALID')
            path = control.directory / (identity + '.json')
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            stream = stack.enter_context(os.fdopen(fd, 'rb'))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DeploymentDenied('ADMISSION_HELD') from exc
            info, raw = os.fstat(stream.fileno()), stream.read()
            row = json.loads(raw)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'RECORD_NOT_REGULAR')
            require(row.get('id') == identity and row.get('pid') == ui_pid
                    and row.get('role') in {'subprocess', 'legacy-db-write'}, 'DEFERRED_OWNER_INVALID')
            require((path.lstat().st_dev, path.lstat().st_ino) == (info.st_dev, info.st_ino), 'RECORD_REPLACED')
            records.append({'id': identity, 'dev': info.st_dev, 'inode': info.st_ino,
                            'sha256': hashlib.sha256(raw).hexdigest(), 'row': row})
    return records


class RestartHost(HostDeployment):
    """沿用备份、源码采用和新进程检查；仅替换既有维护接管与退休顺序。"""
    def closed(self):
        expected = self.plan['restart']['control']
        state = self.control._read()
        require(state == expected and state['state'] == 'MAINTENANCE', 'MAINTENANCE_CHANGED')
        require(boot_identity() == self.plan['restart']['owners']['boot'], 'BOOT_CHANGED')
        return state

    def ledger_idle(self):
        require(not PipelineDB.maintenance_active_work(self.root / 'output/pipeline.db'), 'UNFINISHED_LEDGER')

    def retirement_check(self, *, frozen=False, partial=False, allow_missing=False, deferred_after_exit=False):
        self.closed()
        self.protections()
        self.sources.baseline()
        if partial:
            self.schedules.files_check(self.plan['schedules'])
        elif frozen:
            self.schedules.frozen(self.plan['schedules'])
        else:
            self.schedules.baseline(self.plan['schedules'])
            self.schedules.require_operational_intent()
        bound = self.plan['restart']['owners']
        observed = verify_owners(self.control, self.root, bound, allow_missing=allow_missing)
        workers = observed['workers']
        ui_pid = bound['workers']['ui']['pid']
        remaining = [r for r in self.plan['restart']['deferred']
                     if (self.control.directory / (r['id'] + '.json')).exists()]
        require(not remaining or 'ui' in workers or deferred_after_exit, 'DEFERRED_REQUIRES_EXIT_ARCHIVE')
        require(deferred_records(self.control, [r['id'] for r in remaining], ui_pid) == remaining,
                'DEFERRED_CHANGED')
        raw = inspection(self.control, retiring_workers=workers)
        require(not raw['active'], 'ACTIVE_WORK')
        expected = [{'code': 'SOURCES_NOT_VERIFIED'}] + [dict(id=r['id'], code='ABANDONED_ADMISSION') for r in remaining]
        require(sorted(raw['unknown'], key=digest) == sorted(expected, key=digest), 'UNEXPECTED_UNKNOWN')
        require(raw['workers'] == workers, 'WORKER_IDENTITY_CHANGED')
        self.ledger_idle()
        return raw

    def preflight(self, step):
        if step in {'baseline', 'freeze'}:
            self.retirement_check(partial=step == 'freeze' and (self.directory / 'freeze-closed.json').exists())
            self.web_readback(maintenance='MAINTENANCE')
        elif step == 'stop':
            path = self.directory / 'stop-intent.json'
            continuing = path.exists()
            if continuing:
                require(read_json(path) == {'plan': digest(self.plan), 'owners': self.plan['restart']['owners']['workers']},
                        'STOP_INTENT_CHANGED')
            self.retirement_check(frozen=True, allow_missing=continuing, deferred_after_exit=continuing)
        elif step == 'resume':
            self.closed()
            self.protections()
            self.sources.final()
            self.backup_valid()
            if not (self.directory / 'restore-closed.json').exists():
                self.safe(started=True)
            self.web_readback(maintenance='MAINTENANCE')
        elif step == 'restore':
            self.final_status()
        else:
            super().preflight(step)

    def action(self, step):
        if step == 'baseline':
            return {'ok': True, 'source_hash': code_hash(), 'runtime': self.web_readback(maintenance='MAINTENANCE'),
                    'restart_only': True, 'old_source_proven': False}
        if step == 'freeze':
            freeze_closed(self)
            return {'ok': True, 'retirement': self.retirement_check(frozen=True)}
        if step == 'resume':
            restore_closed(self)
            self.resume_check()
            write_json(self.directory / 'resume-intent.json', {'plan': digest(self.plan), 'version': self.closed()['version']})
            value = self.control.resume(self.closed()['version'], validated=True)
            return {'ok': True, 'maintenance': value, 'schedules_restored_before_resume': True}
        if step == 'restore':
            return {'ok': True, 'runtime': self.final_status()}
        return super().action(step)

    def resume_check(self):
        self.closed()
        self.protections()
        self.sources.final()
        self.backup_valid()
        self.schedules.restored(self.plan['schedules'])
        self.schedules.require_operational_intent()
        raw = inspection(self.control)
        require(not raw['active'] and raw['unknown'] == [{'code': 'SOURCES_NOT_VERIFIED'}], 'RESUME_NOT_IDLE')
        roles = {'ui', 'auto-pipeline', 'queue-runner', 'ready-supervisor', 'keepalive-watchdog'}
        workers = raw['workers']
        require(roles <= workers.keys(), 'RESUME_ROLES_INCOMPLETE')
        ui = workers['ui']
        expected = (ui['pid'], ui['birth'], code_hash(), str(self.root))
        require(all((workers[role]['pid'], workers[role]['birth'], workers[role]['source_hash'],
                     workers[role]['cwd']) == expected for role in roles), 'RESUME_UI_IDENTITY_MISMATCH')
        old = self.plan['restart']['owners']['workers']['ui']
        require((ui['pid'], ui['birth']) != (old['pid'], old['birth']), 'RESUME_OLD_UI')
        self.ledger_idle()
        self.web_readback(maintenance='MAINTENANCE')

    def archive_deferred(self):
        """必须旧身份退出后才创建归档计划；原记录可被原进程正常清除。"""
        from .maintenance_recovery import process_identity
        restart = self.plan['restart']
        owner = restart['owners']['workers']['ui']
        require(process_identity(owner['pid']) == {'state': 'ABSENT'}, 'OLD_UI_STILL_PRESENT')
        self.closed()
        directory = self.directory / 'deferred-archive'
        recovery = MaintenanceRecovery(self.control, directory)
        if (directory / 'plan.json').exists():
            plan = read_json(directory / 'plan.json')
            require([{k: r[k] for k in ('id', 'dev', 'inode', 'sha256', 'row')} for r in plan['records']]
                    == read_json(self.directory / 'deferred-selected.json'), 'DEFERRED_PLAN_CHANGED')
            return recovery.apply(recover=(directory / 'intent.json').exists(), expected_plan=digest(plan))
        expected = restart['deferred']
        present = [r for r in expected if (self.control.directory / (r['id'] + '.json')).exists()]
        require(deferred_records(self.control, [r['id'] for r in present], owner['pid']) == present, 'DEFERRED_CHANGED')
        write_json(self.directory / 'deferred-selected.json', present)
        write_json(self.directory / 'deferred-already-removed.json', [r for r in expected if r not in present])
        if not present:
            return {'count': 0, 'task_outcome': 'NOT_ASSESSED'}
        plan = recovery.plan([r['id'] for r in present])
        require([{k: r[k] for k in ('id', 'dev', 'inode', 'sha256', 'row')} for r in plan['records']]
                == present, 'DEFERRED_PLAN_CHANGED')
        return recovery.apply(expected_plan=digest(plan))

    def stop(self):
        path = self.directory / 'stop-intent.json'
        owners = self.plan['restart']['owners']['workers']
        intent = {'plan': digest(self.plan), 'owners': owners}
        existed = path.exists()
        if existed:
            require(read_json(path) == intent, 'STOP_INTENT_CHANGED')
        before = self.retirement_check(frozen=True, allow_missing=existed, deferred_after_exit=existed)
        if not existed:
            write_json(path, intent)
        owner = owners['ui']
        if 'ui' in before['workers']:
            require(self.schedules.service(UI)['pid'] == owner['pid'], 'UI_OWNER_CHANGED')
            self.owner_check('ui', owner)
            self.schedules.runner.run(['launchctl', 'bootout', self.schedules.domain + '/' + UI])
            self.wait_exit(owner)
        self.schedules.wait_unloaded(UI)
        self.archive_deferred()
        # 此时旧 UI 已退出，归档完成；只停止无业务在途的已核实独立 worker。
        bound = self.plan['restart']['owners']
        observed = verify_owners(self.control, self.root, bound, allow_missing=True)
        remaining = {r: v for r, v in observed['workers'].items() if r in {'ready-worker', 'wallstreet-worker', 'publishing-recovery-worker'}}
        for role, worker in remaining.items():
            self.retirement_check(frozen=True, allow_missing=True)
            self.owner_check(role, worker)
            os.kill(worker['pid'], signal.SIGTERM)
            self.wait_exit(worker)
        require(not self.safe()['workers'], 'WORKERS_NOT_STOPPED')
        return {'ok': True, 'owners': before['workers'], 'business_task_mutations': False}

    def verify(self, step, result):
        if step == 'baseline':
            self.retirement_check()
        elif step == 'freeze':
            self.retirement_check(frozen=True)
        elif step == 'resume':
            self.schedules.restored(self.plan['schedules'])
            require(self.control.status()['state'] == 'RUNNING', 'RESUME_UNCONFIRMED')
        else:
            super().verify(step, result)

    def reconcile(self, row):
        if row['pending'] == 'freeze':
            self.retirement_check(partial=(self.directory / 'freeze-closed.json').exists())
            return 'NOT_STARTED'
        if row['pending'] == 'stop' and (self.directory / 'stop-intent.json').exists():
            intent = {'plan': digest(self.plan), 'owners': self.plan['restart']['owners']['workers']}
            require(read_json(self.directory / 'stop-intent.json') == intent, 'STOP_INTENT_CHANGED')
            self.retirement_check(frozen=True, allow_missing=True, deferred_after_exit=True)
            return 'NOT_STARTED'
        if row['pending'] == 'resume':
            state = self.control.status()
            if state['state'] == 'MAINTENANCE':
                self.closed()
                return 'NOT_STARTED'
            intent = read_json(self.directory / 'resume-intent.json')
            require(intent == {'plan': digest(self.plan), 'version': self.plan['restart']['control']['version']}
                    and state['version'] == intent['version'] + 1, 'RESUME_IDENTITY_UNKNOWN')
            self.final_status()
            return 'DONE'
        return super().reconcile(row)

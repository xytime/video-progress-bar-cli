"""显式恢复重启前遗留准入，再沿用完整九步部署；不自动解除维护。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def boot_id():
    return subprocess.check_output(['sysctl', '-n', 'kern.boottime'], text=True).strip()


def archive_records(control, expected, destination):
    """调用者已冻结触发源；控制锁、记录锁、PID 缺失和字节绑定全部成立才移动。"""
    from video_processing.core.deployment import require, write_json
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with control._locked():
        state = control._read()
        require(state['state'] == 'MAINTENANCE' and state['version'] == expected['version'], 'MAINTENANCE_CHANGED')
        require(boot_id() == expected['boot'], 'BOOT_CHANGED')
        for item in expected['records']:
            path = control.directory / (item['id'] + '.json')
            target = destination / path.name
            require(not target.exists(), 'ARCHIVE_ALREADY_EXISTS')
            with path.open('rb') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                stat = os.fstat(stream.fileno())
                raw = stream.read()
                require(stat.st_ino == item['inode'] and hashlib.sha256(raw).hexdigest() == item['sha256'], 'RECORD_CHANGED')
                row = json.loads(raw)
                require(row['role'] == 'channel-monitor' and row['at'] < expected['boot_epoch'], 'NOT_PREBOOT_MONITOR')
                try:
                    os.kill(row['pid'], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise RuntimeError('PID_PRESENT')
                require(path.stat().st_ino == stat.st_ino, 'RECORD_REPLACED')
                write_json(destination / (item['id'] + '.intent'), item)
                path.rename(target)
                for directory in (control.directory, destination):
                    fd = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'recover', 'status'])
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--target')
    parser.add_argument('--tested-manifest', type=Path)
    parser.add_argument('--record', action='append', default=[])
    args = parser.parse_args()
    root = args.project_root.resolve()
    sys.path.insert(0, str(root / 'src'))
    from config.settings import settings
    from video_processing.core.deployment import Deployment, require, read_json, write_json
    from video_processing.core.deployment_host import HostDeployment, LOADED_IMPLEMENTATION
    from video_processing.core.deployment_sources import prepare
    from video_processing.core.deployment_schedules import Schedules
    from video_processing.core.maintenance_runtime import inspection, protection_snapshot, code_hash
    from video_processing.core.maintenance import gate
    from video_processing.core.keyword_rollout import verify_loaded

    class RecoveryHost(HostDeployment):
        def recovery_baseline(self):
            self.protections()
            self.sources.baseline()
            self.schedules.baseline(self.plan['schedules'])
            raw = inspection(self.control)
            expected = self.plan['recovery']
            require(raw['state'] == 'MAINTENANCE' and raw['version'] == expected['version'], 'MAINTENANCE_CHANGED')
            require(boot_id() == expected['boot'], 'BOOT_CHANGED')
            require(not raw['active'], 'ACTIVE_WORK')
            require(sorted((r.get('id',''), r['code']) for r in raw['unknown']) ==
                    sorted([('', 'SOURCES_NOT_VERIFIED')] + [(r['id'], 'ABANDONED_ADMISSION') for r in expected['records']]), 'UNEXPECTED_UNKNOWN')
            self.web_readback(maintenance='MAINTENANCE')

        def preflight(self, step):
            if step in {'baseline', 'freeze'}:
                self.recovery_baseline()
            else:
                super().preflight(step)

        def action(self, step):
            if step == 'baseline':
                return {'ok': True, 'source_hash': code_hash(), 'runtime': self.web_readback(maintenance='MAINTENANCE')}
            if step == 'freeze':
                self.schedules.freeze(self.plan['schedules'])
                archive_records(self.control, self.plan['recovery'], self.control.path.parent / ('orphan-archive-' + self.plan['id']))
                return {'ok': True, 'inspection': self.safe()}
            return super().action(step)

    directory = args.directory.resolve()
    own_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        require(root == settings.project_root.resolve() and not directory.is_relative_to(root), 'ROOT_INVALID')
        if args.action == 'plan':
            require(args.target and args.tested_manifest and args.record and not directory.exists(), 'NEW_PLAN_REQUIRED')
            require(len(args.record) == len(set(args.record)) and all(len(r) == 32 and all(c in '0123456789abcdef' for c in r) for r in args.record), 'RECORD_IDS_INVALID')
            directory.mkdir(parents=True, mode=0o700)
            control = gate()
            state = control.status()
            import re
            boot = boot_id()
            epoch = int(re.search(r'sec = (\d+)', boot).group(1))
            records = []
            for identity in args.record:
                path = control.directory / (identity + '.json')
                records.append({'id': identity, 'inode': path.stat().st_ino, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            require(verify_loaded(settings, complete=True), 'KEYWORD_PROFILE_REQUIRED')
            plan = {'schema': 1, 'id': uuid.uuid4().hex, 'root': str(root),
                    'sources': prepare(root, args.target, directory, args.tested_manifest),
                    'schedules': Schedules(root, directory).snapshot(), 'protections': protection_snapshot(),
                    'implementation': LOADED_IMPLEMENTATION, 'recovery_script': own_hash,
                    'keyword_preserve': True, 'keyword_profile_before': settings.topic_rollout_snapshot(),
                    'recovery': {'version': state['version'], 'boot': boot, 'boot_epoch': epoch, 'records': records}}
            RecoveryHost(plan, directory).recovery_baseline()
            write_json(directory / 'plan.json', plan)
            print(json.dumps({'planned': True, 'directory': str(directory)}))
            return
        plan = read_json(directory / 'plan.json')
        require(plan['recovery_script'] == own_hash, 'RECOVERY_IMPLEMENTATION_CHANGED')
        deploy = Deployment(plan, directory, None if args.action == 'status' else RecoveryHost(plan, directory))
        print(json.dumps(deploy.status() if args.action == 'status' else deploy.run(recover=args.action == 'recover')))
    except Exception as exc:
        print(json.dumps({'ok': False, 'code': getattr(exc, 'code', type(exc).__name__), 'detail': str(exc)}))
        raise SystemExit(2)


if __name__ == '__main__':
    main()

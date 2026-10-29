"""接管既有 MAINTENANCE 的空闲重启；plan/apply/recover 均绑定精确现场。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def implementation():
    directory = Path(__file__).resolve().parents[1]
    names = ['scripts/recover_maintenance_restart.py'] + [
        'src/video_processing/core/' + name + '.py' for name in
        ('maintenance_restart', 'maintenance_restart_probe', 'maintenance_restart_schedules',
         'maintenance_restart_freeze', 'maintenance_recovery')]
    return {n: hashlib.sha256((directory / n).read_bytes()).hexdigest() for n in names}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'recover', 'status'])
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--target')
    parser.add_argument('--tested-manifest', type=Path)
    parser.add_argument('--deferred-record', action='append', default=[])
    parser.add_argument('--expected-plan')
    args = parser.parse_args(argv)
    from config.settings import settings
    from video_processing.core.deployment import Deployment, require, read_json, write_json, digest
    from video_processing.core.deployment_host import LOADED_IMPLEMENTATION
    from video_processing.core.deployment_sources import prepare
    from video_processing.core.deployment_schedules import Schedules, UI
    from video_processing.core.maintenance import gate
    from video_processing.core.maintenance_runtime import protection_snapshot
    from video_processing.core.maintenance_restart import RestartHost, deferred_records
    from video_processing.core.maintenance_restart_probe import capture_owners
    from video_processing.core.keyword_rollout import verify_loaded
    directory = args.directory.resolve()
    try:
        root = settings.project_root.resolve()
        require(not directory.is_relative_to(root), 'PRIVATE_DIRECTORY_REQUIRED')
        if args.action == 'plan':
            require(args.target and args.tested_manifest and not directory.exists(), 'NEW_PLAN_REQUIRED')
            control = gate()
            state = control._read()
            require(state['state'] == 'MAINTENANCE', 'MAINTENANCE_REQUIRED')
            owners = capture_owners(control, root)
            records = deferred_records(control, args.deferred_record, owners['workers']['ui']['pid'])
            require(verify_loaded(settings, complete=True), 'KEYWORD_PROFILE_REQUIRED')
            directory.mkdir(parents=True, mode=0o700)
            schedules = Schedules(root, directory).snapshot()
            ui = next(r for r in schedules['launchd'] if r['label'] == UI)
            require(ui['loaded'] and not ui['disabled'], 'UI_ORIGINAL_STATE_UNSUPPORTED')
            plan = {'schema': 1, 'id': uuid.uuid4().hex, 'root': str(root),
                    'sources': prepare(root, args.target, directory, args.tested_manifest),
                    'schedules': schedules, 'protections': protection_snapshot(),
                    'implementation': LOADED_IMPLEMENTATION, 'restart_implementation': implementation(),
                    'keyword_preserve': True, 'keyword_profile_before': settings.topic_rollout_snapshot(),
                    'restart': {'control': state, 'owners': owners, 'deferred': records}}
            RestartHost(plan, directory).preflight('baseline')
            write_json(directory / 'plan.json', plan)
            result = {'planned': True, 'plan_sha256': digest(plan), 'directory': str(directory)}
        else:
            plan = read_json(directory / 'plan.json')
            require(plan['restart_implementation'] == implementation(), 'RESTART_IMPLEMENTATION_CHANGED')
            require(args.action == 'status' or args.expected_plan == digest(plan), 'PLAN_CHANGED')
            deploy = Deployment(plan, directory, None if args.action == 'status' else RestartHost(plan, directory))
            result = deploy.status() if args.action == 'status' else deploy.run(recover=args.action == 'recover')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'code': getattr(exc, 'code', type(exc).__name__),
                          'directory': str(directory), 'automatic_resume': False}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

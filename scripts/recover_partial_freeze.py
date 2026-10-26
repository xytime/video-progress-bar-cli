"""接续仅关闭维护闸门、尚未改动调度的原生部署；不修改闸门或部署日志。

可从隔离且已测的维护工具副本执行，依照私有计划加载原项目的原生适配器；
因此恢复旧计划不需要先改线上源码、实现指纹、目标或账本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| partial-freeze-v1 | 2026-10-26 | Codex | 维护版本/计划/身份/源码/调度/账本闭锁，完成真实冻结后交回原生recover。 |
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time


def complete_partial_freeze(host, expected_version):
    """只支持准确的闸门关闭阶段；真正冻结并验证后，原引擎才可确认该步骤。"""
    from video_processing.core.deployment import Deployment, require, project_lock, write_json
    from video_processing.core.deployment_host import retirement_owners
    from video_processing.core.maintenance_runtime import inspection, code_hash
    from video_processing.db.database import PipelineDB

    def control_check():
        state = host.control.status()
        require(state['state'] == 'MAINTENANCE' and state['version'] == expected_version
                and state.get('reason') == '部署 ' + host.plan['id'], 'PARTIAL_FREEZE_CONTROL_DRIFT')
        require(not state['active'] and not state['unknown'], 'PARTIAL_FREEZE_ACTIVE_OR_UNKNOWN')
        return state

    with project_lock(host.lock_path):
        row = Deployment(host.plan, host.directory, host).status()
        require(row['done'] == ['baseline'] and row['pending'] == 'freeze'
                and row['state'] in {'FAILED', 'RUNNING'}
                and row.get('error') in {None, 'SCHEDULE_DAEMON_NOT_DRAINED'}, 'PARTIAL_FREEZE_STAGE_INVALID')
        state = control_check()
        host.protections()
        host.sources.baseline()
        host.schedules.baseline(host.plan['schedules'])
        host.schedules.require_operational_intent()
        owners = retirement_owners(host.plan.get('retirement'))
        raw = inspection(host.control, retiring_workers=owners)
        require(raw['version'] == expected_version and not raw['active']
                and raw['unknown'] == [{'code': 'SOURCES_NOT_VERIFIED'}], 'PARTIAL_FREEZE_NOT_IDLE')
        require(owners.get('ui') and raw['workers'] == owners, 'PARTIAL_FREEZE_OWNER_DRIFT')
        require(not PipelineDB.maintenance_active_work(host.root / 'output/pipeline.db'),
                'PARTIAL_FREEZE_UNFINISHED_LEDGER')
        intent = {'schema': 1, 'plan_id': host.plan['id'], 'version': expected_version,
                  'source_hash': code_hash(), 'at': time.time(), 'state': 'VERIFIED_UNFROZEN',
                  'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'workers': raw['workers'], 'control_at': state['at']}
        write_json(host.directory / 'partial-freeze-recovery.json', intent)
        control_check()
        # 原生freeze再次校验原调度、Bot身份及无在途，按原计划冻结，绝不自行解锁/开闸。
        host.schedules.freeze(host.plan['schedules'])
        control_check()
        result = {'ok': True, 'inspection': host.safe()}
        host.verify('freeze', result)
        control_check()
        write_json(host.directory / 'freeze.json', result)
        write_json(host.directory / 'partial-freeze-recovery.json',
                   dict(intent, state='FROZEN_VERIFIED', completed_at=time.time()))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--expected-maintenance-version', required=True, type=int)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    # 仅入口加载计划绑定的项目；HostDeployment仍验证真实settings根与原实现指纹。
    plan = json.loads((directory / 'plan.json').read_text())
    root = Path(plan['root']).resolve()
    if directory.is_relative_to(root):
        raise ValueError('PRIVATE_DIRECTORY_REQUIRED')
    sys.path.insert(0, str(root / 'src'))
    from video_processing.core.deployment import Deployment
    from video_processing.core.deployment_host import HostDeployment
    try:
        host = HostDeployment(plan, directory)
        complete_partial_freeze(host, args.expected_maintenance_version)
        # 不改pending/done：由原恢复器重新核验冻结后置条件，再顺序备份、采用、启动及恢复。
        result = Deployment(plan, directory, host).run(recover=True)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'code': getattr(exc, 'code', type(exc).__name__),
                          'directory': str(directory), 'recovery': '保持现场；先只读核实实际阶段，不自动开闸或重复冻结。'},
                         ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

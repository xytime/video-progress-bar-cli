"""维护中逐项恢复已绑定的原调度；每步可核对，全部完成前不开闸。"""
from pathlib import Path
import plistlib
import os

from .deployment import require, write_json, read_json, digest
from .deployment_sources import sha
from .deployment_schedules import UI


def _closed_idle(host):
    host.closed()
    state = host.control.status()
    require(not state['active'] and not state['unknown'], 'RESTORE_NOT_IDLE')
    host.ledger_idle()


def restore_closed(host):
    """只接续本计划冻结态/目标态；未知定义、额外来源或 cron 漂移拒绝。"""
    schedules, plan = host.schedules, host.plan['schedules']
    receipt = host.directory / 'restore-closed.json'
    identity = digest(plan)
    _closed_idle(host)
    schedules.files_check(plan)
    if receipt.exists():
        journal = read_json(receipt)
        require(journal.get('plan') == identity, 'RESTORE_PLAN_CHANGED')
    else:
        schedules.frozen(plan, ui_started=True)
        journal = {'schema': 1, 'plan': identity, 'done': [], 'pending': None}
        write_json(receipt, journal)
    for row in plan['launchd']:
        _closed_idle(host)
        schedules.files_check(plan)
        label = row['label']
        original = plistlib.loads((schedules.directory / 'plists' / (label + '.plist')).read_bytes())
        config = original if label == UI else schedules.restored_definition(original)
        seen = schedules.service(label)
        if seen['loaded']:
            require(row['loaded'] and plistlib.loads(Path(seen['path']).read_bytes()) == config,
                    'RESTORE_LOADED_DEFINITION_UNKNOWN')
        require(label != UI or seen['loaded'], 'RESTORE_UI_MISSING')
        disabled = schedules.disabled().get(label, row['disabled'])
        if label in journal['done']:
            require(seen['loaded'] == row['loaded'] and disabled == row['disabled'], 'RESTORE_COMPLETED_DRIFT')
            continue
        require(journal['pending'] in {None, label}, 'RESTORE_ORDER_INVALID')
        journal['pending'] = label
        write_json(receipt, journal)
        if row['loaded'] and not seen['loaded']:
            folder = schedules.runtime_directory / sha(str(host.directory).encode())[:20]
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = folder / (label + '.restore.plist')
            payload = plistlib.dumps(config)
            if path.exists():
                require(path.read_bytes() == payload, 'RESTORE_PAYLOAD_DRIFT')
            else:
                with open(path, 'xb', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                descriptor = os.open(folder, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            for key in ('StandardOutPath', 'StandardErrorPath'):
                if config.get(key):
                    Path(config[key]).parent.mkdir(parents=True, exist_ok=True)
            if not row['disabled']:
                schedules.runner.run(['launchctl', 'enable', schedules.domain + '/' + label])
            schedules.runner.run(['launchctl', 'bootstrap', schedules.domain, str(path)])
        schedules.runner.run(['launchctl', 'disable' if row['disabled'] else 'enable', schedules.domain + '/' + label])
        seen = schedules.service(label)
        require(seen['loaded'] == row['loaded'] and schedules.disabled().get(label, row['disabled']) == row['disabled'],
                'RESTORE_ITEM_UNCONFIRMED')
        journal['done'].append(label)
        journal['pending'] = None
        write_json(receipt, journal)
    _closed_idle(host)
    require(sha(schedules.cron()) in {plan['cron'], plan['frozen_cron']}, 'RESTORE_CRON_DRIFT')
    schedules.runner.run(['crontab', '-'], data=(schedules.directory / 'cron.original').read_bytes())
    schedules.restored(plan)
    schedules.record_operational_intent(plan)
    journal['complete'] = True
    write_json(receipt, journal)

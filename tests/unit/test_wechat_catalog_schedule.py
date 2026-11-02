"""商品同步 cron 的独立追加、备份和维护/CAS 反例。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 使用原调度替身验证新块，不操作真实 crontab/launchd。 |
"""
import pytest
from tests.unit.test_deployment_schedules import scheduling, cruise_scheduling
from video_processing.core.deployment import DeploymentDenied
from video_processing.core.deployment_sources import sha


def test_catalog_cron_appends_preserves_other_bytes_and_intent(cruise_scheduling):
    schedules, commands, original, state, intent=cruise_scheduling
    report=schedules.install_catalog_sync(sha(original))
    assert commands.crontab.startswith(original)
    assert commands.crontab.count(b'35 7 * * * ')==1
    assert b'/scripts/sync_wechat_product_catalog.py' in commands.crontab
    assert b'--retry' not in commands.crontab
    assert report['daily_local_time']=='07:35' and report['enabled']
    assert (schedules.directory/'cron.before').read_bytes()==original
    assert (schedules.directory/'operational-intent.before.json').read_bytes()==intent
    schedules.require_operational_intent()
    assert state['state']=='MAINTENANCE'


@pytest.mark.parametrize('fault',['running','active','unknown','drift','duplicate'])
def test_catalog_cron_denies_unsafe_mutation(cruise_scheduling,fault):
    schedules,commands,original,state,intent=cruise_scheduling
    expected=sha(original)
    if fault=='running': state['state']='RUNNING'
    elif fault in {'active','unknown'}: state[fault].append({'pid':123})
    elif fault=='drift': expected='wrong'
    else:
        commands.crontab+=b'# Video Pipeline catalog-sync (managed)\n'
    before=commands.crontab
    with pytest.raises(DeploymentDenied): schedules.install_catalog_sync(expected)
    assert commands.crontab==before
    assert (schedules.runtime_directory/'operational-intent.json').read_bytes()==intent

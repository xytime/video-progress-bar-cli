"""真实维护闸门/日志/调度模型验证部分冻结接续；不访问生产或真实launchd。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| partial-freeze-v1 | 2026-10-26 | Codex | 版本/身份/在途/账本/调度漂移、崩溃及真实冻结后原recover判定。 |
"""
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace, MethodType

import pytest

from scripts.recover_partial_freeze import complete_partial_freeze
from tests.unit.test_deployment_schedules import scheduling  # noqa: F401
from video_processing.core import deployment, deployment_host, maintenance_runtime
from video_processing.core.deployment import Deployment, DeploymentDenied, write_json
from video_processing.core.deployment_sources import sha


@pytest.fixture
def partial(scheduling, isolated_running_maintenance, monkeypatch):
    schedules, commands, schedule_plan = scheduling
    root, directory = schedules.root, schedules.directory
    (root/'output').mkdir()
    with sqlite3.connect(root/'output/pipeline.db') as c:
        c.execute('CREATE TABLE processed_videos(id INTEGER,status TEXT)')
        c.execute("INSERT INTO processed_videos VALUES(1,'PENDING')")
    source = root/'source.txt'; source.write_text('original-source')
    policy = root/'policy.txt'; policy.write_text('original-policy')
    owner = dict(role='ui',pid=123,birth='identity',source_hash='a'*64)
    proof = directory/'previous';proof.mkdir();write_json(proof/'owner.json',owner)
    plan = dict(schema=1,id='partial-plan',root=str(root),schedules=schedule_plan,
                retirement=dict(directory=str(proof),owners={'ui':owner},files={'owner.json':sha((proof/'owner.json').read_bytes())}))
    control = isolated_running_maintenance
    control.enter('部署 '+plan['id'])
    injection = dict(unknown=[{'code':'SOURCES_NOT_VERIFIED'}],workers={'ui':owner})
    def observe(control, **kwargs):
        return dict(control.status(),unknown=injection['unknown'],workers=injection['workers'])
    monkeypatch.setattr(maintenance_runtime,'inspection',observe)
    def baseline():
        deployment.require(source.read_text()=='original-source','SOURCE_BASELINE_DRIFT')
    def protections():
        deployment.require(policy.read_text()=='original-policy','PROTECTION_DRIFT')
    host = SimpleNamespace(plan=plan,root=root,directory=directory,control=control,schedules=schedules,
                           lock_path=root/'output/deploy.lock',sources=SimpleNamespace(baseline=baseline),protections=protections)
    def safe():
        schedules.frozen(schedule_plan)
        result=observe(control)
        deployment.require(not result['active'] and result['unknown']==[{'code':'SOURCES_NOT_VERIFIED'}], 'MAINTENANCE_NOT_IDLE')
        return dict(result,unknown=[],safe=True)
    host.safe=safe
    host.verify=lambda step,result: safe()
    host.reconcile=MethodType(deployment_host.HostDeployment.reconcile,host)
    row=dict(schema=1,plan=deployment.digest(plan),done=['baseline'],pending='freeze',state='FAILED',error='SCHEDULE_DAEMON_NOT_DRAINED')
    write_json(directory/'journal.json',row)
    return SimpleNamespace(host=host,commands=commands,source=source,policy=policy,injection=injection,
                           version=control.status()['version'],row=row)


def mutations(commands):
    return [v for v in commands.calls if v[:2]==['crontab','-'] or len(v)>1 and v[1] in {'disable','enable','bootout','bootstrap'}]


def test_native_freeze_completed_without_opening_gate_or_forging_journal(partial):
    p=partial;h=p.host;before=h.control.path.read_bytes()
    complete_partial_freeze(h,p.version)
    assert h.control.path.read_bytes()==before
    assert Deployment(h.plan,h.directory,h).status()==p.row
    assert json.loads((h.directory/'freeze.json').read_text())['inspection']['safe']
    assert json.loads((h.directory/'partial-freeze-recovery.json').read_text())['state']=='FROZEN_VERIFIED'
    assert h.reconcile(p.row)=='DONE'  # 仍由原生恢复器根据真实后置条件决定。
    assert mutations(p.commands)


@pytest.mark.parametrize('fault',['version','reason','running','active','unknown','owner','source','schedule','policy','ledger','journal'])
def test_any_unverified_condition_refuses_before_schedule_mutation(partial,fault):
    p=partial;h=p.host;version=p.version
    if fault=='version':version+=1
    elif fault=='reason':
        h.control.resume(p.version,validated=True);h.control.enter('另一维护操作');version=h.control.status()['version']
    elif fault=='running':h.control.resume(p.version,validated=True)
    elif fault=='unknown':p.injection['unknown'].insert(0,{'code':'UNREGISTERED_PROCESS','pid':999})
    elif fault=='owner':p.injection['workers']={'ui':dict(p.injection['workers']['ui'],birth='reused')}
    elif fault=='source':p.source.write_text('changed')
    elif fault=='schedule':p.commands.crontab+=b'concurrent-other-edit\n'
    elif fault=='policy':p.policy.write_text('changed')
    elif fault=='ledger':
        with sqlite3.connect(h.root/'output/pipeline.db') as c:c.execute("UPDATE processed_videos SET status='PUBLISHING'")
    elif fault=='journal':write_json(h.directory/'journal.json',dict(p.row,pending='stop',done=['baseline','freeze']))
    if fault=='active':
        # 真实存活票据，即使维护已关闭，仍属于未排空在途。
        h.control.resume(p.version,validated=True)
        with h.control.admit('test','active') as ticket:
            ticket.start();h.control.enter('部署 '+h.plan['id']);version=h.control.status()['version']
            with pytest.raises(DeploymentDenied):complete_partial_freeze(h,version)
    else:
        with pytest.raises(DeploymentDenied):complete_partial_freeze(h,version)
    assert not mutations(p.commands)
    assert not (h.directory/'freeze.json').exists()


def test_cas_version_change_after_intent_does_not_freeze(partial,monkeypatch):
    p=partial;h=p.host;original=deployment.write_json
    def write(path,value):
        original(path,value)
        if path.name=='partial-freeze-recovery.json':
            h.control.resume(p.version,validated=True);h.control.enter('部署 '+h.plan['id'])
    monkeypatch.setattr(deployment,'write_json',write)
    with pytest.raises(DeploymentDenied,match='CONTROL_DRIFT'):complete_partial_freeze(h,p.version)
    assert not mutations(p.commands)


def test_failure_after_real_freeze_preserves_scene_and_original_recover_can_reconcile(partial):
    p=partial;h=p.host;verify=h.verify
    def refused(*args):raise DeploymentDenied('INJECTED_AFTER_FREEZE')
    h.verify=refused
    with pytest.raises(DeploymentDenied,match='INJECTED_AFTER_FREEZE'):complete_partial_freeze(h,p.version)
    assert h.control.status()['state']=='MAINTENANCE'
    assert not (h.directory/'freeze.json').exists()
    assert Deployment(h.plan,h.directory,h).status()==p.row
    h.verify=verify
    assert h.reconcile(p.row)=='DONE'


def test_repeated_partial_entry_never_repeats_already_frozen_schedules(partial):
    p=partial;complete_partial_freeze(p.host,p.version);count=len(mutations(p.commands))
    with pytest.raises(DeploymentDenied):complete_partial_freeze(p.host,p.version)
    assert len(mutations(p.commands))==count


@pytest.mark.parametrize('extra,code',[([], 'MAINTENANCE_VERSION_REQUIRED'),
                                    (['--expected-maintenance-version','1'],'PARTIAL_FREEZE_STAGE_INVALID')])
def test_real_cli_routes_explicit_recovery_and_refuses_new_plan(tmp_path,extra,code):
    from config.settings import settings
    directory=tmp_path/'private';directory.mkdir()
    write_json(directory/'plan.json',dict(schema=1,id='new-plan',root=str(settings.project_root),
                                        sources={},schedules={},implementation=deployment_host.LOADED_IMPLEMENTATION))
    process=subprocess.run([sys.executable,str(settings.project_root/'scripts/deployment_control.py'),
                            'recover-partial-freeze','--directory',str(directory),*extra],capture_output=True,text=True)
    assert process.returncode==2
    assert json.loads(process.stdout)['code']==code
    assert not (directory/'journal.json').exists()

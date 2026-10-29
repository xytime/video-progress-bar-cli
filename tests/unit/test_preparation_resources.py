"""真实 flock/子孙 FD 与低负载资源让行验收；仅临时目录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 资源互斥、进程崩溃存活锁、可靠检查点与关闭清理。 |
"""
import json
from pathlib import Path
import subprocess
import sys
import time
import pytest
from video_processing.core import preparation_resources as resources
from video_processing.core.ffmpeg_slot import _BASE_POPEN


def until(predicate, timeout=4):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('synthetic worker did not reach expected boundary')


def spawn(cohort, key, owner, code, *args):
    options = cohort.options(key, owner, dict(stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
    return _BASE_POPEN([sys.executable, '-c', code, *map(str,args)], **options)


def test_parent_exit_keeps_fence_task_source_and_heavy_until_grandchild_exit(tmp_path):
    marker = tmp_path/'started'
    cohort = resources.PreparationCohort(tmp_path)
    code = '''import os, subprocess, sys
from pathlib import Path
from video_processing.core.preparation_resources import setup_execution_context,execution_context
s=setup_execution_context()
with execution_context(s.output,s.key,s.owner):
 s.switch('heavy','synthetic')
 p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(1.2)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 Path(sys.argv[1]).write_text(str(p.pid))
 os._exit(0)
'''
    process = spawn(cohort, 'alpha:0', 'a'*32, code, marker)
    cohort.close()
    until(marker.exists)
    _, errors = process.communicate(timeout=3)
    assert process.returncode == 0, errors
    paths = [tmp_path/'pipeline.lock',tmp_path/'task_locks/alpha.lock',
             tmp_path/'source_locks/alpha.lock',tmp_path/'preparation_resources/heavy.lock']
    for path in paths:
        with pytest.raises(BlockingIOError):
            resources.DescriptorLease(path,label='probe')
    time.sleep(1.3)
    for path in paths:
        lease=resources.DescriptorLease(path,label='probe'); lease.close()


def test_network_overlaps_heavy_but_two_heavy_never_overlap(tmp_path):
    cohort=resources.PreparationCohort(tmp_path)
    code='''import sys,time
from pathlib import Path
from video_processing.core.preparation_resources import setup_execution_context,execution_context
s=setup_execution_context()
with execution_context(s.output,s.key,s.owner):
 for kind,duration in [v.split(':') for v in sys.argv[2:]]:
  s.switch(kind,'synthetic')
  with Path(sys.argv[1]).open('a') as f: f.write(kind+' start '+str(time.monotonic())+'\\n')
  time.sleep(float(duration))
  with Path(sys.argv[1]).open('a') as f: f.write(kind+' end '+str(time.monotonic())+'\\n')
s.close()
'''
    first=tmp_path/'one'; second=tmp_path/'two'
    one=spawn(cohort,'alpha:0','a'*32,code,first,'heavy:.7')
    until(first.exists)
    two=spawn(cohort,'beta:0','b'*32,code,second,'network:.1','heavy:.05')
    for proc in (one,two):
        _, errors=proc.communicate(timeout=5); assert proc.returncode == 0,errors
    cohort.close()
    a=[line.split() for line in first.read_text().splitlines()]
    b=[line.split() for line in second.read_text().splitlines()]
    assert float(b[0][2]) < float(a[1][2])
    assert float(b[2][2]) >= float(a[1][2])
    assert not list((tmp_path/'preparation_resources').glob('*.wait'))


def test_nested_network_releases_outer_heavy_and_restores(tmp_path):
    scope=resources.ExecutionScope(tmp_path,'alpha:0','a'*32,[])
    token=resources._CURRENT.set(scope)
    try:
        with resources.resource_stage('heavy','outer'):
            with resources.resource_stage('network','translation'):
                lease=resources.DescriptorLease(tmp_path/'preparation_resources/heavy.lock',label='probe')
                lease.close()
                assert scope.lane_name == 'network'
            assert scope.lane_name == 'heavy'
        assert scope.lane is None
    finally:
        resources._CURRENT.reset(token); scope.close()


def test_validated_checkpoint_yields_only_for_live_competitor_and_preserves_cumulative(tmp_path):
    scope=resources.ExecutionScope(tmp_path,'alpha:0','a'*32,[])
    token=resources._CURRENT.set(scope)
    try:
        scope.switch('heavy','ocr')
        scope.lane_started-=301
        resources.checkpoint_boundary('complete-prefix-v1')  # no competitor, no churn
        ticket=resources.DescriptorLease(tmp_path/'preparation_resources/000.wait',label='heavy',owner='b'*32)
        try:
            with pytest.raises(resources.PreparationYielded):
                resources.checkpoint_boundary('complete-prefix-v1')
        finally:
            ticket.close()
        receipt=json.loads(next((tmp_path/'preparation_checkpoints').glob('*.json')).read_text())
        assert receipt['cumulative_heavy_seconds'] >= 301
        assert receipt['cumulative_heavy_seconds'] < 305
        assert issubclass(resources.PreparationYielded,BaseException)
        assert not issubclass(resources.PreparationYielded,Exception)
        with pytest.raises(ValueError):
            resources.checkpoint_boundary('not-complete',validated=False)
    finally:
        resources._CURRENT.reset(token); scope.close()


def test_context_close_clears_global_and_forged_fd_rejected(tmp_path,monkeypatch):
    scope=resources.ExecutionScope(tmp_path,'alpha:0','a'*32,[])
    monkeypatch.setattr(resources,'_PROCESS_SCOPE',scope)
    scope.close(); scope.close()
    assert resources.active_context() is None
    path=tmp_path/'pipeline.lock'; path.write_text('{}')
    with path.open('r+') as stream:
        with pytest.raises(ValueError,match='not held'):
            resources.setup_execution_context(dict(protocol=1,output=str(tmp_path),key='alpha:0',owner='a'*32,
                descriptors=[dict(path=str(path),fd=stream.fileno())]))


@pytest.mark.parametrize('other_key',['alpha:0','alpha:1'])
def test_task_and_source_lease_reject_concurrent_worker(tmp_path,other_key):
    cohort=resources.PreparationCohort(tmp_path)
    code='''import sys,time
from pathlib import Path
from video_processing.core.preparation_resources import setup_execution_context,execution_context,PreparationBusy
s=setup_execution_context()
try:
 with execution_context(s.output,s.key,s.owner):
  Path(sys.argv[1]).write_text('executing')
  time.sleep(float(sys.argv[2]))
except PreparationBusy:
 Path(sys.argv[1]).write_text('waiting')
finally:
 s.close()
'''
    first=tmp_path/'first'; second=tmp_path/'second'
    one=spawn(cohort,'alpha:0','a'*32,code,first,'.7')
    until(first.exists)
    two=spawn(cohort,other_key,'b'*32,code,second,'0')
    for proc in (one,two):
        _,errors=proc.communicate(timeout=4); assert proc.returncode == 0,errors
    cohort.close()
    assert first.read_text() == 'executing'
    assert second.read_text() == 'waiting'


def test_resource_wait_state_reports_live_elapsed_wait(tmp_path):
    cohort=resources.PreparationCohort(tmp_path)
    held=resources.DescriptorLease(tmp_path/'preparation_resources/heavy.lock',label='heavy',owner='a'*32)
    marker=tmp_path/'wait-state'
    code='''import json,sys,threading,time
from pathlib import Path
from video_processing.core.preparation_resources import setup_execution_context,execution_context,wait_state
s=setup_execution_context()
def watch():
 while not wait_state()['waiting']: time.sleep(.01)
 time.sleep(.05)
 Path(sys.argv[1]).write_text(json.dumps(wait_state()))
t=threading.Thread(target=watch); t.start()
with execution_context(s.output,s.key,s.owner): s.switch('heavy','synthetic')
t.join(); s.close()
'''
    child=spawn(cohort,'beta:0','b'*32,code,marker)
    try:
        until(marker.exists)
        state=json.loads(marker.read_text())
        assert state['waiting'] and state['seconds'] >= .04
    finally:
        held.close()
        _,errors=child.communicate(timeout=4); cohort.close()
    assert child.returncode == 0,errors

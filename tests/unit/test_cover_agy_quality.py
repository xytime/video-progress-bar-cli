"""真实子进程超时清理，以及质量回执失败关闭。"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from video_processing.utils import cover_agy as agy


def test_timeout_kills_child_group_and_does_not_echo_command(tmp_path):
    marker = tmp_path/'heartbeat'
    child = f"from pathlib import Path; import time\np=Path({str(marker)!r})\nwhile True:\n p.write_text(str(time.time())); time.sleep(.02)"
    parent = f"import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
    with pytest.raises(RuntimeError, match='PROCESS_TIMEOUT') as exc:
        agy.run_process([sys.executable, '-c', parent], cwd=tmp_path, timeout=.4, env={})
    assert parent not in str(exc.value)
    assert marker.exists()
    last = marker.read_text()
    time.sleep(.1)
    assert marker.read_text() == last


def test_cli_strips_credentials_and_rejects_failure_envelope(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(agy, 'build_subprocess_env', lambda **k: {'OPENAI_API_KEY':'test','GEMINI_API_KEY':'test','PATH':'/usr/bin'})
    def process(command, **kw):
        captured.update(kw)
        return subprocess.CompletedProcess(command, 0, '{"status":"ERROR"}', '')
    monkeypatch.setattr(agy, 'run_process', process)
    with pytest.raises(RuntimeError, match='FAILED_ENVELOPE'):
        agy.run_cli(['agy'], cwd=tmp_path, timeout=1)
    assert captured['env'] == {'PATH':'/usr/bin'}


@pytest.mark.parametrize('change', [{'decision':'UNCERTAIN'}, {'image_inspected':False}, {'adequate_detail':False}, {'observed_content':''}, {'composition_complete':'true'}])
def test_quality_requires_complete_positive_evidence(change):
    r = dict(decision='PASS', image_inspected=True, subject_relevant=True,
        composition_complete=True, adequate_detail=True, no_severe_artifacts=True,
        observed_content='gold treasury room', reason='usable')
    assert agy.valid_quality(r)
    r.update(change)
    assert not agy.valid_quality(r)


def test_review_is_independent_and_requires_structured_output(tmp_path, monkeypatch):
    image=tmp_path/'candidate.png'; image.write_bytes(b'image')
    commands=[]
    def cli(command, **kwargs):
        commands.append(command)
        return {'response': 'PASS'}
    monkeypatch.setattr(agy, 'run_cli', cli)
    with pytest.raises(RuntimeError, match='MISSING_STRUCTURED_OUTPUT'):
        agy.review_image(image, subject={'title':'treasury'}, agy_bin='agy', model='gemini-test', timeout=30)
    assert commands[0][0]=='agy'
    assert '--continue' not in commands[0]
    assert 'text presence are NOT rejection criteria' in commands[0][-1]


def test_nested_worker_gets_time_to_kill_own_cli_group(tmp_path):
    marker=tmp_path/'nested-heartbeat'
    src=Path(agy.__file__).resolve().parents[2]
    child=f"import signal,time\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\np=Path({str(marker)!r})\nwhile True:\n p.write_text(str(time.time()));time.sleep(.02)"
    parent=(f"import sys,signal\nfrom pathlib import Path\nsys.path.insert(0,{str(src)!r})\n"
            "from video_processing.utils.cover_agy import run_process\n"
            "def interrupted(*a): raise RuntimeError('WORKER_INTERRUPTED')\n"
            "signal.signal(signal.SIGTERM,interrupted)\n"
            f"run_process([sys.executable,'-c',{child!r}],cwd=Path({str(tmp_path)!r}),timeout=60,env={{}})\n")
    with pytest.raises(RuntimeError,match='PROCESS_TIMEOUT'):
        agy.run_process([sys.executable,'-c',parent],cwd=tmp_path,timeout=1,env={},cleanup_grace=15)
    assert marker.exists()
    before=marker.read_text();time.sleep(.1)
    assert marker.read_text()==before

"""断流修复：共享熔断、采集不调用翻译、音频备用仍经过审查。"""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from video_processing.utils.provider_circuit import ProviderCircuit
from video_processing.utils.monitor_translation_queue import cached_or_enqueue, drain
from video_processing.utils.source_audio_preflight import transcript


def test_provider_outage_shared_across_instances_and_probe_reopens(tmp_path):
    path = tmp_path / 'health.json'
    a = ProviderCircuit(path, cooldown=100)
    a.record(False, now=10)
    b = ProviderCircuit(path, cooldown=100)
    assert not b.blocked(now=11)
    b.record(False, now=20)
    assert a.blocked(now=119)
    assert not a.blocked(now=120)
    a.record(False, now=121)
    assert b.blocked(now=220)
    b.record(True, now=222)
    assert not a.blocked(now=223)


def test_title_intake_never_calls_network_and_preserves_completed_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('network')))
    assert cached_or_enqueue(tmp_path, 'An English title') == 'An English title'
    path = next(tmp_path.glob('*.json'))
    row = json.loads(path.read_text()); row['translation'] = '中文标题'
    path.write_text(json.dumps(row))
    assert cached_or_enqueue(tmp_path, 'An English title') == '中文标题'
    assert len(list(tmp_path.glob('*.json'))) == 1


def test_translation_timeout_shared_cooldown(tmp_path, monkeypatch):
    calls = []
    for title in ['first', 'second']:
        cached_or_enqueue(tmp_path, title)
    def timeout(*a, **kw):
        calls.append(kw['timeout'])
        raise subprocess.TimeoutExpired(a[0], kw['timeout'])
    monkeypatch.setattr(subprocess, 'run', timeout)
    assert drain(tmp_path, timeout=7) == 0
    assert drain(tmp_path, timeout=7) == 0
    assert calls == [7]


def test_audio_unknown_duration_never_downloads(tmp_path):
    settings = SimpleNamespace(source_audio_max_duration_seconds=1800)
    import pytest
    with pytest.raises(ValueError, match='AUDIO_DURATION_UNVERIFIED'):
        transcript({'youtube_id': 'unknown'}, tmp_path, lambda *a, **kw: pytest.fail('download'), 'python', settings)


def test_audio_retry_budget_preserved_across_runs(tmp_path):
    import hashlib
    import pytest
    model = tmp_path / 'base.pt'; model.write_bytes(b'model')
    directory = tmp_path / 'source_audio_preflight' / hashlib.sha256(b'known').hexdigest()
    directory.mkdir(parents=True)
    (directory / 'attempts.json').write_text('{"count": 3}')
    settings = SimpleNamespace(source_audio_max_duration_seconds=1800, source_audio_model_path=model,
                               source_audio_max_attempts=3)
    with pytest.raises(ValueError, match='AUDIO_ATTEMPTS_EXHAUSTED'):
        transcript({'youtube_id':'known','duration_sec':100}, tmp_path,
                   lambda *a, **kw: pytest.fail('download'), 'python', settings)


def test_preboot_archive_preserves_bytes_and_rejects_live_pid(tmp_path, monkeypatch):
    import importlib.util
    import os
    import hashlib
    import pytest
    from video_processing.core.maintenance import MaintenanceGate
    spec = importlib.util.spec_from_file_location('recovery', Path(__file__).resolve().parents[2] / 'scripts/recover_continuity.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    gate = MaintenanceGate(tmp_path / 'state.json'); state = gate.enter('test')
    gate.directory.mkdir()
    identity = 'a' * 32
    path = gate.directory / (identity + '.json')
    data = json.dumps({'id':identity,'role':'channel-monitor','object':'test','phase':'ACTIVE','pid':os.getpid(),'at':1}).encode()
    path.write_bytes(data)
    expected = {'version':state['version'],'boot':'boot','boot_epoch':2,'records':[
        {'id':identity,'inode':path.stat().st_ino,'sha256':hashlib.sha256(data).hexdigest()}]}
    monkeypatch.setattr(module, 'boot_id', lambda:'boot')
    with pytest.raises(RuntimeError, match='PID_PRESENT'):
        module.archive_records(gate, expected, tmp_path/'archive')
    assert path.read_bytes() == data
    def absent(pid, sig):
        raise ProcessLookupError()
    monkeypatch.setattr(module.os, 'kill', absent)
    module.archive_records(gate, expected, tmp_path/'archive')
    assert not path.exists()
    assert (tmp_path/'archive'/path.name).read_bytes() == data
    assert gate.status()['state'] == 'MAINTENANCE'


def test_maintenance_age_never_auto_resumes(tmp_path, monkeypatch):
    from video_processing.core.maintenance import MaintenanceGate
    import video_processing.core.maintenance as module
    monkeypatch.setattr(module.time, 'time', lambda:1)
    gate = MaintenanceGate(tmp_path/'state.json'); gate.enter('intentional')
    monkeypatch.setattr(module.time, 'time', lambda:4000)
    result=gate.status()
    assert result['maintenance_overdue'] and result['maintenance_age_seconds']==3999
    assert result['state']=='MAINTENANCE'

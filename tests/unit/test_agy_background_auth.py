"""认证失败不运行模型、不打开授权页；提醒合并且人工登录后自动恢复。"""
import json
import subprocess
from pathlib import Path

import pytest
from video_processing.utils import agy_background_auth as auth
from video_processing.utils import cover_agy


@pytest.mark.parametrize('evidence,exit_code,ready', [
    ('ChainedAuth: authenticated via keyring (effective: keyring)', 0, True),
    ('OAuth: authenticated successfully as test', 0, True),
    ('available models from cache', 0, False),
    ('not authenticated: no stored credentials found', 1, False),
    ('OAuth: authenticated successfully\nStarting OAuth authentication flow', 0, False),
])
def test_preflight_requires_current_positive_auth_evidence(tmp_path, evidence, exit_code, ready):
    def runner(command, **kw):
        assert command[0].endswith('sandbox-exec')
        assert command[-1] == 'models'
        assert '--print' not in command
        Path(command[command.index('--log-file') + 1]).write_text(evidence)
        return subprocess.CompletedProcess(command, exit_code, 'cached model list', '')
    if ready:
        auth.require_auth('agy', cwd=tmp_path, env={}, runner=runner)
    else:
        with pytest.raises(auth.AgyAuthRequired):
            auth.require_auth('agy', cwd=tmp_path, env={}, runner=runner)
    assert not list(tmp_path.glob('agy-auth-*'))


def test_missing_isolator_fails_closed(monkeypatch):
    monkeypatch.setattr(auth.shutil, 'which', lambda name: None)
    with pytest.raises(auth.AgyAuthRequired, match='isolation unavailable'):
        auth.background_command(['agy', '--print', 'test'])


def test_auth_failure_never_launches_generation(tmp_path, monkeypatch):
    def unavailable(*a, **k):
        raise auth.AgyAuthRequired('AGY_AUTH_REQUIRED')
    monkeypatch.setattr(cover_agy, 'require_auth', unavailable)
    monkeypatch.setattr(cover_agy, 'run_process', lambda *a, **k: pytest.fail('model launched'))
    with pytest.raises(auth.AgyAuthRequired):
        cover_agy.run_cli(['agy', '--print', 'private prompt'], cwd=tmp_path, timeout=1)


def test_auth_notice_deduplicated_and_recovers_after_manual_login(tmp_path):
    path = tmp_path / 'state.json'
    calls, notices = [], []
    def unavailable():
        calls.append(1)
        raise auth.AgyAuthRequired('AGY_AUTH_REQUIRED')
    def check(now, probe=unavailable):
        return auth.auth_ready(path, check=probe, notify=lambda: notices.append(1), now=now)
    assert not check(1000)
    assert not check(1001)
    assert not check(1300)
    assert len(calls) == 2 and len(notices) == 1
    assert check(1600, lambda: None)
    assert json.loads(path.read_text())['status'] == 'READY'
    assert not check(1900)
    assert len(notices) == 2  # 新故障可再次提示。


def test_auth_expires_after_preflight_still_returns_manual_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(cover_agy, 'require_auth', lambda *a, **k: None)
    def lost_auth(command, **kw):
        assert command[0].endswith('sandbox-exec')
        Path(command[command.index('--log-file') + 1]).write_text('Print mode: triggering interactive OAuth')
        raise RuntimeError('PROCESS_TIMEOUT')
    monkeypatch.setattr(cover_agy, 'run_process', lost_auth)
    with pytest.raises(auth.AgyAuthRequired, match='expired during background call'):
        cover_agy.run_cli(['agy', '--print', 'test'], cwd=tmp_path, timeout=1)

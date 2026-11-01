"""真实内核锁保护所有 Bot 初始化；不读取认证、不建立网络连接。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-11-01 | Codex | 覆盖跨进程重复启动、完整生命周期及异常释放，不吞业务层占用异常。 |
"""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from bot import telegram_bot as bot
from video_processing.core.task_lease import TaskLeaseBusy, read_lease_owner


def test_competing_process_prevents_bot_configuration_and_network_initialization(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, 'settings', SimpleNamespace(default_output_dir=tmp_path))
    def forbidden():
        raise AssertionError('A second process must never initialize the Bot')
    monkeypatch.setattr(bot, '_run_bot', forbidden)
    script = ("from pathlib import Path; import sys; "
              "from video_processing.core.task_lease import TaskLease; "
              "lease=TaskLease(Path(sys.argv[1])); lease.__enter__(); "
              "print('locked',flush=True); sys.stdin.readline(); lease.__exit__()")
    child = subprocess.Popen([sys.executable, '-c', script, str(tmp_path/'telegram_bot.lock')],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'locked'
        assert read_lease_owner(tmp_path/'telegram_bot.lock')['pid'] == child.pid
        bot.main()
        assert child.poll() is None
        assert read_lease_owner(tmp_path/'telegram_bot.lock')['pid'] == child.pid
    finally:
        child.communicate('\n', timeout=10)
    assert child.returncode == 0
    assert not read_lease_owner(tmp_path/'telegram_bot.lock')


def test_instance_lock_covers_entire_run_and_releases_after_normal_return(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, 'settings', SimpleNamespace(default_output_dir=tmp_path))
    calls = []
    def run():
        calls.append('running')
        assert len(calls) == 1
        assert read_lease_owner(tmp_path/'telegram_bot.lock')['pid'] == os.getpid()
        bot.main()
    monkeypatch.setattr(bot, '_run_bot', run)
    bot.main()
    assert calls == ['running']
    assert not read_lease_owner(tmp_path/'telegram_bot.lock')


@pytest.mark.parametrize('failure', [RuntimeError('startup failed'), TaskLeaseBusy('business-stage-busy')])
def test_run_failure_is_preserved_and_instance_lock_released(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(bot, 'settings', SimpleNamespace(default_output_dir=tmp_path))
    def run():
        raise failure
    monkeypatch.setattr(bot, '_run_bot', run)
    with pytest.raises(type(failure), match=str(failure)):
        bot.main()
    assert not read_lease_owner(tmp_path/'telegram_bot.lock')

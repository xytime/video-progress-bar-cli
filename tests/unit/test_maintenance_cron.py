"""cron shell 归属：真实未知保持阻断，测试不操作宿主调度。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 唯一登记子进程、命令与拓扑负向回归 |
"""
import os
from pathlib import Path
import subprocess
import pytest
from video_processing.core.maintenance_cron import verified_cron_shell


@pytest.mark.parametrize('case', [
    'valid', 'relative', 'pythonpath', 'untracked', 'extra_child', 'wrong_parent',
    'wrong_uid', 'wrong_child', 'wrong_cwd', 'empty_cwd', 'multi_cwd', 'not_cron',
    'duplicate_cron', 'extra_command', 'substitution', 'changed_pid', 'changed_command',
    'exited_child', 'read_failed', 'cwd_failed', 'no_child', 'production_script_symlink',
])
def test_cron_shell_requires_complete_evidence(tmp_path, monkeypatch, case):
    root = tmp_path / 'production'
    (root / 'scripts').mkdir(parents=True)
    (root / 'output').mkdir()
    script = root / 'scripts/monitor_channels.py'
    script.write_text('# isolated fixture')
    if case == 'production_script_symlink':
        external = tmp_path / 'external.py'; external.write_text('# external')
        script.unlink(); script.symlink_to(external)
    python = str(root / '.venv/bin/python')
    entry = 'scripts/monitor_channels.py' if case == 'relative' else str(script)
    env = f'PYTHONPATH="{root}/src" ' if case == 'pythonpath' else ''
    body = f'cd "{root}" && {env}"{python}" "{entry}" >> "{root}/output/monitor.log" 2>&1'
    if case == 'extra_command': body += '; echo extra'
    if case == 'substitution': body = body.replace('monitor.log', '$(echo unsafe).log')
    command = '/bin/sh -c ' + body
    child_command = f'{python} {entry}'
    uid = os.getuid()
    cron = '9991 1 0 /usr/sbin/cron\n'
    if case == 'wrong_parent': cron = '9991 1 0 /bin/sh\n'
    shell = f'9992 9991 {uid if case != "wrong_uid" else uid+1} /bin/sh\n'
    child = f'9993 9992 {uid} {python}\n'
    if case == 'no_child': child = ''
    if case == 'extra_child': child += f'9994 9992 {uid} /bin/sh\n'
    counts = {'topology': 0, 'birth': 0}
    def run(args, **kwargs):
        if case == 'read_failed' or (case == 'cwd_failed' and args[0].endswith('lsof')):
            raise subprocess.CalledProcessError(1, args)
        if args == ['crontab', '-l']:
            text = '' if case == 'not_cron' else '*/30 * * * * ' + body + '\n'
            if case == 'duplicate_cron': text *= 2
        elif args == ['ps', '-axo', 'pid=,ppid=,uid=,comm=']:
            counts['topology'] += 1
            text = cron + shell + ('' if case == 'exited_child' and counts['topology'] == 2 else child)
        elif args[0].endswith('lsof'):
            text = f'n{tmp_path if case == "wrong_cwd" else root}\n'
            if case == 'empty_cwd': text = ''
            if case == 'multi_cwd': text += f'n{tmp_path}\n'
        else:
            text = command if args[2] == '9992' else child_command
            if case == 'changed_command': text += ' extra'
        return subprocess.CompletedProcess(args, 0, text, '')
    monkeypatch.setattr(subprocess, 'run', run)
    def birth(pid):
        counts['birth'] += 1
        return str(pid) + ('changed' if case == 'changed_pid' and counts['birth'] > 3 else '')
    commands = {9993: child_command if case != 'wrong_child' else python + ' other.py'}
    active = set() if case == 'untracked' else {9993}
    observed = verified_cron_shell(9992, command, root, active, commands, birth)
    assert observed is (case in {'valid', 'relative', 'pythonpath'})

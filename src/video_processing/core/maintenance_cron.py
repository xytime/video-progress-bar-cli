"""只读确认等待已登记子进程的 cron shell；不信任名称或路径子串。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 命令、cron 父进程、唯一登记子进程及身份复核 |
"""
import os
from pathlib import Path
import shlex
import subprocess


def _read(args):
    return subprocess.run(args, text=True, capture_output=True, timeout=2, check=True).stdout


def _entry(command, root):
    prefix = '/bin/sh -c '
    if not command.startswith(prefix):
        return None
    body = command[len(prefix):]
    if any(char in body for char in ('$', '`', ';', '|', '\n', '\r', '<')):
        return None
    tokens = shlex.split(body)
    if tokens[:3] != ['cd', str(root), '&&']:
        return None
    tail = tokens[3:]
    if tail and tail[0] == 'PYTHONPATH=' + str(root / 'src'):
        tail = tail[1:]
    if len(tail) != 5 or tail[0] != str(root / '.venv/bin/python') or tail[2] != '>>' or tail[4] != '2>&1':
        return None
    script = Path(tail[1])
    script = script if script.is_absolute() else root / script
    log = Path(tail[3])
    if (script.resolve().parent != (root / 'scripts').resolve() or script.suffix != '.py'
            or not script.is_file() or log.resolve().parent != (root / 'output').resolve()):
        return None
    return body, tail[:2]


def _topology():
    rows = {}
    for line in _read(['ps', '-axo', 'pid=,ppid=,uid=,comm=']).splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) != 4:
            raise ValueError('进程拓扑无法确认')
        pid, parent, uid = map(int, parts[:3])
        rows[pid] = (parent, uid, parts[3])
    return rows


def verified_cron_shell(pid, command, root, active_pids, commands, birth_reader):
    """仅在真实登记子进程存活时承认其受控 shell；失败一律不排除。"""
    try:
        parsed = _entry(command, root)
        if parsed is None:
            return False
        body, child_args = parsed
        entries = []
        for line in _read(['crontab', '-l']).splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            fields = line.split(None, 1 if line.startswith('@') else 5)
            if len(fields) == (2 if line.startswith('@') else 6):
                entries.append(fields[-1])
        if entries.count(body) != 1:
            return False
        rows = _topology()
        parent, uid, executable = rows[pid]
        children = [child for child, row in rows.items() if row[0] == pid]
        if (executable != '/bin/sh' or uid != os.getuid() or len(children) != 1
                or rows[parent][1:] != (0, '/usr/sbin/cron')):
            return False
        child = children[0]
        if (child not in active_pids or rows[child][1:] != (uid, str(root / '.venv/bin/python'))
                or shlex.split(commands.get(child, '')) != child_args):
            return False
        identities = {item: birth_reader(item) for item in (pid, parent, child)}
        cwd = _read(['/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'])
        directories = [line[1:] for line in cwd.splitlines() if line.startswith('n')]
        if directories != [str(root)]:
            return False
        # 再读身份、拓扑和命令，拒绝退出、PID 复用或中途替换入口。
        after = _topology()
        if any(after.get(item) != rows[item] or birth_reader(item) != identities[item] for item in identities):
            return False
        if [item for item, row in after.items() if row[0] == pid] != children:
            return False
        return (_read(['ps', '-p', str(pid), '-o', 'command=']).strip() == command
                and shlex.split(_read(['ps', '-p', str(child), '-o', 'command=']).strip()) == child_args)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
        return False

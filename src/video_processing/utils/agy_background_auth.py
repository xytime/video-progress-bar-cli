"""后台 AGY 认证预检与浏览器隔离；不读取或保存认证凭据。

模型列表成功不等于已认证，必须同时取得本次 CLI 的正向认证日志。
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path


class AgyAuthRequired(RuntimeError):
    pass


# CLI 当前会执行 open，也可能经 LaunchServices 直接打开浏览器。
# 规则随子进程继承；缺少原生隔离器时失败关闭，禁止无保护调用。
NO_BROWSER_PROFILE = '''(version 1)
(allow default)
(deny process-exec (literal "/usr/bin/open") (literal "/usr/bin/osascript")
 (subpath "/Applications") (subpath "/System/Applications"))
(deny mach-lookup (global-name "com.apple.lsd.open")
 (global-name "com.apple.lsd.mapdb") (global-name "com.apple.appleevents"))
'''


def background_command(command: list[str]) -> list[str]:
    sandbox = shutil.which('sandbox-exec')
    if not sandbox:
        raise AgyAuthRequired('AGY_AUTH_REQUIRED: browser isolation unavailable')
    return [sandbox, '-p', NO_BROWSER_PROFILE, *command]


def require_auth(command: str, *, cwd: Path, env: dict, runner) -> None:
    """无模型调用的认证预检。只输出状态，临时原始日志随检查删除。"""
    with tempfile.TemporaryDirectory(prefix='agy-auth-', dir=cwd) as directory:
        log = Path(directory) / 'probe.log'
        try:
            result = runner(background_command([command, '--log-file', str(log), 'models']),
                            cwd=Path(directory), timeout=30, env=env)
        except (OSError, RuntimeError):
            raise AgyAuthRequired('AGY_AUTH_REQUIRED: authentication check unavailable') from None
        evidence = log.read_text(errors='replace') if log.is_file() else ''
        authenticated = ('ChainedAuth: authenticated via' in evidence
                         or 'OAuth: authenticated successfully' in evidence)
        interactive = 'triggering interactive OAuth' in evidence or 'Starting OAuth authentication flow' in evidence
        if result.returncode or not authenticated or interactive:
            raise AgyAuthRequired('AGY_AUTH_REQUIRED: please log in manually with agy')


def auth_ready(path: Path, *, check, notify, now: float) -> bool:
    """调用方持协调器锁；五分钟重查，通知按故障合并，恢复后自动放行。"""
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    if state.get('status') == 'AUTH_REQUIRED' and now < state.get('next_check_at', 0):
        return False
    try:
        check()
    except AgyAuthRequired:
        state = {'status': 'AUTH_REQUIRED', 'since': state.get('since', now),
                 'next_check_at': now + 300, 'notice_at': state.get('notice_at', 0)}
        if now >= state['notice_at']:
            # UNKNOWN 也不高频重发；底层投递账本另有成功回执去重。
            state['notice_at'] = now + 86400
            notify()
        ready = False
    else:
        state = {'status': 'READY', 'checked_at': now}
        ready = True
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state) + '\n')
    temporary.replace(path)
    return ready

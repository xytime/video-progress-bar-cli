"""后台 AGY 认证预检与浏览器隔离；不读取或保存认证凭据。

模型列表成功不等于已认证，必须同时取得本次 CLI 的正向认证日志。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1 | 2026-10-25 | Codex | 认证结果带时效与检查失败分类，独立文件锁保护强制核实及后台刷新。 |
"""
from __future__ import annotations

import json
import shutil
import tempfile
import fcntl
import math
from pathlib import Path


class AgyAuthRequired(RuntimeError):
    pass


class AgyAuthUnavailable(AgyAuthRequired):
    """检查设施不可用，不能据此要求用户重新登录。"""


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
        raise AgyAuthUnavailable('AGY_AUTH_UNKNOWN: browser isolation unavailable')
    return [sandbox, '-p', NO_BROWSER_PROFILE, *command]


def require_auth(command: str, *, cwd: Path, env: dict, runner) -> None:
    """无模型调用的认证预检。只输出状态，临时原始日志随检查删除。"""
    with tempfile.TemporaryDirectory(prefix='agy-auth-', dir=cwd) as directory:
        log = Path(directory) / 'probe.log'
        try:
            result = runner(background_command([command, '--log-file', str(log), 'models']),
                            cwd=Path(directory), timeout=30, env=env)
        except (OSError, RuntimeError):
            raise AgyAuthUnavailable('AGY_AUTH_UNKNOWN: authentication check unavailable') from None
        evidence = log.read_text(errors='replace') if log.is_file() else ''
        authenticated = ('ChainedAuth: authenticated via' in evidence
                         or 'OAuth: authenticated successfully' in evidence)
        interactive = 'triggering interactive OAuth' in evidence or 'Starting OAuth authentication flow' in evidence
        if interactive or 'not authenticated' in evidence or 'no stored credentials' in evidence:
            raise AgyAuthRequired('AGY_AUTH_REQUIRED: please log in manually with agy')
        if result.returncode or not authenticated:
            raise AgyAuthUnavailable('AGY_AUTH_UNKNOWN: no current authentication evidence')


def auth_snapshot(path: Path, *, now: float) -> dict:
    """只读脱敏状态；过期、损坏和未来时间不冒充当前登录结论。"""
    try:
        state = json.loads(path.read_text())
        checked = float(state.get('checked_at', 0))
        fresh = math.isfinite(checked) and 0 < checked <= now and now - checked < 300
        if not math.isfinite(checked):
            checked = 0
        status = state.get('status') if fresh else 'UNKNOWN'
        if status not in {'READY', 'AUTH_REQUIRED', 'UNKNOWN'}:
            status = 'UNKNOWN'
    except (OSError, ValueError, TypeError, AttributeError):
        state = {}
        status, checked, fresh = 'UNKNOWN', 0, False
    return {'status': status, 'checked_at': checked or None, 'fresh': fresh,
            'reason': state.get('reason') if fresh else 'STALE'}


def auth_ready(path: Path, *, check, notify, now: float, force: bool = False) -> bool:
    """五分钟重查；独立锁保护控制台与协调器，人工核实不弹 OAuth。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        snapshot = auth_snapshot(path, now=now)
        if snapshot['fresh'] and not force:
            return snapshot['status'] == 'READY'
        try:
            previous = json.loads(path.read_text())
            if not isinstance(previous, dict):
                previous = {}
        except (OSError, ValueError):
            previous = {}
        state = {'checked_at': now, 'status': 'UNKNOWN', 'reason': 'CHECK_FAILED'}
        try:
            check()
        except AgyAuthUnavailable:
            pass
        except AgyAuthRequired:
            notice_at = previous.get('notice_at', 0)
            if not isinstance(notice_at, (int, float)) or not math.isfinite(notice_at):
                notice_at = 0
            state.update(status='AUTH_REQUIRED', reason='LOGIN_REQUIRED',
                         notice_at=notice_at)
            if notify is not None and now >= state['notice_at']:
                state['notice_at'] = now + 86400
                notify()
        else:
            state.update(status='READY', reason='CURRENT_POSITIVE_EVIDENCE')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state) + '\n')
        temporary.replace(path)
        return state['status'] == 'READY'

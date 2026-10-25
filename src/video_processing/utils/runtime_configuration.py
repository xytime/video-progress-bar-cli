"""业务层配置快照与统一验证适配；不启动平台工作、不更改账本。

# Modification History
| reply-recovery-v1 | 2026-10-25 | Codex | 回复策略复用活动版本校验，保留既有时段与审批批准上界。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | 唯一读取入口、批准范围校验、失败闭锁与执行者5秒加载确认。 |
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import copy
import os
import time
from config.settings import settings
from config.runtime_policy import PolicyStore, ATTEMPT, ConfigurationError, atomic
from config.runtime_registry import (SETTING_FIELDS, TASK_FIELDS, OBSERVABILITY_FIELDS,
                                     TASK_DEFAULTS, OBSERVABILITY_DEFAULTS, validate_fields, validate_interaction_controls)


def store():
    return PolicyStore(settings.runtime_configuration_path)


def enabled():
    return settings.runtime_configuration_enabled


def snapshot(*, fresh=False):
    if not enabled():
        return None
    frozen = ATTEMPT.get()
    if not fresh and frozen and frozen[0] == str(settings.runtime_configuration_path):
        return frozen[1]
    result = store().read()
    validate_domains(result.domains())
    return result


def value(domain, key, fallback):
    current = snapshot()
    return current.domains()[domain][key] if current else fallback


def validate_domains(domains):
    from .wechat_operations_policy import validate
    if not isinstance(domains, dict) or set(domains) != {'wechat_operations','task_scheduling','observability','runtime_settings','interaction_controls'}:
        raise ConfigurationError('配置领域不完整')
    validate(domains['wechat_operations'])
    validate_fields(domains['task_scheduling'], TASK_FIELDS)
    validate_fields(domains['observability'], OBSERVABILITY_FIELDS)
    validate_fields(domains['runtime_settings'], SETTING_FIELDS)
    validate_interaction_controls(domains['interaction_controls'])
    return domains


def approved_validation(domains):
    """原值基线为服务端迁移材料；客户端不能上传/修改批准边界。"""
    validate_domains(domains)
    from config.runtime_policy import decode
    baseline = decode((settings.runtime_configuration_path / 'approved-baseline.json').read_bytes())
    candidate = domains['interaction_controls'].get('reply_strategy')
    if candidate is not None:
        from .secondary_reply_policy import read_legacy_policy, validate_strategy_approval
        original = baseline['interaction_controls'].get('reply_strategy') or read_legacy_policy()
        validate_strategy_approval(candidate, original)
    for name, candidate in domains['runtime_settings'].items():
        original = baseline['runtime_settings'][name]
        more_is_safer = 'interval' in name or name.endswith('retry_hours')
        if (more_is_safer and candidate < original) or (not more_is_safer and candidate > original):
            raise ConfigurationError(SETTING_FIELDS[name][0] + '超出迁移基线，需要单独批准；当前没有批准凭据')
    return domains


def initial_domains():
    from .wechat_operations_policy import load_policy
    return {'wechat_operations':copy.deepcopy(load_policy()), 'task_scheduling':dict(TASK_DEFAULTS),
            'observability':dict(OBSERVABILITY_DEFAULTS),
            'interaction_controls':{'automatic_replies_enabled':bool(settings.enable_wechat_secondary_reply and settings.enable_wechat_secondary_reply_live_submission)},
            'runtime_settings':{name:getattr(settings,name) for name in SETTING_FIELDS}}


@contextmanager
def policy_read_lock():
    if enabled():
        with store().locked():
            yield
    else:
        yield


def freeze_attempt(current=None):
    current = current or snapshot(fresh=True)
    return ATTEMPT.set((str(settings.runtime_configuration_path), current)) if current else None


def finish_attempt(token):
    if token is not None:
        ATTEMPT.reset(token)


def acknowledge(role, *, lifecycle='RUNNING'):
    """本机只写非秘密加载确认；从不把活跃任务伪装成采用了新参数。"""
    if not enabled():
        return {'enabled':False}
    try:
        current = snapshot(fresh=True)
        active = ATTEMPT.get()
        result = {'role':role,'pid':os.getpid(),'loaded_revision':current.revision,
                  'active_attempt_revision':active[1].revision if active else None,
                  'acknowledged_at':time.time(),'error':None,
                  'lifecycle':lifecycle,
                  'automatic_replies_enabled':current.domains()['interaction_controls']['automatic_replies_enabled'],
                  'reply_identity_configured':bool(settings.wechat_reply_account_key and settings.wechat_reply_author_finder_id)}
    except (ValueError,OSError) as exc:
        result = {'role':role,'pid':os.getpid(),'loaded_revision':None,'active_attempt_revision':None,
                  'acknowledged_at':time.time(),'error':type(exc).__name__}
    atomic(settings.default_output_dir / 'runtime_config_workers' / (role + '.json'), result)
    return result


@contextmanager
def presence(role):
    """定时CLI在运行时确认版本；结束后明确标记停止，不假装常驻在线。"""
    import threading
    stopped=threading.Event()
    def tick():
        while not stopped.is_set():
            try:acknowledge(role)
            except (ValueError,OSError):pass
            stopped.wait(5)
    thread=threading.Thread(target=tick,daemon=True)
    thread.start()
    try:yield
    finally:
        stopped.set();thread.join(timeout=6)
        try:acknowledge(role,lifecycle='STOPPED')
        except (ValueError,OSError):pass  # 观测故障不能覆盖已完成的外部动作事实。


def recompute_waits(db, current):
    """版本变更只重算未提交的本地门禁，实际外部动作仍由原调度领取。"""
    import datetime
    from ..core.wechat_request_guard import WeChatRequestGuard
    guard = WeChatRequestGuard(settings.default_output_dir / 'wechat_state.json')
    changed = 0
    for row in db.runtime_configuration_waits():
        if row.get('policy_wait_revision') == current.revision:
            continue
        info = guard.evaluate(purpose='首评', task=row['platform_post_id'])
        now = time.time()
        until = info.get('until')
        next_at = max(now, until) if until is not None else now + current.domains()['task_scheduling']['local_defer_fallback_seconds']
        changed += db.reschedule_runtime_configuration_wait(row,
            next_at=datetime.datetime.fromtimestamp(next_at,datetime.timezone.utc).isoformat(),
            revision=current.revision,codes=[b['code'] for b in info['blockers']],until=until)
    if changed:
        (settings.default_output_dir / 'ready_publications.wake').touch()
    return changed

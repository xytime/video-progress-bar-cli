"""视频号二级回复运营策略配置、CAS 原子保存与跨进程热加载。

支持后台管理界面实时调整提交时间窗（默认 00:00–24:00 全天开放）、最小提交间隔（默认 3600 秒即 1 小时）、
滚动小时上限、单视频累计上限与审批模式，并通过文件 mtime 变化检测在 Web 进程、CLI 与 Tick 进程间热加载生效。

依赖方向：web / db / interaction -> 本模块 -> config.settings / wechat_product_config (atomic_json)。

# Modification History
| reply-linkage-v1 | 2026-10-25 | Codex | 每日额度联动与持久手动覆盖；校验实际检查节拍。 |
| reply-recovery-v1 | 2026-10-25 | Codex | 策略页接入活动版本 CAS，独立额度一致读取，旧文件只保留批准基线。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-18 | Antigravity | 初始创建：实现二级回复运营策略 CAS 持久化、24h/跨午夜窗口判定与 mtime 热加载 |
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, Optional

from config.settings import settings
from config.runtime_registry import REPLY_STRATEGY_FIELDS, validate_reply_strategy
from .wechat_product_config import PolicyConflict, atomic_json

logger = logging.getLogger(__name__)

from config.secondary_reply_schema import SecondaryReplyPolicyModel, parse_policy

# 记录各配置文件路径上次已热加载到 settings 的 st_mtime_ns
_LAST_MTIME_NS: Dict[str, int] = {}


def validate_strategy_approval(candidate: dict, approved: dict) -> None:
    """保持迁移前批准时段与审批上界；普通保存可以收紧，不能扩大自动发送。"""
    validate_reply_strategy(candidate)
    allowed = {minute for minute in range(1440) if is_within_shanghai_window(
        f'{minute // 60:02d}:{minute % 60:02d}', approved['window_start_shanghai'], approved['window_end_shanghai'])}
    proposed = {minute for minute in range(1440) if is_within_shanghai_window(
        f'{minute // 60:02d}:{minute % 60:02d}', candidate['window_start_shanghai'], candidate['window_end_shanghai'])}
    if not proposed <= allowed or (candidate['approval_mode'] == 'hybrid_auto' and approved['approval_mode'] != 'hybrid_auto'):
        raise ValueError('扩大回复时段或自动审批范围需要专门批准；本次未保存，草稿已保留')


def parse_editor_policy(data: dict) -> dict:
    base = {k: v for k, v in data.items() if k not in {'daily_quota', 'linkage'}}
    result = parse_policy(base, editor=True)
    if 'daily_quota' in data:
        daily = data['daily_quota']
        if type(daily) is not int or not 1 <= daily <= 1000:
            raise ValueError('最近24小时回复上限须为1–1000的整数')
        result['daily_quota'] = daily
    if 'linkage' in data:
        from config.reply_linkage import validate_linkage
        result['linkage'] = dict(validate_linkage(data['linkage']))
    return result


def digest(config: dict) -> str:
    """计算配置字典的确定性 SHA256 摘要，用于 CAS 并发保护。"""
    normalized = parse_editor_policy(config)
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def is_within_shanghai_window(current_hhmm: str, start_hhmm: str, end_hhmm: str) -> bool:
    """判断上海时间 HH:MM 是否处于配置的允许提交窗口内。

    支持：
    - 全天 24 小时开放：start == '00:00' 且 end == '24:00'（或 start == end）；
    - 常规日内窗口（start < end）：start <= current < end；
    - 跨午夜窗口（start > end，如 08:30–01:00）：current >= start 或 current < end。
    """
    if (start_hhmm == "00:00" and end_hhmm == "24:00") or start_hhmm == end_hhmm:
        return True
    if start_hhmm < end_hhmm:
        return start_hhmm <= current_hhmm < end_hhmm
    return current_hhmm >= start_hhmm or current_hhmm < end_hhmm


def current_policy_from_settings() -> dict:
    """从当前内存 settings 单例提取有效二级回复策略。"""
    raw = {
        "schema_version": 1,
        "window_start_shanghai": str(getattr(settings, "wechat_reply_window_start_shanghai", "00:00") or "00:00"),
        "window_end_shanghai": str(getattr(settings, "wechat_reply_window_end_shanghai", "24:00") or "24:00"),
        "min_interval_seconds": int(getattr(settings, "wechat_reply_min_interval_seconds", 3600)),
        "hourly_quota": int(getattr(settings, "wechat_reply_hourly_quota", 10)),
        "max_per_video": int(getattr(settings, "wechat_reply_max_per_video", 3)),
        "approval_mode": str(getattr(settings, "wechat_reply_approval_mode", "manual") or "manual"),
    }
    return parse_policy(raw, editor=settings.runtime_configuration_enabled)


def apply_policy_to_settings(config: dict) -> dict:
    """将已校验的策略字典立即热更新到当前进程 settings 单例。"""
    validated = parse_editor_policy(config)
    settings.wechat_reply_window_start_shanghai = validated["window_start_shanghai"]
    settings.wechat_reply_window_end_shanghai = validated["window_end_shanghai"]
    settings.wechat_reply_min_interval_seconds = validated["min_interval_seconds"]
    settings.wechat_reply_hourly_quota = validated["hourly_quota"]
    settings.wechat_reply_max_per_video = validated["max_per_video"]
    settings.wechat_reply_approval_mode = validated["approval_mode"]
    return validated


def sync_secondary_reply_settings(path: Optional[Path] = None) -> dict:
    """按文件 mtime 热加载二级回复策略到 settings；若文件不存在或未变化则保留当前内存设置。"""
    if settings.runtime_configuration_enabled:
        from .runtime_configuration import snapshot
        return apply_policy_to_settings(_runtime_policy(snapshot(), path))
    target = Path(path if path is not None else getattr(settings, "wechat_reply_policy_path"))
    key = str(target)
    try:
        if target.exists():
            mtime_ns = target.stat().st_mtime_ns
            if _LAST_MTIME_NS.get(key) != mtime_ns:
                loaded = parse_policy(json.loads(target.read_text(encoding="utf-8")))
                apply_policy_to_settings(loaded)
                _LAST_MTIME_NS[key] = mtime_ns
                logger.info(
                    "[SecondaryReplyPolicy] 已热加载策略 (%s): window=%s-%s, min_interval=%ds, hourly=%d, max_per_video=%d, mode=%s",
                    target.name,
                    loaded["window_start_shanghai"],
                    loaded["window_end_shanghai"],
                    loaded["min_interval_seconds"],
                    loaded["hourly_quota"],
                    loaded["max_per_video"],
                    loaded["approval_mode"],
                )
    except Exception as exc:
        logger.warning("[SecondaryReplyPolicy] 热加载 %s 失败，保持当前内存配置: %s", target, exc)
    return current_policy_from_settings()


def read_legacy_policy(path: Optional[Path] = None) -> dict:
    """只读迁移前批准策略，不应用到进程，不回退到损坏的活动版本。"""
    target = Path(path if path is not None else getattr(settings, "wechat_reply_policy_path"))
    if target.exists():
        return parse_policy(json.loads(target.read_text(encoding="utf-8")))
    return current_policy_from_settings()


def _runtime_policy(current, path=None) -> dict:
    domains = current.domains()
    config = read_legacy_policy(path)
    config.update(domains['interaction_controls'].get('reply_strategy', {}))
    reply = domains['wechat_operations']['operations']['reply']
    config.update(min_interval_seconds=reply['min_interval_seconds'], hourly_quota=reply['rolling_1h_limit'],
                  max_per_video=reply['max_replies_per_video_lifetime'])
    from .reply_linked_policy import editor_config
    config.update(editor_config(domains, legacy=config))
    return parse_editor_policy(config)


def load_policy(path: Optional[Path] = None) -> dict:
    """读取唯一活动版本；迁移后旧文件仅提供既有时段和审批基线。"""
    if settings.runtime_configuration_enabled:
        from .runtime_configuration import snapshot
        return apply_policy_to_settings(_runtime_policy(snapshot(fresh=True), path))
    return apply_policy_to_settings(read_legacy_policy(path))


def policy_view(path: Path) -> dict:
    if settings.runtime_configuration_enabled:
        from .runtime_configuration import snapshot
        from config.wechat_operations_schema import APPROVED
        current = snapshot(fresh=True)
        config = _runtime_policy(current, path)
        from .reply_linked_policy import capacity_view
        return {'config': config, 'digest': digest(config), 'revision': current.revision,
                'capacity': capacity_view(config),
                'limits': {'min_interval_seconds': APPROVED['reply']['min_interval_seconds'],
                           'hourly_quota': APPROVED['reply']['rolling_1h_limit'],
                           'daily_quota': APPROVED['reply']['rolling_24h_limit'],
                           'max_interval_seconds': 604800,
                           'max_per_video': APPROVED['reply']['max_replies_per_video_lifetime']}}
    config = load_policy(path)
    return {'config': config, 'digest': digest(config), 'revision': None}


def save_policy(path: Path, data: dict, expected_digest: Optional[str] = None,
                *, expected_revision: Optional[str] = None, actor: str = 'secondary-reply-settings') -> dict:
    """校验、CAS 原子落盘并立即热更新到内存 settings。"""
    config = parse_editor_policy(data) if settings.runtime_configuration_enabled else parse_policy(data)
    if settings.runtime_configuration_enabled:
        from config.runtime_policy import ConfigurationConflict
        from .runtime_configuration import snapshot, store, approved_validation
        current = snapshot(fresh=True)
        if expected_revision != current.revision or expected_digest != digest(_runtime_policy(current, path)):
            raise PolicyConflict('配置版本已变化。草稿已保留，请重新载入后合并修改。')
        from .reply_linked_policy import recommend
        prior = _runtime_policy(current, path)
        config.setdefault('daily_quota', prior['daily_quota'])
        config.setdefault('linkage', prior['linkage'])
        config, _ = recommend(config)
        domains = current.domains()
        reply = domains['wechat_operations']['operations']['reply']
        reply.update(rolling_24h_limit=config['daily_quota'], min_interval_seconds=config['min_interval_seconds'], rolling_1h_limit=config['hourly_quota'],
                     max_replies_per_video_lifetime=config['max_per_video'])
        domains['interaction_controls']['reply_strategy'] = {key: config[key] for key in REPLY_STRATEGY_FIELDS}
        domains['interaction_controls']['reply_linkage'] = config['linkage']
        try:
            store().commit(domains, expected_revision=current.revision, actor=actor,
                           reason='评论回复策略页保存', operation_id='reply_settings_' + uuid.uuid4().hex,
                           validate=approved_validation)
        except ConfigurationConflict as exc:
            raise PolicyConflict('配置版本已变化。草稿已保留，请重新载入后合并修改。') from exc
        return apply_policy_to_settings(config)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_suffix(".json.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if expected_digest is not None:
            current_dig = digest(load_policy(target))
            if current_dig != expected_digest:
                raise PolicyConflict("配置已被其他窗口更新。草稿已保留，请重新载入后再修改。")
        atomic_json(target, config)
        apply_policy_to_settings(config)
        try:
            _LAST_MTIME_NS[str(target)] = target.stat().st_mtime_ns
        except OSError:
            pass
    return config

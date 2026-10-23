"""视频号账户冷却与调度策略配置、CAS 原子保存与跨进程热加载。

支持后台管理界面实时调整视频号账户级调度策略（总开关、稳定期最小间隔、稳定期24小时上限、
恢复期最小间隔、恢复期24小时上限、会话请求最小间隔、平台限流退避基数），并通过文件 mtime 变化检测
在 Web 进程、CLI 与守护进程间热加载生效。默认参数严格保留安全生产默认值（900s / 20次 / 3600s / 1次 / 60s / 1800s）。

依赖方向：web / core -> 本模块 -> config.settings / wechat_product_config (atomic_json)。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-22 | Antigravity | 初始创建：实现视频号账户冷却与调度策略 CAS 持久化、参数边界校验与 mtime 热加载 |
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from .wechat_product_config import PolicyConflict, atomic_json

logger = logging.getLogger(__name__)

# 记录各配置文件路径上次已热加载到 settings 的 st_mtime_ns
_LAST_MTIME_NS: Dict[str, int] = {}


class WeChatSchedulerPolicyModel(BaseModel):
    """视频号账户冷却与调度策略 Schema（禁止额外字段与类型强转）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    scheduler_enabled: bool = Field(default=True, strict=True)
    stable_interval_seconds: int = Field(default=900, strict=True, ge=60, le=86400)
    daily_limit: int = Field(default=20, strict=True, ge=1, le=100)
    recovery_interval_seconds: int = Field(default=3600, strict=True, ge=300, le=86400)
    recovery_limit: int = Field(default=1, strict=True, ge=1, le=20)
    request_min_interval_seconds: int = Field(default=60, strict=True, ge=1, le=3600)
    rate_limit_cooldown_seconds: int = Field(default=1800, strict=True, ge=300, le=86400)


DEFAULT_WECHAT_SCHEDULER_POLICY: dict = {
    "schema_version": 1,
    "scheduler_enabled": True,
    "stable_interval_seconds": 900,
    "daily_limit": 20,
    "recovery_interval_seconds": 3600,
    "recovery_limit": 1,
    "request_min_interval_seconds": 60,
    "rate_limit_cooldown_seconds": 1800,
}


def parse_policy(data: dict) -> dict:
    """校验并规范化视频号账户调度策略字典。"""
    return WeChatSchedulerPolicyModel.model_validate(data).model_dump()


def digest(config: dict) -> str:
    """计算配置字典的确定性 SHA256 摘要，用于 CAS 并发保护。"""
    normalized = parse_policy(config)
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def current_policy_from_settings() -> dict:
    """从当前内存 settings 单例提取有效视频号账户调度策略。"""
    raw = {
        "schema_version": 1,
        "scheduler_enabled": bool(getattr(settings, "wechat_account_scheduler_enabled", True)),
        "stable_interval_seconds": int(getattr(settings, "wechat_scheduler_stable_interval_seconds", 900)),
        "daily_limit": int(getattr(settings, "wechat_scheduler_daily_limit", 20)),
        "recovery_interval_seconds": int(getattr(settings, "wechat_scheduler_recovery_interval_seconds", 3600)),
        "recovery_limit": int(getattr(settings, "wechat_scheduler_recovery_limit", 1)),
        "request_min_interval_seconds": int(getattr(settings, "wechat_request_min_interval_seconds", 60)),
        "rate_limit_cooldown_seconds": int(getattr(settings, "wechat_rate_limit_cooldown_seconds", 1800)),
    }
    return parse_policy(raw)


def apply_policy_to_settings(config: dict) -> dict:
    """将已校验的策略字典立即热更新到当前进程 settings 单例。"""
    validated = parse_policy(config)
    settings.wechat_account_scheduler_enabled = validated["scheduler_enabled"]
    settings.wechat_scheduler_stable_interval_seconds = validated["stable_interval_seconds"]
    settings.wechat_scheduler_daily_limit = validated["daily_limit"]
    settings.wechat_scheduler_recovery_interval_seconds = validated["recovery_interval_seconds"]
    settings.wechat_scheduler_recovery_limit = validated["recovery_limit"]
    settings.wechat_request_min_interval_seconds = validated["request_min_interval_seconds"]
    settings.wechat_rate_limit_cooldown_seconds = validated["rate_limit_cooldown_seconds"]
    return validated


def sync_wechat_scheduler_settings(path: Optional[Path] = None) -> dict:
    """按文件 mtime 热加载视频号调度策略到 settings；若文件不存在或未变化则保留当前内存设置。"""
    target = Path(path if path is not None else getattr(settings, "wechat_scheduler_policy_path"))
    key = str(target)
    try:
        if target.exists():
            mtime_ns = target.stat().st_mtime_ns
            if _LAST_MTIME_NS.get(key) != mtime_ns:
                loaded = parse_policy(json.loads(target.read_text(encoding="utf-8")))
                apply_policy_to_settings(loaded)
                _LAST_MTIME_NS[key] = mtime_ns
                logger.info(
                    "[WeChatSchedulerPolicy] 已热加载策略 (%s): enabled=%s, stable=%ds/%d, recovery=%ds/%d, min_req=%ds",
                    target.name,
                    loaded["scheduler_enabled"],
                    loaded["stable_interval_seconds"],
                    loaded["daily_limit"],
                    loaded["recovery_interval_seconds"],
                    loaded["recovery_limit"],
                    loaded["request_min_interval_seconds"],
                )
    except Exception as exc:
        logger.warning("[WeChatSchedulerPolicy] 热加载 %s 失败，保持当前内存配置: %s", target, exc)
    return current_policy_from_settings()


def load_policy(path: Optional[Path] = None) -> dict:
    """读取当前生效的视频号调度策略（若磁盘文件存在则校验并同步）。"""
    target = Path(path if path is not None else getattr(settings, "wechat_scheduler_policy_path"))
    if target.exists():
        loaded = parse_policy(json.loads(target.read_text(encoding="utf-8")))
        apply_policy_to_settings(loaded)
        _LAST_MTIME_NS[str(target)] = target.stat().st_mtime_ns
        return loaded
    return current_policy_from_settings()


def save_policy(path: Path, data: dict, expected_digest: Optional[str] = None) -> dict:
    """校验、CAS 原子落盘并立即热更新到内存 settings。"""
    config = parse_policy(data)
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

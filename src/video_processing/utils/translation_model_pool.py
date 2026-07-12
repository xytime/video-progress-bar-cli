# -*- coding: utf-8 -*-
"""字幕翻译动态模型池。

以持久化的冷却、错误分类和质量分数替代固定 provider 顺序，避免某个
供应商持续失败时重复撞限额，也让具备 vocabulary 能力的模型优先承担主路径。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-13 | Codex  | 新增字幕 provider 动态排序、冷却记忆、错误分类与质量评分 |
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ModelProfile:
    name: str
    capabilities: frozenset[str]
    priority: int


PROFILES = {
    "gemini": ModelProfile("gemini", frozenset({"translate", "vocab"}), 100),
    "deepseek": ModelProfile("deepseek", frozenset({"translate", "vocab"}), 90),
    "aliyun": ModelProfile("aliyun", frozenset({"translate"}), 40),
    "google": ModelProfile("google", frozenset({"translate"}), 20),
}


def classify_error(message: str | None) -> str:
    """将供应商错误归一为可用于冷却策略的类别。"""
    text = (message or "").lower()
    if any(token in text for token in ("429", "quota", "rate limit", "resource_exhausted")):
        return "rate_limit"
    if any(token in text for token in ("401", "403", "10009", "permission", "unauthorized")):
        return "auth_or_permission"
    if any(token in text for token in ("timeout", "timed out", "connection", "name or service")):
        return "network"
    if any(token in text for token in ("json", "parse", "aligned", "empty")):
        return "invalid_response"
    return "unknown"


class DynamicTranslationModelPool:
    """小型持久化模型池；状态只保存 provider 名称和运行统计，不保存密钥。"""

    _COOLDOWN_SECONDS = {
        "rate_limit": 900,
        "auth_or_permission": 3600,
        "network": 180,
        "invalid_response": 300,
        "quality_blocked": 600,
        "unknown": 180,
    }

    def __init__(self, state_path: Path | None):
        self.state_path = state_path
        self._state = self._load()

    def order(self, providers: Iterable[str], required: set[str] | None = None) -> list[str]:
        """按能力匹配、质量分和静态优先级排序；冷却中的模型排除。"""
        now = time.time()
        required = required or set()
        candidates = []
        for raw in providers:
            name = raw.strip().lower()
            profile = PROFILES.get(name)
            if profile is None:
                continue
            item = self._state.setdefault(name, {})
            if float(item.get("cooldown_until", 0)) > now:
                continue
            missing = len(required - profile.capabilities)
            quality = float(item.get("quality_score", 70.0))
            candidates.append((missing, -(quality + profile.priority * 0.1), name))
        return [name for _, _, name in sorted(candidates)]

    def record_failure(self, provider: str, error: str | None = None, *, category: str | None = None) -> None:
        name = provider.lower()
        item = self._state.setdefault(name, {})
        category = category or classify_error(error)
        item["failure_count"] = int(item.get("failure_count", 0)) + 1
        item["last_error_class"] = category
        item["last_error"] = (error or "")[:240]
        item["cooldown_until"] = time.time() + self._COOLDOWN_SECONDS.get(category, 180)
        self._save()

    def record_quality(self, provider: str, *, score: float, warning_count: int = 0) -> None:
        item = self._state.setdefault(provider.lower(), {})
        previous = float(item.get("quality_score", 70.0))
        item["quality_score"] = round(previous * 0.7 + max(0.0, min(100.0, score)) * 0.3, 2)
        item["warning_count"] = int(item.get("warning_count", 0)) + warning_count
        item["last_success_at"] = time.time()
        item["cooldown_until"] = 0
        self._save()

    def snapshot(self) -> dict:
        return dict(self._state)

    def _load(self) -> dict:
        if self.state_path is None:
            return {}
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # 模型池不能阻断主流程；无法落盘时仍保留本进程内存状态。
            return

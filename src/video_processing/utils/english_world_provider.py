"""英语世界独立 CLI 路由：真实生成预检、冷却及单次故障切换。

依赖：scripts / study_cards → 本模块 → agy / codex_text / settings。
不处理内容裁决、不重置语言账本、不操作发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 具名供应商回执、真实探测和最多两次内容调用；新会话独立审校。 |
"""
from dataclasses import dataclass
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import time
import uuid

import jsonschema
from config.settings import settings
from .agy_provider import AgyProviderError, run_agy_structured
from .codex_text_provider import CodexTextError, run_codex_structured, _atomic_json


class EnglishWorldProviderError(AgyProviderError):
    """无可用通道；上层不能换候选或立即重复整个阶段。"""


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def infrastructure_error(exc):
    if isinstance(exc, CodexTextError):
        return exc.code in {"command_unavailable", "timeout", "quota", "authentication", "model_unavailable",
                            "unavailable", "cooldown", "busy", "incomplete"}
    return isinstance(exc, AgyProviderError) and any(s in str(exc).lower() for s in (
        "command not found", "timed out", "timeout", "location ineligible", "model unavailable",
        "rate limit", "permission", "provider error", "local startup blocked"))


@dataclass(frozen=True)
class Provider:
    name: str
    model: str
    command: str
    effort: str = "high"

    def call(self, prompt, *, schema, state_dir, timeout, images=()):
        if self.name == "agy":
            if images:
                raise ValueError("AGY 图像调用须使用专用视觉入口")
            result = run_agy_structured(prompt, schema=schema, model=self.model, command=self.command,
                                        effort=self.effort, timeout_sec=timeout, include_usage=True)
            jsonschema.validate(result["structured_result"], schema)
            return result
        result = run_codex_structured(prompt, schema=schema, state_dir=state_dir / "codex",
            model=self.model, command=self.command, effort=self.effort, timeout_sec=timeout, images=images)
        return {"structured_result": result.payload, "usage": result.usage}

    def language_caller(self, state_dir):
        def call(prompt, *, schema, timeout_sec, **kwargs):
            return self.call(prompt, schema=schema, state_dir=state_dir, timeout=timeout_sec)
        return call


def providers():
    result = [Provider("agy", settings.english_world_language_model, settings.agy_command,
                       settings.english_world_language_effort)]
    if settings.english_world_codex_fallback:
        result.append(Provider("codex", settings.english_world_codex_model, settings.codex_text_command))
    return result


class ProviderRouter:
    def __init__(self, state_dir, routes=None):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.routes = providers() if routes is None else routes

    def _health_path(self, provider):
        return self.state_dir / (fingerprint(vars(provider)) + ".health.json")

    def _failed(self, provider, exc):
        _atomic_json(self._health_path(provider), {"provider": provider.name, "model": provider.model,
            "state": "UNAVAILABLE", "error": str(exc), "checked_at": time.time(),
            "next_check_at": time.time() + 900})

    def preflight(self):
        for provider in self.routes:
            if self.ready(provider):
                return {"provider": provider.name, "model": provider.model, "state": "READY"}
        raise EnglishWorldProviderError("PROVIDER_BLOCKED: 真实生成预检未通过；15 分钟后允许重新检查")

    def ready(self, provider):
        """真实完成 nonce 结构化生成才算健康；预检不消耗内容审校额度。"""
        path = self._health_path(provider)
        with path.with_suffix(".lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                previous = json.loads(path.read_text())
                if previous["next_check_at"] > time.time():
                    return previous["state"] == "READY"
            nonce = uuid.uuid4().hex
            schema = {"type": "object", "properties": {"nonce": {"type": "string"}},
                      "required": ["nonce"], "additionalProperties": False}
            try:
                result = provider.call("不使用工具。只返回 JSON，将 nonce 原样返回：" + nonce,
                    schema=schema, state_dir=self.state_dir, timeout=60)
                if result["structured_result"] != {"nonce": nonce}:
                    raise ValueError("供应商生成预检返回错误 nonce")
            except (AgyProviderError, CodexTextError) as exc:
                if not infrastructure_error(exc):
                    raise
                self._failed(provider, exc)
                return False
            _atomic_json(path, {"provider": provider.name, "model": provider.model, "state": "READY",
                "checked_at": time.time(), "next_check_at": time.time() + 600, "usage": result.get("usage")})
            return True

    def run(self, action, *, receipt, binding, replay=None):
        """同一阶段输入最多调用两次。成功复用，崩溃占额；内容拒绝从不触发切换。"""
        receipt = Path(receipt)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        key = fingerprint(binding)
        with receipt.with_suffix(".lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            saved = json.loads(receipt.read_text()) if receipt.exists() else {
                "version": "english-world-provider-v1", "binding": key, "attempts": []}
            if saved["binding"] != key:
                raise ValueError("供应商阶段输入已改变；不能复用或覆盖既有回执")
            if saved.get("state") == "COMPLETED":
                if replay is not None:
                    selected = next(p for p in self.routes if p.name == saved["provider"]["provider"]
                                    and p.model == saved["provider"]["model"])
                    return replay(selected), saved["provider"]
                return saved["result"], saved["provider"]
            if saved.get("state") in {"RUNNING", "INVALID"}:
                raise ValueError("供应商阶段在途或输出无效；不得自动重新调用")
            for provider in self.routes:
                if len(saved["attempts"]) >= 2:
                    break
                if any(a["provider"] == provider.name for a in saved["attempts"]):
                    continue
                if not self.ready(provider):
                    continue
                entry = {"provider": provider.name, "model": provider.model, "effort": provider.effort,
                         "started_at": time.time(), "state": "RUNNING"}
                saved["attempts"].append(entry)
                saved["state"] = "RUNNING"
                _atomic_json(receipt, saved)
                try:
                    result = action(provider)
                except Exception as exc:
                    entry.update(state="INFRASTRUCTURE_ERROR" if infrastructure_error(exc) else "INVALID",
                                 error_type=type(exc).__name__, finished_at=time.time())
                    saved["state"] = entry["state"]
                    _atomic_json(receipt, saved)
                    if not infrastructure_error(exc):
                        raise
                    self._failed(provider, exc)
                    continue
                entry.update(state="COMPLETED", finished_at=time.time())
                saved.update(state="COMPLETED", result=result,
                             provider={"provider": provider.name, "model": provider.model, "effort": provider.effort})
                _atomic_json(receipt, saved)
                return result, saved["provider"]
            saved.update(state="PROVIDER_BLOCKED", next_check_at=time.time() + 900)
            _atomic_json(receipt, saved)
            raise EnglishWorldProviderError("PROVIDER_BLOCKED: 独立 CLI 均不可用或阶段额度已用尽；见供应商阶段回执")

    def draft(self, prompt, *, schema, receipt):
        result, _ = self.run(lambda provider: provider.call(prompt, schema=schema, state_dir=self.state_dir,
            timeout=settings.english_world_language_timeout_seconds), receipt=receipt,
            binding={"prompt": prompt, "schema": schema})
        return result["structured_result"]

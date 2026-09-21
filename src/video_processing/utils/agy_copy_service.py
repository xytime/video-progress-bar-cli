"""完整文案的单并发、内容寻址缓存与供应商冷却；不参与投稿。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | AGY 独立文案调用：一次请求、校验后缓存、限流/故障冷却。 |
"""

import fcntl
import hashlib
import json
import time
from pathlib import Path
from typing import Callable

from config.settings import settings
from video_processing.utils.agy_provider import AgyProviderError, run_agy_structured


class CopyProviderDeferred(RuntimeError):
    """稳定的本地延后协议；不得包含模型输出、来源正文或 CLI 原始日志。"""

    def __init__(self, until: int, reason: str, notify: bool = False):
        self.until = int(until)
        self.reason = reason
        self.notify = notify
        super().__init__(f"COPY_PROVIDER_DEFERRED until={self.until} reason={reason} notify={int(notify)}")


def generate_cached_agy_copy(
    prompt: str, *, schema: dict, model: str, command: str, timeout_sec: int,
    quota_cooldown_sec: int, cache_dir: Path, validate: Callable[[dict], dict],
) -> dict:
    """只缓存通过宿主质量审查的响应，命中缓存仍重新执行当前质量合同。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    identity = json.dumps(["agy-copy-v1", prompt, schema, model], ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(identity.encode()).hexdigest()
    cached = cache_dir / f"{key}.json"
    with (cache_dir / "provider.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CopyProviderDeferred(int(time.time()) + 60, "busy") from exc
        if cached.exists():
            return validate(json.loads(cached.read_text(encoding="utf-8")))
        cooldown = cache_dir / "cooldown.json"
        if cooldown.exists():
            state = json.loads(cooldown.read_text(encoding="utf-8"))
            if int(state["until"]) > time.time():
                raise CopyProviderDeferred(int(state["until"]), "cooldown")
        try:
            raw = run_agy_structured(
                prompt, schema=schema, model=model, command=command, timeout_sec=timeout_sec,
                environment=settings.agy_app_environment(),
            )
        except AgyProviderError as exc:
            quota = "rate limit" in str(exc)
            reason = "quota" if quota else "unavailable"
            until = int(time.time()) + (quota_cooldown_sec if quota else 300)
            _atomic_json(cooldown, {"until": until, "reason": reason})
            raise CopyProviderDeferred(until, reason, notify=True) from exc
        result = validate(raw)
        _atomic_json(cached, raw)
        return result


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

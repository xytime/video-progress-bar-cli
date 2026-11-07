"""完整文案的单并发、内容寻址缓存与供应商冷却；不参与投稿。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | AGY 独立文案调用：一次请求、校验后缓存、限流/故障冷却。 |
| 1.1.0 | 2026-11-07 | Grok Bot | 冷却原因保留 auth/timeout/quota/rate_limit；二次命中不再改写成 cooldown。 |
"""

import fcntl
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Callable, Union

from config.settings import settings
from video_processing.utils.agy_provider import AgyProviderError, run_agy_structured


_FAILURE_CLASSES = ("auth", "timeout", "quota", "rate_limit", "unavailable")
_WIRE_REASONS = _FAILURE_CLASSES + ("busy", "cooldown")
_CODE_MAP = {
    "authentication": "auth", "auth": "auth", "agy_auth_required": "auth",
    "timeout": "timeout", "total_timeout": "timeout", "cli_timeout": "timeout",
    "quota": "quota", "rate_limit": "rate_limit", "rate limit": "rate_limit",
    "resource_exhausted": "rate_limit", "unavailable": "unavailable", "busy": "busy",
    "cooldown": "cooldown", "permission": "unavailable", "provider error": "unavailable",
    "invalid_output": "unavailable", "copy_quality": "unavailable",
    "command_unavailable": "unavailable", "model_unavailable": "unavailable",
}
_DIAGNOSTIC_MARKERS = (
    ("AGY_AUTH_REQUIRED", "AGY_AUTH_REQUIRED"),
    ("authentication required", "authentication required"),
    ("RESOURCE_EXHAUSTED", "RESOURCE_EXHAUSTED"),
    ("429", "HTTP 429"),
    ("timed out", "timed out"),
    ("cli_timeout", "cli_timeout"),
    ("rate limit", "rate limit"),
    ("quota", "quota"),
    ("command not found", "command not found"),
)


class CopyProviderDeferred(RuntimeError):
    """稳定的本地延后协议；不得包含模型输出、来源正文或 CLI 原始日志。"""

    def __init__(self, until: int, reason: str, notify: bool = False, classes: str = ""):
        self.until = int(until)
        self.reason = reason
        self.notify = notify
        self.classes = _sanitize_classes(classes)
        suffix = f" classes={self.classes}" if self.classes else ""
        super().__init__(
            f"COPY_PROVIDER_DEFERRED until={self.until} reason={reason} notify={int(notify)}{suffix}"
        )


def _sanitize_classes(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_:,.\-]", "", value or "")[:240]


_DEFERRED_LINE = re.compile(
    r"^COPY_PROVIDER_DEFERRED until=(\d+) reason=(quota|unavailable|busy|cooldown|auth|timeout|rate_limit)"
    r" notify=([01])(?: classes=([A-Za-z0-9_:,.\-]+))?$",
    re.MULTILINE,
)


def match_copy_provider_deferred(detail: Union[str, bytes]):
    """解析文案延后协议。不认识的类别不能被当成普通失败丢掉。"""
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    return _DEFERRED_LINE.search(detail or "")


def _classify_failure_text(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in (
        "agy_auth_required", "authentication required", "not logged in", "login required",
    )):
        return "auth"
    if ("resource_exhausted" in lowered or "too many requests" in lowered
            or re.search(r"\b429\b", lowered) or "rate limit" in lowered):
        return "rate_limit"
    if any(token in lowered for token in ("quota", "usage limit", "insufficient credits")):
        return "quota"
    if "timed out" in lowered or "cli_timeout" in lowered or re.search(r"\btimeout\b", lowered):
        return "timeout"
    return "unavailable"


def classify_copy_provider_failure(exc: BaseException) -> str:
    """把供应商异常收成稳定类别；不回显密钥、正文或原始 CLI 日志。"""
    explicit = getattr(exc, "failure_class", None)
    mapped = _CODE_MAP.get(str(explicit).strip().lower()) if explicit else None
    if mapped:
        return mapped
    if isinstance(exc, CopyProviderDeferred):
        mapped = _CODE_MAP.get(str(exc.reason).strip().lower())
        if mapped:
            return mapped
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        mapped = _CODE_MAP.get(code.strip().lower())
        if mapped:
            return mapped
    return _classify_failure_text(str(exc))


def safe_copy_diagnostic(exc: BaseException) -> str:
    """只保留异常类型、失败类和允许的状态词。"""
    preset = getattr(exc, "safe_diagnostic", None)
    if isinstance(preset, str) and preset.strip():
        return preset.strip()[:180]
    klass = classify_copy_provider_failure(exc)
    raw = str(exc)
    markers = []
    for needle, label in _DIAGNOSTIC_MARKERS:
        if needle == "429":
            if re.search(r"\b429\b", raw):
                markers.append(label)
            continue
        if needle.lower() in raw.lower():
            markers.append(label)
    suffix = f" {' '.join(markers)}" if markers else ""
    return f"{type(exc).__name__}:{klass}{suffix}"[:180]


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
                stored = str(state.get("reason") or "cooldown")
                if stored not in _WIRE_REASONS:
                    stored = "cooldown"
                raise CopyProviderDeferred(int(state["until"]), stored)
        try:
            raw = run_agy_structured(
                prompt, schema=schema, model=model, command=command, timeout_sec=timeout_sec,
                environment=settings.agy_app_environment(),
            )
        except AgyProviderError as exc:
            failure_class = classify_copy_provider_failure(exc)
            reason = failure_class if failure_class in _WIRE_REASONS else "unavailable"
            delay = quota_cooldown_sec if reason in {"quota", "rate_limit"} else 300
            until = int(time.time()) + delay
            _atomic_json(cooldown, {"until": until, "reason": reason})
            raise CopyProviderDeferred(until, reason, notify=True) from exc
        result = validate(raw)
        _atomic_json(cached, raw)
        return result


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

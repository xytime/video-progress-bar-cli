"""字幕局部恢复的独立计划账本；仅保存宿主状态，不保存提示词或拒绝译文。

依赖：codex_subtitle_provider → 本模块 → codex_text_provider；不访问任务库或音频。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 为逐段恢复持久化有界请求、累计期限、降级位置与安全失败，独立文件锁保护续跑。 |
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

from .codex_text_provider import CodexTextError, _safe_quality_details


RECOVERY_RECIPE = "subtitle-singleton-recovery-v1"


class SubtitleRecoveryState:
    """同一来源计划串行领取；缓存读取不消耗预算，只有真实执行前预扣。"""

    def __init__(self, directory: Path, *, texts: list[str], context: str, model: str,
                 effort: str, batch_size: int, max_attempts: int, max_requests: int,
                 total_timeout: float, request_timeout: float):
        recipe = [RECOVERY_RECIPE, batch_size, max_attempts, "parent-first-rejection-to-singletons"]
        identity = json.dumps([texts, context, model, effort, recipe], ensure_ascii=False, sort_keys=True)
        self.identity = hashlib.sha256(identity.encode()).hexdigest()
        self.directory = directory / "subtitle-recovery"
        self.path = self.directory / f"{self.identity}.json"
        self.max_requests = max_requests
        self.total_timeout = total_timeout
        self.request_timeout = request_timeout
        self.data: dict = {}
        self._lock = None
        self._tick = 0.0

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = self.path.with_suffix(".lock").open("a+")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            self._lock = None
            raise CodexTextError("recovery_busy", int(time.time()) + 60) from None
        try:
            if self.path.exists():
                try:
                    self.data = json.loads(self.path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    raise CodexTextError("recovery_state_invalid") from None
                self._validate_state()
                active = self.data.get("active_window")
                if active:
                    # 异常退出只保守扣最后一次请求窗口；数小时离线不扩大为数小时消耗。
                    self.data["elapsed_seconds"] += min(
                        max(0.0, time.time() - active["started_at"]), active["allowance_seconds"])
                self.data["max_requests"] = min(self.data["max_requests"], self.max_requests)
                self.data["total_timeout"] = min(self.data["total_timeout"], self.total_timeout)
            else:
                self.data = {"identity": self.identity, "recipe": RECOVERY_RECIPE,
                             "max_requests": self.max_requests, "requests_used": 0,
                             "total_timeout": self.total_timeout, "elapsed_seconds": 0.0,
                             "split_batches": {}, "units": {}, "last_failure": None}
            self._tick = time.monotonic()
            self._write()
            return self
        except BaseException:
            self._lock.close()
            self._lock = None
            raise

    def _validate_state(self) -> None:
        try:
            valid = (self.data["identity"] == self.identity and self.data["recipe"] == RECOVERY_RECIPE
                     and type(self.data["requests_used"]) is int and self.data["requests_used"] >= 0
                     and type(self.data["max_requests"]) is int and self.data["max_requests"] > 0
                     and math.isfinite(self.data["elapsed_seconds"]) and 0 <= self.data["elapsed_seconds"]
                     and math.isfinite(self.data["total_timeout"]) and self.data["total_timeout"] > 0
                     and isinstance(self.data["split_batches"], dict) and isinstance(self.data["units"], dict))
            for unit in self.data["units"].values():
                valid = valid and type(unit["attempts_used"]) is int and 0 <= unit["attempts_used"] <= 2
            active = self.data.get("active_window")
            if active:
                valid = (valid and math.isfinite(active["started_at"]) and active["started_at"] >= 0
                         and math.isfinite(active["allowance_seconds"]) and active["allowance_seconds"] >= 0)
        except (KeyError, TypeError):
            valid = False
        if not valid:
            raise CodexTextError("recovery_state_invalid")

    def _write(self, *, closing: bool = False) -> None:
        now = time.monotonic()
        self.data["elapsed_seconds"] += max(0.0, now - self._tick)
        self._tick = now
        remaining = max(0.0, self.data["total_timeout"] - self.data["elapsed_seconds"])
        self.data["active_window"] = None if closing else {
            "started_at": time.time(), "allowance_seconds": min(self.request_timeout, remaining),
        }
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False, encoding="utf-8") as stream:
                temporary = Path(stream.name)
                json.dump(self.data, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def __exit__(self, exc_type, exc, traceback):
        try:
            self._write(closing=True)
        finally:
            self._lock.close()
            self._lock = None

    def remaining_seconds(self) -> float:
        return self.data["total_timeout"] - self.data["elapsed_seconds"] - max(0.0, time.monotonic() - self._tick)

    def split(self, offset: int, count: int) -> bool:
        return f"{offset}:{count}" in self.data["split_batches"]

    def mark_split(self, offset: int, count: int, error: CodexTextError) -> None:
        self.data["split_batches"][f"{offset}:{count}"] = self._failure(error)
        self._write()

    def previous_failure(self, source_id: int) -> dict | None:
        return self.data["units"].get(str(source_id), {}).get("last_failure")

    def before_execute(self, source_id: int | None = None) -> None:
        """调用方在缓存/冷却检查后调用；持久预扣使崩溃也不能退还真实请求。"""
        if self.remaining_seconds() <= 0:
            raise CodexTextError("total_timeout")
        if self.data["requests_used"] >= self.data["max_requests"]:
            raise CodexTextError("request_budget_exhausted")
        if source_id is not None:
            unit = self.data["units"].setdefault(str(source_id), {"attempts_used": 0})
            # 已接受的缓存后来丢失/被宿主拒绝时可有一次新的修复周期；全片余额绝不重置。
            if unit.get("accepted"):
                unit.update(attempts_used=0, accepted=False)
            if unit["attempts_used"] >= 2:
                failure = unit.get("last_failure") or {}
                code = failure.get("code", "")
                quality_rejected = (code == "invalid_output" or code in {"subtitle_ids", "subtitle_structure"}
                                    or code.startswith(("subtitle_quality_", "subtitle_vocab_alignment_")))
                if quality_rejected:
                    raise CodexTextError("subtitle_recovery_exhausted",
                                         quality_details=failure.get("quality_details", ()))
                # 执行预算耗尽不构成音频/ASR证据，保留原服务失败在账本供调度诊断。
                raise CodexTextError("request_budget_exhausted", failure.get("retry_at", 0))
            unit["attempts_used"] += 1
        self.data["requests_used"] += 1
        self._write()

    @staticmethod
    def _failure(error: CodexTextError) -> dict:
        return {"code": error.code[:160], "retry_at": error.retry_at,
                "quality_details": _safe_quality_details(error.quality_details)}

    def record_failure(self, error: CodexTextError, source_id: int | None = None) -> None:
        failure = self._failure(error)
        self.data["last_failure"] = failure
        if source_id is not None:
            unit = self.data["units"].setdefault(str(source_id), {"attempts_used": 0})
            unit["last_failure"] = failure
            unit["accepted"] = False
        self._write()

    def mark_accepted(self, source_id: int) -> None:
        unit = self.data["units"].setdefault(str(source_id), {"attempts_used": 0})
        unit["accepted"] = True
        self._write()

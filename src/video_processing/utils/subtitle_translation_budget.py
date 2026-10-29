"""字幕候选预算准入；依赖：processor/provider → 本模块 → 标准库。

初始成本是保守估计而非实测；只允许 Gemini/DeepSeek 用一个有界批次校准。
预算仅分配本次既有总期限，不创建恢复计划，也不修改供应商持久累计额度。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 按批成本准入、后备机会和全片质检预留。 |
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time


DEFAULT_BATCH_SECONDS = {'gemini': 30.0, 'deepseek': 30.0, 'google': 1.0,
                         'codex': 120.0, 'agy': 90.0}
BATCH_ROWS = {'gemini': 25, 'deepseek': 25, 'google': 1, 'codex': 5}


@dataclass(frozen=True)
class Admission:
    allowed: bool
    seconds: float
    estimated_seconds: float
    fallback_reserve: float
    probe: bool = False


class CandidateBudget:
    """调用者提供单调时钟余量；不依赖设置、数据库或业务执行。"""

    def __init__(self, rows, *, quality_reserve=120.0, batch_seconds=None):
        self.rows = rows
        self.quality_reserve = max(0.0, float(quality_reserve))
        self.costs = dict(DEFAULT_BATCH_SECONDS)
        for provider, value in (batch_seconds or {}).items():
            if provider in self.costs and math.isfinite(float(value)) and float(value) > 0:
                self.costs[provider] = float(value)

    def estimate(self, provider):
        batches = math.ceil(self.rows / BATCH_ROWS.get(provider, max(1, self.rows)))
        return batches * self.costs.get(provider, 90.0)

    def admit(self, provider, remaining, later=(), *, estimates=None):
        usable = max(0.0, remaining - self.quality_reserve)
        estimate = lambda item: (estimates or {}).get(item, self.estimate(item))
        # 保留下一条确有机会完成的后备；无需机械等分全部供应商。
        fallback = next((estimate(item) for item in later
                         if estimate(item) + min(estimate(provider), self.costs.get(provider, 90.0)) <= usable), 0.0)
        allocation = max(0.0, usable - fallback)
        required = estimate(provider)
        probe = provider in {'gemini', 'deepseek'} and allocation >= self.costs[provider]
        allowed = required <= allocation or probe
        return Admission(allowed, allocation if allowed else 0.0, required, fallback,
                         probe=allowed and required > allocation)


def transport_failure(error):
    """只分类已知传输异常；稳定错误码可安全写回执，不带 URL/正文。"""
    import http.client
    import urllib.error
    if isinstance(error, urllib.error.HTTPError):
        status = error.code
        category = 'quota' if status == 429 else ('authentication' if status in {401, 402, 403} else 'network')
        return dict(code=f'http_{status}', category=category)
    if isinstance(error, TimeoutError):
        return dict(code='transport_timeout', category='timeout')
    if isinstance(error, (http.client.HTTPException, urllib.error.URLError, ConnectionError)):
        return dict(code='transport_connection', category='network')
    return None


class TranslationAttemptLedger:
    """同语义计划累计计时；调用前预扣，崩溃后不归还未核实的预扣预算。"""

    def __init__(self, root, identity, total_seconds):
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                       allow_nan=False).encode()).hexdigest()
        self.directory = Path(root) / 'subtitle-attempt-budget-v1' / key
        self.path = self.directory / 'budget.json'
        self.limit = max(0.0, float(total_seconds))
        self.used, self.terminal = 0.0, False
        self.started = None

    @contextmanager
    def lease(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / 'budget.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                if self.path.exists():
                    try:
                        data = json.loads(self.path.read_text())
                        if (not isinstance(data, dict) or type(data['terminal']) is not bool
                                or any(type(data[key]) not in (int, float)
                                       or not math.isfinite(data[key]) or data[key] < 0
                                       for key in ('used_seconds', 'total_seconds'))):
                            raise ValueError('invalid cumulative budget')
                        # 完整校验后才赋值，不让损坏上限污染 fail-closed 的原始边界。
                        self.used = float(data['used_seconds'])
                        self.limit = min(self.limit, float(data['total_seconds']))
                        self.terminal = data['terminal']
                    except (OSError, ValueError, KeyError, TypeError):
                        # 损坏账本不能变成全新预算。
                        self.used, self.terminal = self.limit, True
                self.started = time.monotonic()
                yield self
            finally:
                if self.started is not None:
                    self.checkpoint()
                fcntl.flock(lock, fcntl.LOCK_UN)

    def remaining(self):
        return 0.0 if self.terminal else max(0.0, self.limit - self.used)

    def checkpoint(self, reserve=0.0):
        elapsed = max(0.0, time.monotonic() - self.started)
        payload = dict(version=1, total_seconds=self.limit,
                       used_seconds=min(self.limit, self.used + elapsed + max(0.0, reserve)),
                       terminal=self.terminal)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=self.directory, encoding='utf-8', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

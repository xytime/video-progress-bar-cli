"""完整字幕视觉分页的持久累计预算；独立于翻译或发布业务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 从已测累计账本提取原样实现；保留身份、预扣、崩溃和耗尽保护。 |
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time


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

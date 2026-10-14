"""持久化供应商冷却；调用方须持有该供应商的跨进程执行锁。

依赖：scripts -> provider_circuit -> 标准库。
"""
import json
import time
from pathlib import Path


class ProviderCircuit:
    def __init__(self, path, *, threshold=2, cooldown=900):
        self.path = Path(path)
        self.threshold = threshold
        self.cooldown = cooldown

    def read(self):
        if not self.path.exists():
            return {"failures": 0, "retry_at": 0}
        return json.loads(self.path.read_text())

    def blocked(self, now=None):
        return self.read()["retry_at"] > (time.time() if now is None else now)

    def record(self, success, now=None):
        now = time.time() if now is None else now
        old = self.read()
        failures = 0 if success else old["failures"] + 1
        state = {"failures": failures, "retry_at": now + self.cooldown
                 if failures >= self.threshold else 0, "checked_at": now}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(self.path)

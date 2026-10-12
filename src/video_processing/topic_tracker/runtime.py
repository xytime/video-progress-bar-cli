"""候选局部生命周期：初始化单飞、有界重试与脱敏健康记录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | v0.2.1 故障隔离及退出 OFF 未确认状态 |
"""
from __future__ import annotations

import threading
import time
from ..core.topic_candidates import TopicError


class TopicRuntime:
    def __init__(self, factory, *, monotonic=time.monotonic, clock=time.time):
        self.factory, self.monotonic, self.clock = factory, monotonic, clock
        self.mutex = threading.Lock()
        self.tracker = None
        self.retry_at = 0
        self.health = dict(initialized_at=None, cleaned_at=None, failed_at=None,
                           code=None, ready=False, stopped_off_confirmed=None)

    def failure(self, exc):
        if not self.health["ready"] and self.health["code"] == exc.code and self.monotonic() < self.retry_at:
            return
        self.health.update(failed_at=self.clock(), code=exc.code, ready=False)
        self.retry_at = self.monotonic() + 60

    def service(self):
        with self.mutex:
            if self.health["ready"]:
                return self.tracker
            if self.monotonic() < self.retry_at:
                raise TopicError(self.health["code"], "候选模块暂不可用，等待有界重试", 503)
            try:
                if self.tracker is None:
                    self.tracker = self.factory()
                else:
                    self.tracker.maintenance()
                    self.tracker.enforce_closed()
                self.health.update(initialized_at=self.clock(), cleaned_at=self.clock(), ready=True, code=None)
                return self.tracker
            except TopicError as exc:
                self.failure(exc)
                raise

    def clean(self):
        tracker = self.service()
        try:
            tracker.maintenance()
            self.health.update(cleaned_at=self.clock())
        except TopicError as exc:
            with self.mutex:
                self.failure(exc)
            raise

    def stop(self):
        tracker = self.tracker
        if tracker is None:
            self.health["stopped_off_confirmed"] = False
            return
        try:
            control = tracker.db.topic_control()
            tracker.db.topic_set_mode("OFF", control["version"], "host", tracker.clock())
            self.health["stopped_off_confirmed"] = tracker.db.topic_control()["mode"] == "OFF"
        except TopicError as exc:
            self.health["stopped_off_confirmed"] = False
            self.failure(exc)
        finally:
            try:
                tracker.wait()
            finally:
                self.health["ready"] = False
                if self.health["stopped_off_confirmed"]:
                    self.tracker = None

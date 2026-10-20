"""视频号账户级请求退避；跨作品、跨进程共享，拒绝请求不延长冷却。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 持久保存原生 -360/HTTP 429、会话间隔与指数退避；只记录脱敏端点及业务码。 |
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from config.settings import settings


class WeChatRequestDeferred(RuntimeError):
    """账户仍在退避，调用方不得启动平台请求。"""


def business_rate_limited(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    base = data.get("baseResp") if isinstance(data, dict) else None
    return any(type(layer.get(key)) is int and layer[key] == -360
               for layer in (payload, base) if isinstance(layer, dict)
               for key in ("errCode", "errcode", "ret"))


class WeChatRequestGuard:
    def __init__(self, state_path: str | Path):
        state = Path(state_path).expanduser().resolve(strict=False)
        self.path = state.with_name(f".{state.name}.requests.json")
        self.audit_path = state.with_name(f".{state.name}.requests.jsonl")

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "blocked_until": 0, "next_session_at": 0, "failure_streak": 0}
        try:
            row = json.loads(self.path.read_text(encoding="utf-8"))
            if (row.get("version") != 1 or type(row.get("failure_streak")) is not int
                    or not 0 <= row["failure_streak"] <= 6):
                raise ValueError("version or failure_streak")
            for key in ("blocked_until", "next_session_at", "failure_streak"):
                value = row[key]
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(key)
            return row
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise WeChatRequestDeferred("视频号共享退避记录不可验证，停止请求") from exc

    def _save(self, row, event):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)
        with self.audit_path.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps(dict(event, at=time.time(), pid=os.getpid()), ensure_ascii=False) + "\n")

    @staticmethod
    def _check(row, now):
        until = max(row["blocked_until"], row["next_session_at"])
        if now < until:
            raise WeChatRequestDeferred(f"视频号账户退避中，最早 {until:.0f}，禁止平台请求")

    def check(self):
        with self._locked():
            self._check(self._read(), time.time())

    def snapshot(self):
        with self._locked():
            return self._read()

    def start_session(self, purpose):
        with self._locked():
            row, now = self._read(), time.time()
            self._check(row, now)
            row.update(last_session_at=now, next_session_at=now + settings.wechat_request_min_interval_seconds)
            self._save(row, {"event": "SESSION_STARTED", "purpose": purpose})

    def record_limited(self, *, endpoint, code=-360, evidence="native_response"):
        with self._locked():
            row, now = self._read(), time.time()
            # 同一限流事件的多个响应或重复导入不能滚动延长，也不增加退避级数。
            if now < row["blocked_until"]:
                return
            streak = min(int(row["failure_streak"]) + 1, 6)
            seconds = min(settings.wechat_rate_limit_cooldown_seconds * 2 ** (streak - 1), 21600)
            row.update(blocked_until=now + seconds, last_limited_at=now,
                       failure_streak=streak, business_code=code, reason="PLATFORM_RATE_LIMITED")
            self._save(row, {"event": "RATE_LIMITED", "endpoint": endpoint, "code": code,
                             "evidence": evidence, "blocked_until": row["blocked_until"]})

    def observe_response(self, response):
        """只信任官方原生业务响应；不保存 URL 查询参数、正文或凭证。"""
        url = urlsplit(response.url)
        if (url.scheme != "https" or url.hostname != "channels.weixin.qq.com"
                or "/cgi-bin/mmfinderassistant-bin/" not in url.path):
            return False
        if response.status == 429:
            self.record_limited(endpoint=url.path, code=429)
            return True
        try:
            payload = response.json()
        except Exception:
            return False
        if business_rate_limited(payload):
            self.record_limited(endpoint=url.path)
            return True
        # 只有原生作品列表的内外层成功能清除失败级数；其他接口成功没有恢复证明力。
        if url.path.endswith("/post/post_list") and isinstance(payload, dict):
            data = payload.get("data")
            base = data.get("baseResp") if isinstance(data, dict) else None
            if (isinstance(data, dict) and isinstance(data.get("list"), list) and isinstance(base, dict)
                    and type(payload.get("errCode")) is int and payload["errCode"] == 0
                    and type(base.get("errcode")) is int and base["errcode"] == 0
                    and all(type(layer[key]) is int and layer[key] == 0
                            for layer in (payload, base) for key in ("errCode", "errcode", "ret") if key in layer)):
                with self._locked():
                    row = self._read()
                    if row["failure_streak"] and time.time() >= row["blocked_until"]:
                        row.update(failure_streak=0, blocked_until=0, reason="NATIVE_LIST_RECOVERED")
                        self._save(row, {"event": "RECOVERED", "endpoint": url.path})
        return False

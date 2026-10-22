"""视频号账户级请求退避；跨作品、跨进程共享，拒绝请求不延长冷却。

| manual-login-v1 | 2026-10-22 | Codex | 人工单次扫码恢复保留账户互斥与限流即停，不恢复发布队列。 |

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| scheduler-v1 | 2026-10-21 | Codex | 关闭旧作品自动查询，接入账户统一降频和有界核对。 |
| 1.0.0 | 2026-10-20 | Codex | 持久保存原生 -360/HTTP 429、会话间隔与指数退避；只记录脱敏端点及业务码。 |
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import hashlib
import math
import os
from pathlib import Path
import time
import uuid
from urllib.parse import urlsplit

from config.settings import settings
from .wechat_account_schedule import admission


class WeChatRequestDeferred(RuntimeError):
    """账户仍在退避，调用方不得启动平台请求。"""


class WeChatCooldownDeferred(WeChatRequestDeferred):
    """可确认跳过的本地冷却；不包含损坏记录或浏览器占用。"""


def business_rate_limited(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    base = data.get("baseResp") if isinstance(data, dict) else None
    return any(type(layer.get(key)) is int and layer[key] == -360
               for layer in (payload, base) if isinstance(layer, dict)
               for key in ("errCode", "errcode", "ret"))


def account_state_path(state_path):
    """统一调度按本项目账户计费，临时/复制登录态不能分裂冷却和浏览器锁。"""
    state = settings.default_output_dir / "wechat_state.json" if settings.wechat_account_scheduler_enabled else Path(state_path)
    return state.expanduser().resolve(strict=False)


class WeChatRequestGuard:
    def __init__(self, state_path: str | Path):
        state = account_state_path(state_path)
        self.path = state.with_name(f".{state.name}.requests.json")
        self.audit_path = state.with_name(f".{state.name}.requests.jsonl")
        self._override_generation = None
        self._limited_recorded = False
        self._manual_login = False
        self.purpose = ""
        self.task = ""
        self.caller = ""
        self.metadata = {}

    @staticmethod
    def _generation(row):
        return (row["blocked_until"], row.get("last_limited_at", 0), row["next_session_at"])

    @staticmethod
    def _version(row):
        values = [row["blocked_until"], row["next_session_at"],
                  row.get("last_limited_at", 0), row["failure_streak"]]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def cooldown(self):
        """仅返回可展示字段，不暴露单次执行凭据。"""
        with self._locked():
            row = self._read()
            until = max(row["blocked_until"], row["next_session_at"])
            remaining = max(0, math.ceil(until - time.time()))
            limited = row["blocked_until"] >= row["next_session_at"] and remaining > 0
            return {"active": remaining > 0, "until": until,
                    "remaining_seconds": remaining, "version": self._version(row),
                    "business_code": row.get("business_code") if limited else None,
                    "reason": "视频号返回限流" if limited else "账号会话最小间隔"}

    def issue_override(self, video, version):
        """将显式确认绑定当前冷却版本和单个任务；不清除共享冷却。"""
        with self._locked():
            row, now = self._read(), time.time()
            if not video or version != self._version(row):
                raise WeChatRequestDeferred("冷却状态已变化，请重新确认")
            grants = {key: value for key, value in row.get("manual_overrides", {}).items()
                      if value["expires_at"] > now and value["video"] != video}
            token = uuid.uuid4().hex
            grants[hashlib.sha256(token.encode()).hexdigest()] = {
                "video": video, "expires_at": now + 900,
                "generation": list(self._generation(row))}
            row["manual_overrides"] = grants
            self._save(row, {"event": "COOLDOWN_OVERRIDE_ISSUED", "video": video})
            return token

    def issue_manual_login(self):
        """显式人工入口签发十五分钟单次许可；重复点击不会反复开启后台。"""
        with self._locked():
            row, now = self._read(), time.time()
            if now < row.get("manual_login_issued_at", 0) + 900:
                raise WeChatRequestDeferred("手动登录已申请，请等待当前扫码流程；十五分钟内不重复启动")
            token = uuid.uuid4().hex
            row.setdefault("manual_overrides", {})[hashlib.sha256(token.encode()).hexdigest()] = {
                "video": "__manual_login__", "expires_at": now + 900,
                "generation": list(self._generation(row))}
            row["manual_login_issued_at"] = now
            self._save(row, {"event": "MANUAL_LOGIN_ISSUED"})
            return token

    def consume_manual_login(self, token):
        self.consume_override(token, "__manual_login__")
        self._manual_login = True
        self.purpose, self.task = "登录", "manual-login"

    def revoke_override(self, token):
        with self._locked():
            row = self._read()
            grant = row.get("manual_overrides", {}).pop(hashlib.sha256(token.encode()).hexdigest(), None)
            if grant:
                self._save(row, {"event": "COOLDOWN_OVERRIDE_REVOKED", "video": grant["video"]})

    def consume_override(self, token, video):
        """只在取得浏览器互斥锁后消费；过期、跨任务和重放均拒绝。"""
        with self._locked():
            row = self._read()
            key = hashlib.sha256(token.encode()).hexdigest()
            grant = row.get("manual_overrides", {}).get(key)
            if (not grant or grant["video"] != video or grant["expires_at"] <= time.time()
                    or tuple(grant["generation"]) != self._generation(row)):
                raise WeChatRequestDeferred("单次跳过已失效或冷却已更新，请重新确认")
            del row["manual_overrides"][key]
            self._override_generation = self._generation(row)
            self._limited_recorded = False
            self._save(row, {"event": "COOLDOWN_OVERRIDE_CONSUMED", "video": video})

    def _check_session(self, row, now):
        if ((self._manual_login or not settings.wechat_account_scheduler_enabled) and self._override_generation is not None
                and self._override_generation == self._generation(row)):
            return
        self._check(row, now)

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
            grants = row.get("manual_overrides", {})
            if not isinstance(grants, dict):
                raise ValueError("manual_overrides")
            for grant in grants.values():
                if (not isinstance(grant, dict) or not isinstance(grant.get("video"), str)
                        or type(grant.get("expires_at")) not in (int, float)
                        or not math.isfinite(grant["expires_at"])
                        or not isinstance(grant.get("generation"), list)
                        or len(grant["generation"]) != 3
                        or any(type(v) not in (int, float) or not math.isfinite(v)
                               for v in grant["generation"])):
                    raise ValueError("manual_override")
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
            raise WeChatCooldownDeferred(f"视频号账户冷却中，最早 {until:.0f}，禁止平台请求")

    def check(self):
        with self._locked():
            self._check_session(self._read(), time.time())

    def snapshot(self):
        with self._locked():
            return self._read()

    def admission(self, purpose, task, caller=""):
        self.purpose, self.task, self.caller = purpose, task, caller
        if not settings.wechat_account_scheduler_enabled:
            return
        with self._locked():
            row, now = self._read(), time.time()
            self._check(row, now)  # 调度策略不接受跳过冷却凭据。
            reason = admission(row, now, purpose, task)
            self._save(row, {"event": "QUEUED" if not reason else "DEFERRED",
                             "purpose": purpose, "task": task, "caller": caller, "reason": reason})
            if reason:
                raise WeChatRequestDeferred(reason)

    def bind_publication(self, native_id, receipt_path=""):
        if not settings.wechat_account_scheduler_enabled or not native_id or self.purpose != "发布":
            return
        with self._locked():
            row = self._read()
            schedule = row.get("schedule", {})
            if not any(s["task"] == self.task for s in schedule.get("sessions", [])):
                return
            if self.task == settings.wechat_scheduler_priority_video:
                schedule["priority_bound"] = True
            schedule.setdefault("publications", {}).setdefault(str(native_id),
                {"at": time.time(), "checks": 0, "task": self.task,
                 "receipt_path": str(receipt_path), "metadata": self.metadata,
                 "heartbeat_managed": self.task == settings.wechat_scheduler_priority_video})
            self._save(row, {"event": "SUBMISSION_BOUND", "task": self.task, "native_id": str(native_id)})

    def record_publication_state(self, native_id, state):
        with self._locked():
            row = self._read()
            publication = row.get("schedule", {}).get("publications", {}).get(native_id)
            if publication is None:
                raise WeChatRequestDeferred("原生 ID 未绑定本次投稿")
            publication["state"] = state
            self._save(row, {"event": "PUBLICATION_OBSERVED", "native_id": native_id, "state": state})

    def mark_submit_intent(self):
        if not settings.wechat_account_scheduler_enabled:
            return
        with self._locked():
            row = self._read()
            intents = row.setdefault("schedule", {}).setdefault("submit_intents", {})
            if self.task in intents:
                raise WeChatRequestDeferred("已有提交意图，拒绝重复发表")
            intents[self.task] = time.time()
            self._save(row, {"event": "SUBMIT_INTENT", "task": self.task})

    def end_session(self, requests=0, list_requests=0):
        with self._locked():
            row = self._read()
            self._save(row, {"event": "SESSION_ENDED", "task": self.task, "purpose": self.purpose,
                             "caller": self.caller, "requests": requests, "list_requests": list_requests, "next_session_at": row["next_session_at"]})

    def start_session(self, purpose):
        with self._locked():
            row, now = self._read(), time.time()
            self._check_session(row, now)
            if self._manual_login:
                if purpose != "登录":
                    raise WeChatRequestDeferred("人工登录许可不能用于其他操作")
                schedule = row.setdefault("schedule", {"queue": [], "sessions": [], "publications": {}})
                schedule["sessions"].append({"at": now, "purpose": "登录", "task": self.task})
            elif settings.wechat_account_scheduler_enabled:
                self._check(row, now)
                reason = admission(row, now, purpose, self.task, consume=True)
                if reason:
                    self._save(row, {"event": "DEFERRED", "reason": reason, "task": self.task})
                    raise WeChatRequestDeferred(reason)
            row.update(last_session_at=now, next_session_at=max(row["next_session_at"], now + settings.wechat_request_min_interval_seconds))
            if self._override_generation is not None:
                self._override_generation = self._generation(row)
            self._save(row, {"event": "SESSION_STARTED", "purpose": purpose, "task": self.task, "caller": self.caller})

    def record_limited(self, *, endpoint, code=-360, evidence="native_response"):
        with self._locked():
            row, now = self._read(), time.time()
            # 同一限流事件的多个响应或重复导入不能滚动延长，也不增加退避级数。
            if now < row["blocked_until"] and (self._override_generation is None or self._limited_recorded):
                return
            self._limited_recorded = True
            streak = min(int(row["failure_streak"]) + 1, 6)
            seconds = min(settings.wechat_rate_limit_cooldown_seconds * 2 ** (streak - 1), 21600)
            if settings.wechat_account_scheduler_enabled:
                seconds = max(seconds, 86400)
                row.get("schedule", {}).pop("recovery_started", None)
            row.update(blocked_until=max(row["blocked_until"], now + seconds), last_limited_at=now,
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

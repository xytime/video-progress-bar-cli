"""视频号账户级请求退避；跨作品、跨进程共享，拒绝请求不延长冷却。

| manual-login-v1 | 2026-10-22 | Codex | 人工单次扫码恢复保留账户互斥与限流即停，不恢复发布队列。 |

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| operations-v1 | 2026-10-24 | Codex | 分用途滚动预算与安全有界重试接入，保留既有提交事实与内容保护。 |
| recovery-console-v1 | 2026-10-23 | Codex | 公开纯准入快照与有版本、幂等、原生互斥保护的本地额度／冷却恢复。 |
| 1.1.0 | 2026-10-22 | Antigravity | 接入视频号调度策略 mtime 热加载，并支持绑定任务的单次跳过凭据穿过会话间隔与配额等待。 |
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
from ..utils.wechat_scheduler_policy import sync_wechat_scheduler_settings
from .wechat_account_schedule import admission, evaluate
from ..utils.wechat_operations_policy import WeChatRequestDeferred, load_policy, revision


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
    sync_wechat_scheduler_settings()
    state = settings.default_output_dir / "wechat_state.json" if (settings.wechat_account_scheduler_enabled or settings.wechat_operations_enabled) else Path(state_path)
    return state.expanduser().resolve(strict=False)


class WeChatRequestGuard:
    def __init__(self, state_path: str | Path):
        sync_wechat_scheduler_settings()
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
        self.attempt_id = uuid.uuid4().hex

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
        sync_wechat_scheduler_settings()
        with self._locked():
            row = self._read()
            until = max(row["blocked_until"], row["next_session_at"])
            remaining = max(0, math.ceil(until - time.time()))
            limited = row["blocked_until"] >= row["next_session_at"] and remaining > 0
            return {"active": remaining > 0, "until": until,
                    "remaining_seconds": remaining, "version": self._version(row),
                    "business_code": row.get("business_code") if limited else None,
                    "reason": "视频号返回限流" if limited else "账号会话最小间隔"}

    def acknowledge_unfrozen(self, version):
        """仅供操作者明确确认平台解冻后调用；保留历史、正常间隔及投稿去重。"""
        sync_wechat_scheduler_settings()
        with self._locked():
            row, now = self._read(), time.time()
            if version != self._version(row):
                raise WeChatRequestDeferred("账号状态已变化，不能解除新的限流")
            previous_until = row["blocked_until"]
            row["blocked_until"] = 0
            row["next_session_at"] = max(
                row.get("last_session_at", 0) + settings.wechat_scheduler_stable_interval_seconds,
                now,
            )
            row.setdefault("schedule", {"queue": [], "sessions": [], "publications": {}})["recovery_started"] = now - 86400
            row["manual_overrides"] = {}
            row["reason"] = "OPERATOR_CONFIRMED_UNFROZEN"
            self._save(row, {"event": "OPERATOR_CONFIRMED_UNFROZEN",
                             "previous_blocked_until": previous_until,
                             "last_limited_at": row.get("last_limited_at", 0)})

    def issue_override(self, video, version, *, full_state=False):
        """将显式确认绑定当前冷却版本和单个任务；不清除共享冷却。"""
        with self._locked():
            row, now = self._read(), time.time()
            if not video or version != (self.recovery_version(row) if full_state else self._version(row)):
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

    def _has_override(self, row) -> bool:
        return self._override_generation is not None and self._override_generation == self._generation(row)

    def _check_session(self, row, now):
        if settings.wechat_operations_enabled:
            return self._check(row, now)
        if self._has_override(row):
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
            schedule = row.get("schedule", {})
            for name in ("sessions", "queue", "recovery_priority"):
                values = schedule.get(name, [])
                if not isinstance(values, list):
                    raise ValueError(name)
                for value in values:
                    keys = ("at",) if name == "sessions" else (("at", "seen") if name == "queue" else ("expires_at",))
                    if not isinstance(value, dict) or any(type(value.get(k)) not in (int, float) or not math.isfinite(value[k]) for k in keys):
                        raise ValueError(name)
                    if not isinstance(value.get("task"), str) or (name != "recovery_priority" and not isinstance(value.get("purpose"), str)):
                        raise ValueError(name)
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
        policy = load_policy()
        until = row["blocked_until"] if policy is not None else max(row["blocked_until"], row["next_session_at"])
        if now < until:
            raise WeChatCooldownDeferred(f"视频号账户冷却中，最早 {until:.0f}，禁止平台请求")

    def check(self):
        with self._locked():
            self._check_session(self._read(), time.time())

    def snapshot(self):
        with self._locked():
            return self._read()

    @staticmethod
    def recovery_version(row):
        """完整本地状态版本；任何新会话、新限流或凭据变化均使旧确认失效。"""
        return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def evaluate(self, purpose="发布", task="", *, account_only=False):
        sync_wechat_scheduler_settings()
        with self._locked():
            row = self._read()
            return {**evaluate(row, time.time(), purpose, task, account_only=account_only),
                    "version": self.recovery_version(row), "failure_streak": row["failure_streak"],
                    "last_limited_at": row.get("last_limited_at"),
                    "queue_count": len(row.get("schedule", {}).get("queue", []))}

    def admission_view(self, task):
        """兼容单片确认和队列展示的准入视图；全部阻塞来自同一纯计算。"""
        sync_wechat_scheduler_settings()
        with self._locked():
            row, now = self._read(), time.time()
            info = evaluate(row, now, task=task)
            until = info["until"]
            return {**info, "active": not info["allowed"], "version": self.recovery_version(row),
                    "remaining_seconds": max(0, math.ceil(until-now)) if until else None,
                    "business_code": row.get("business_code") if row["blocked_until"] > now else None,
                    "reason": "；".join(b["reason"] for b in info["blockers"]) or "本地账户限制已满足"}

    def recover_local(self, *, operation_id, expected_version, reset_quota=False,
                      reset_cooldown=False, priority_tasks=()):
        """只恢复操作者确认的本地限制；状态文件与浏览器均持原生锁，重放返回原回执。"""
        if not operation_id or len(operation_id) > 80:
            raise ValueError("缺少有效操作 ID")
        browser_path = self.path.with_name(self.path.name.replace(".requests.json", ".browser.lock"))
        browser_path.parent.mkdir(parents=True, exist_ok=True)
        with browser_path.open("a+") as browser:
            try:
                fcntl.flock(browser, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WeChatRequestDeferred("真实浏览器会话正在使用账号，请等待释放后恢复") from exc
            with self._locked():
                row, now = self._read(), time.time()
                receipts = row.get("recovery_operations", {})
                if operation_id in receipts:
                    return receipts[operation_id]
                if expected_version != self.recovery_version(row):
                    raise WeChatRequestDeferred("账号状态已变化，请刷新预览后重新确认；未重置任何限制")
                before = evaluate(row, now, account_only=True)
                state = row.setdefault("schedule", {"queue": [], "sessions": [], "publications": {}})
                if reset_quota:
                    state.update(quota_epoch=operation_id, quota_reset_at=now)
                if reset_cooldown:
                    row.update(blocked_until=0, next_session_at=0, failure_streak=0,
                               reason="OPERATOR_LOCAL_RECOVERY")
                    state.update(recovery_started=now - 86401, interval_reset_at=now)
                    row["manual_overrides"] = {}
                if priority_tasks:
                    state["recovery_priority"] = [p for p in state.get("recovery_priority", []) if p["expires_at"] > now] + [
                        {"task": task, "expires_at": now + 1800, "operation_id": operation_id}
                        for task in dict.fromkeys(priority_tasks)]
                after = evaluate(row, now, account_only=True)
                receipt = {"operation_id": operation_id, "at": now,
                           "reset_quota": reset_quota, "reset_cooldown": reset_cooldown,
                           "priority_count": len(priority_tasks),
                           "before": before, "after": after}
                row.setdefault("recovery_operations", {})[operation_id] = receipt
                self._save(row, {"event": "OPERATOR_LOCAL_RECOVERY", **receipt})
                return receipt

    def cancel_recovery_priority(self, operation_id):
        """取消仅撤回该批次尚未消费的优先位置，不回滚账户状态。"""
        with self._locked():
            row = self._read()
            state = row.get("schedule", {})
            old = state.get("recovery_priority", [])
            remaining = [p for p in old if p.get("operation_id") != operation_id]
            if remaining != old:
                state["recovery_priority"] = remaining
                self._save(row, {"event": "RECOVERY_PRIORITY_CANCELLED", "operation_id": operation_id})

    def admission(self, purpose, task, caller=""):
        sync_wechat_scheduler_settings()
        self.purpose, self.task, self.caller = purpose, task, caller
        if not (settings.wechat_account_scheduler_enabled or settings.wechat_operations_enabled):
            return
        with self._locked():
            row, now = self._read(), time.time()
            bypass = self._has_override(row)
            if not bypass:
                self._check(row, now)
            reason = admission(row, now, purpose, task, bypass_cooldown=bypass)
            self._save(row, {"event": "QUEUED" if not reason else "DEFERRED",
                             "purpose": purpose, "task": task, "caller": caller, "reason": reason})
            if reason:
                raise WeChatRequestDeferred(reason)

    def bind_publication(self, native_id, receipt_path=""):
        if not (settings.wechat_account_scheduler_enabled or settings.wechat_operations_enabled) or not native_id or self.purpose != "发布":
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
        if not (settings.wechat_account_scheduler_enabled or settings.wechat_operations_enabled):
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
        sync_wechat_scheduler_settings()
        with self._locked():
            row, now = self._read(), time.time()
            self._check_session(row, now)
            if self._manual_login:
                if purpose != "登录":
                    raise WeChatRequestDeferred("人工登录许可不能用于其他操作")
                schedule = row.setdefault("schedule", {"queue": [], "sessions": [], "publications": {}})
                schedule["sessions"].append({"at": now, "purpose": "登录", "task": self.task, "quota_epoch": schedule.get("quota_epoch", "legacy")})
            elif settings.wechat_account_scheduler_enabled or settings.wechat_operations_enabled:
                bypass = self._has_override(row)
                if not bypass:
                    self._check(row, now)
                reason = admission(row, now, purpose, self.task, consume=True, bypass_cooldown=bypass)
                if reason:
                    self._save(row, {"event": "DEFERRED", "reason": reason, "task": self.task})
                    raise WeChatRequestDeferred(reason)
            row["last_session_at"] = now
            policy = load_policy()
            if policy is None:
                row["next_session_at"] = max(row["next_session_at"], now + settings.wechat_request_min_interval_seconds)
            elif not self._manual_login:
                row["schedule"]["sessions"][-1]["attempt_id"] = self.attempt_id
            if self._override_generation is not None:
                self._override_generation = self._generation(row)
            self._save(row, {"event": "SESSION_STARTED", "purpose": purpose, "task": self.task, "caller": self.caller,
                             "attempt_id": self.attempt_id, "policy_revision": revision(policy) if policy else None})

    def record_limited(self, *, endpoint, code=-360, evidence="native_response"):
        sync_wechat_scheduler_settings()
        with self._locked():
            row, now = self._read(), time.time()
            # 同一限流事件的多个响应或重复导入不能滚动延长，也不增加退避级数。
            if now < row["blocked_until"] and (self._override_generation is None or self._limited_recorded):
                return
            self._limited_recorded = True
            streak = min(int(row["failure_streak"]) + 1, 6)
            seconds = min(settings.wechat_rate_limit_cooldown_seconds * 2 ** (streak - 1), 21600)
            if settings.wechat_account_scheduler_enabled or settings.wechat_operations_enabled:
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

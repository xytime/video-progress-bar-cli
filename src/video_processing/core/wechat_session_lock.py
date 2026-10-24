"""视频号浏览器会话的跨进程排他锁。

| manual-login-v1 | 2026-10-22 | Codex | 人工单次扫码恢复保留账户互斥与限流即停，不恢复发布队列。 |

锁文件由 Playwright storage-state 的规范化绝对路径唯一派生，确保上传、
保活和评论适配器不会同时使用或改写同一份登录态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| operations-v1 | 2026-10-24 | Codex | 分用途滚动预算与安全有界重试接入，保留既有提交事实与内容保护。 |
| publishing-recovery-v1 | 2026-10-23 | Codex | 接入发布恢复控制台，复用统一准入并保留任务和投稿保护。 |
| interaction-recovery-v1 | 2026-10-23 | Codex | 按上下文与闭环双层约束列表预算，保留原生限流即停。 |
| scheduler-v1 | 2026-10-21 | Codex | 关闭旧作品自动查询，接入账户统一降频和有界核对。 |
| 1.4.0 | 2026-10-20 | Codex | 会话入口遵守账户共享冷却；上下文首个请求前登记会话并捕获所有原生限流响应。 |
| 1.3.0 | 2026-10-18 | Antigravity | 新增 SessionLockStatus 与 inspect_wechat_session_lock 结构化判锁接口，消除空字典恒真陷阱。 |
| 1.2.0 | 2026-10-12 | Codex | 浏览器资源等待登记与拿锁后的维护重检，保留已运行同项续接。 |
| 1.1.0 | 2026-09-23 | Codex | 所有上传入口强制会话互斥，公开占用归属并让待发布优先。 |
| 1.0.0 | 2026-09-19 | Codex | 新增 state-path 派生的有界非阻塞跨进程会话锁与脚本装饰器。 |
"""

from __future__ import annotations

import fcntl
import functools
import inspect
import time
import json
import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone

from .task_lease import read_lease_owner
from .maintenance import gate, current
from .wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred, WeChatCooldownDeferred, account_state_path
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar


P = ParamSpec("P")
R = TypeVar("R")
EXIT_WECHAT_SESSION_BUSY = 11  # 未进入被保护函数，更未启动浏览器或发表。
EXIT_WECHAT_COOLDOWN = 15
EXIT_WECHAT_OVERRIDE_INVALID = 16
EXIT_WECHAT_ACCOUNT_DEFERRED = 17
_SESSION: ContextVar = ContextVar("wechat_request_session", default=None)


def current_wechat_session():
    return _SESSION.get()


def record_current_wechat_login_required():
    """只记录业务页面已明确出现的登录提示；当前许可代际 CAS，绝不额外发起探测。"""
    from config.settings import settings
    session = _SESSION.get()
    if session is not None and settings.wechat_operations_enabled:
        from .wechat_auth_state import record_wechat_keepalive_result
        record_wechat_keepalive_result(account_state_path(session.state_path), status="LOGIN_REQUIRED",
                                       expected_generation=getattr(session, "_credential_generation", None))


def guard_wechat_context(context):
    """在任何页面导航前挂监听；临时复用上下文沿用当前同一账户的请求预算。"""
    session = _SESSION.get()
    if session is None:
        from config.settings import settings
        if settings.wechat_account_scheduler_enabled or settings.wechat_operations_enabled:
            raise WeChatSessionLockBusy("没有账户调度许可，禁止打开视频号页面")
        return
    if session._request_limited:
        raise WeChatSessionLockBusy("当前视频号会话已收到限流，禁止创建后续上下文")
    if not session._request_started:
        from .wechat_auth_state import read_wechat_auth_state
        session._credential_generation = read_wechat_auth_state(account_state_path(session.state_path)).get("credential_generation")
        try:
            session.request_guard.start_session(session.purpose)
        except WeChatRequestDeferred as exc:
            raise WeChatAccountDeferred(str(exc)) from exc
        session._request_started = True
    context._wechat_rate_limit_seen = False
    context._wechat_list_request_count = 0
    context_list_requests = 0

    def response_received(response):
        if session.request_guard.observe_response(response):
            session._request_limited = True
            context._wechat_rate_limit_seen = True
            context._wechat_rate_limit_code = session.request_guard.snapshot()["business_code"]

    def request_started(request):
        if "channels.weixin.qq.com/" in request.url:
            session._request_count += 1

    def route_request(route):
        nonlocal context_list_requests
        if session._request_limited:
            route.abort()
            return
        from urllib.parse import urlsplit
        path = urlsplit(route.request.url).path
        if path.endswith("/post/post_list"):
            from config.settings import settings
            budget = (settings.wechat_interaction_list_request_budget
                      if session.purpose in {"评论", "首评", "回复", "评论扫描", "作品匹配"} else 2)
            contexts = {"评论": 2, "首评": 2, "回复": 3}.get(session.purpose, 1)
            if session.purpose == "评论扫描":
                from ..utils.wechat_operations_policy import load_policy
                policy = load_policy()
                contexts = policy["operations"]["comment_scan"]["max_videos_per_run"] if policy else 1
            if context_list_requests >= budget or session._list_request_count >= budget * contexts:
                route.abort()
                return
            context_list_requests += 1
            context._wechat_list_request_count = context_list_requests
            session._list_request_count += 1
        route.continue_()

    if callable(getattr(context, "route", None)):
        context.route("https://channels.weixin.qq.com/**", route_request)
    context.on("request", request_started)
    context.on("response", response_received)


def mark_current_wechat_submit_intent():
    session = _SESSION.get()
    if session is not None:
        session.request_guard.mark_submit_intent()


def bind_current_wechat_publication(native_id, receipt_path=""):
    session = _SESSION.get()
    if session is not None:
        session.request_guard.bind_publication(native_id, receipt_path)


@dataclass(frozen=True)
class SessionLockStatus:
    """视频号浏览器会话锁状态快照。"""

    locked: bool
    owner: dict[str, Any]
    lock_path: Path


class WeChatSessionLockBusy(RuntimeError):
    """同一份视频号登录态当前正由另一个浏览器会话占用。"""


class WeChatSessionCooldown(WeChatSessionLockBusy):
    """本地账户冷却，区别于真实浏览器互斥。"""


class WeChatAccountDeferred(WeChatSessionLockBusy):
    """额度、排队或账号记录阻塞，不冒充浏览器占用。"""


class WeChatOverrideInvalid(WeChatSessionLockBusy):
    """单次授权不可消费，必须重新人工确认。"""


def canonical_wechat_session_lock_path(state_path: str | Path) -> Path:
    """从登录态文件的规范化绝对路径派生唯一锁文件。"""
    state_file = account_state_path(state_path)
    return state_file.with_name(f".{state_file.name}.browser.lock")


def inspect_wechat_session_lock(
    state_path: str | Path = "output/wechat_state.json",
) -> SessionLockStatus:
    """只读检查视频号浏览器会话锁占用状态，返回显式 locked 布尔字段。"""
    lock_path = canonical_wechat_session_lock_path(state_path)
    owner = read_lease_owner(lock_path)
    return SessionLockStatus(
        locked=bool(owner),
        owner=owner if isinstance(owner, dict) else {},
        lock_path=lock_path,
    )


class WeChatSessionLock:
    """基于 ``flock`` 的有界轮询排他锁；进程退出后由内核自动释放。"""

    def __init__(
        self,
        state_path: str | Path,
        *,
        timeout_seconds: float = 0.0,
        poll_interval_seconds: float = 0.05,
        purpose: str = "浏览器操作",
        video: str = "",
        cooldown_override: str = "",
        manual_login_token: str = "",
    ) -> None:
        self.state_path = Path(state_path).expanduser().resolve(strict=False)
        self.lock_path = canonical_wechat_session_lock_path(self.state_path)
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self._handle = None
        self.purpose = purpose
        self.video = video
        self.manual_login_token = manual_login_token
        self.cooldown_override = cooldown_override
        self.request_guard = WeChatRequestGuard(self.state_path)
        self._request_started = False
        self._request_count = 0
        self._list_request_count = 0
        self._request_limited = False
        self._context_token = None

    def acquire(self) -> "WeChatSessionLock":
        """在截止时间内尝试获取锁，超时即抛出可识别的 busy 异常。"""
        if not self.manual_login_token and self.purpose not in {"发布", "状态核对"} and read_lease_owner(self.state_path.parent / "wechat_publish_priority.lock"):
            raise WeChatSessionLockBusy("待发布任务优先；评论/保活本轮让出浏览器")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                if self.manual_login_token:
                    if self.purpose != "登录" or self.cooldown_override:
                        raise WeChatOverrideInvalid("人工登录许可仅可用于登录")
                    try:
                        self.request_guard.consume_manual_login(self.manual_login_token)
                    except WeChatRequestDeferred as exc:
                        raise WeChatOverrideInvalid(str(exc)) from exc
                if self.cooldown_override:
                    try:
                        self.request_guard.consume_override(self.cooldown_override, self.video)
                    except WeChatRequestDeferred as exc:
                        raise WeChatOverrideInvalid(str(exc)) from exc
                try:
                    self.request_guard.check()
                    if self.video and not self.manual_login_token:
                        self.request_guard.admission(self.purpose, self.video, Path(sys.argv[0]).name)
                except WeChatCooldownDeferred as exc:
                    raise WeChatSessionCooldown(str(exc)) from exc
                except WeChatRequestDeferred as exc:
                    raise WeChatAccountDeferred(str(exc)) from exc
                self._handle = handle
                self._request_started = False
                self._request_limited = False
                handle.seek(0)
                handle.truncate()
                json.dump({"pid": os.getpid(), "stage": self.purpose, "video": self.video,
                           "started_at": datetime.now(timezone.utc).isoformat()}, handle, ensure_ascii=False)
                handle.flush()
                self._context_token = _SESSION.set(self)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise WeChatSessionLockBusy(
                        f"wechat session lock busy: {self.lock_path}"
                    )
                time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.monotonic())))
            except BaseException:
                handle.close()
                raise

    def release(self) -> None:
        """释放当前进程持有的锁。"""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if self._context_token is not None:
                _SESSION.reset(self._context_token)
                self._context_token = None
            if self._request_started:
                self.request_guard.end_session(self._request_count, self._list_request_count)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "WeChatSessionLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def guarded_wechat_browser_session(
    *,
    enabled: Callable[[], bool],
    state_parameter: str = "state_path",
    timeout_seconds: float = 0.0,
    busy_result: R,
    purpose: str = "浏览器操作",
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """仅在功能开关开启时，为脚本入口的整个浏览器会话加锁。"""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if not enabled():
                return function(*args, **kwargs)
            bound = signature.bind_partial(*args, **kwargs)
            state_path = bound.arguments.get(state_parameter)
            if state_path is None:
                state_path = signature.parameters[state_parameter].default
            parent = current()
            key = parent.key if parent and parent.row.get("parent") else "wechat-session:" + str(state_path) + ":" + purpose
            try:
                video = Path(str(bound.arguments.get("video_path") or "")).stem
                override = bound.arguments.get("cooldown_override") or ""
                if override:
                    # 实际成片名绑定任务，不能借另传的 ID 将授权用于另一条视频。
                    for suffix in ("_vertical_interactive", "_vertical", "_vocab", "_insight"):
                        if video.endswith(suffix):
                            video = video[:-len(suffix)]
                            break
                    if purpose != "发布" or bound.arguments.get("login_only") or bound.arguments.get("verify_only"):
                        raise WeChatOverrideInvalid("单次跳过只允许当前作品发布")
                login_token = bound.arguments.get("manual_login_token") or ""
                if login_token and (not bound.arguments.get("login_only") or bound.arguments.get("verify_only")):
                    raise WeChatOverrideInvalid("人工登录许可不能用于投稿或回查")
                effective_purpose = ("状态核对" if bound.arguments.get("verify_only") else
                                     "登录" if bound.arguments.get("login_only") else purpose)
                task = (str(bound.arguments.get("platform_post_id") or "") if effective_purpose == "状态核对"
                        else str(Path(bound.arguments["video_path"]).resolve()) if bound.arguments.get("video_path")
                        else purpose)
                with gate().admit("wechat-resource", key) as ticket:
                    with WeChatSessionLock(state_path, timeout_seconds=timeout_seconds, purpose=effective_purpose,
                                           video=video if override else task, cooldown_override=override, manual_login_token=login_token) as session:
                        session.request_guard.metadata = {name: str(bound.arguments[name]) for name in
                            ("copy_path", "title_path", "state_path") if bound.arguments.get(name)}
                        ticket.start()
                        return function(*args, **kwargs)
            except WeChatSessionCooldown:
                # 长驻旧执行器仍按 busy=11 处理；新调用方显式声明识别细分结果。
                return EXIT_WECHAT_COOLDOWN if bound.arguments.get("cooldown_result_codes") else busy_result
            except WeChatOverrideInvalid:
                return EXIT_WECHAT_OVERRIDE_INVALID
            except WeChatAccountDeferred:
                return EXIT_WECHAT_ACCOUNT_DEFERRED if bound.arguments.get("cooldown_result_codes") else busy_result
            except WeChatSessionLockBusy:
                return busy_result

        return wrapped

    return decorate

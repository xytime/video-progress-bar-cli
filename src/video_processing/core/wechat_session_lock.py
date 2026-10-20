"""视频号浏览器会话的跨进程排他锁。

锁文件由 Playwright storage-state 的规范化绝对路径唯一派生，确保上传、
保活和评论适配器不会同时使用或改写同一份登录态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.4.0 | 2026-10-20 | Codex | 会话入口遵守账户共享冷却；上下文首个请求前登记会话并捕获所有原生限流响应。 |
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
from contextvars import ContextVar
from datetime import datetime, timezone

from .task_lease import read_lease_owner
from .maintenance import gate, current
from .wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
from pathlib import Path
from typing import Callable, ParamSpec, TypeVar


P = ParamSpec("P")
R = TypeVar("R")
EXIT_WECHAT_SESSION_BUSY = 11  # 未进入被保护函数，更未启动浏览器或发表。
_SESSION: ContextVar = ContextVar("wechat_request_session", default=None)


def guard_wechat_context(context):
    """在任何页面导航前挂监听；临时复用上下文沿用当前同一账户的请求预算。"""
    session = _SESSION.get()
    if session is None:
        return
    if session._request_limited:
        raise WeChatSessionLockBusy("当前视频号会话已收到限流，禁止创建后续上下文")
    if not session._request_started:
        try:
            session.request_guard.start_session(session.purpose)
        except WeChatRequestDeferred as exc:
            raise WeChatSessionLockBusy(str(exc)) from exc
        session._request_started = True
    context._wechat_rate_limit_seen = False

    def response_received(response):
        if session.request_guard.observe_response(response):
            session._request_limited = True
            context._wechat_rate_limit_seen = True
            context._wechat_rate_limit_code = session.request_guard.snapshot()["business_code"]

    context.on("response", response_received)


class WeChatSessionLockBusy(RuntimeError):
    """同一份视频号登录态当前正由另一个浏览器会话占用。"""


def canonical_wechat_session_lock_path(state_path: str | Path) -> Path:
    """从登录态文件的规范化绝对路径派生唯一锁文件。"""
    state_file = Path(state_path).expanduser().resolve(strict=False)
    return state_file.with_name(f".{state_file.name}.browser.lock")


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
    ) -> None:
        self.state_path = Path(state_path).expanduser().resolve(strict=False)
        self.lock_path = canonical_wechat_session_lock_path(self.state_path)
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self._handle = None
        self.purpose = purpose
        self.video = video
        self.request_guard = WeChatRequestGuard(self.state_path)
        self._request_started = False
        self._request_limited = False
        self._context_token = None

    def acquire(self) -> "WeChatSessionLock":
        """在截止时间内尝试获取锁，超时即抛出可识别的 busy 异常。"""
        if self.purpose != "发布" and read_lease_owner(self.state_path.parent / "wechat_publish_priority.lock"):
            raise WeChatSessionLockBusy("待发布任务优先；评论/保活本轮让出浏览器")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    self.request_guard.check()
                except WeChatRequestDeferred as exc:
                    raise WeChatSessionLockBusy(str(exc)) from exc
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
                with gate().admit("wechat-resource", key) as ticket:
                    with WeChatSessionLock(state_path, timeout_seconds=timeout_seconds, purpose=purpose,
                                           video=Path(str(bound.arguments.get("video_path") or "")).stem):
                        ticket.start()
                        return function(*args, **kwargs)
            except WeChatSessionLockBusy:
                return busy_result

        return wrapped

    return decorate

"""视频号浏览器会话的跨进程排他锁。

锁文件由 Playwright storage-state 的规范化绝对路径唯一派生，确保上传、
保活和评论适配器不会同时使用或改写同一份登录态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Codex | 新增 state-path 派生的有界非阻塞跨进程会话锁与脚本装饰器。 |
"""

from __future__ import annotations

import fcntl
import functools
import inspect
import time
from pathlib import Path
from typing import Callable, ParamSpec, TypeVar


P = ParamSpec("P")
R = TypeVar("R")
EXIT_WECHAT_SESSION_BUSY = 11  # 未进入被保护函数，更未启动浏览器或发表。


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
    ) -> None:
        self.state_path = Path(state_path).expanduser().resolve(strict=False)
        self.lock_path = canonical_wechat_session_lock_path(self.state_path)
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self._handle = None

    def acquire(self) -> "WeChatSessionLock":
        """在截止时间内尝试获取锁，超时即抛出可识别的 busy 异常。"""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._handle = handle
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
            try:
                with WeChatSessionLock(state_path, timeout_seconds=timeout_seconds):
                    return function(*args, **kwargs)
            except WeChatSessionLockBusy:
                return busy_result

        return wrapped

    return decorate

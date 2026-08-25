"""macOS WeChat 桌面快捷授权辅助。

该模块只在网页已主动点击“微信快捷登录”后短时运行。它不会启动微信、不会扫描
二维码，也不会点击普通聊天窗口中的通用“允许/确认”按钮；没有明确的登录/授权窗口
或辅助功能权限时返回失败，由调用方回退二维码或 LOGIN_REQUIRED。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-25 | Codex | 新增受限 WeChat 桌面登录授权监听、无点击预检与超时退出。 |
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger("wechat_desktop_auth")


_PREFLIGHT_SCRIPT = r'''
tell application "System Events"
    if not (exists process "WeChat") then return "NO_WECHAT_PROCESS"
    tell process "WeChat"
        set windowNames to name of every window
    end tell
end tell
return "READY"
'''

# 只接受名字明确指向登录动作的窗口和按钮。不要扩大为“允许”“确认”，避免误操作聊天。
_CLICK_AUTH_SCRIPT = r'''
on containsText(haystack, needle)
    if haystack is missing value then return false
    return (haystack as text) contains needle
end containsText

tell application "System Events"
    if not (exists process "WeChat") then return "NO_WECHAT_PROCESS"
    tell process "WeChat"
        repeat with w in windows
            set windowName to ""
            try
                set windowName to name of w as text
            end try
            if my containsText(windowName, "登录") or my containsText(windowName, "授权") or my containsText(windowName, "视频号") or my containsText(windowName, "创作平台") then
                repeat with candidateName in {"登录", "授权登录", "确认登录"}
                    try
                        set authButton to first button of w whose name is candidateName
                        if exists authButton then
                            click authButton
                            return "CLICKED_LOGIN"
                        end if
                    end try
                end repeat
            end if
        end repeat
    end tell
end tell
return "NO_SCOPED_AUTH_WINDOW"
'''


@dataclass(frozen=True)
class DesktopAuthPreflight:
    ready: bool
    code: str


def desktop_auth_preflight() -> DesktopAuthPreflight:
    """只读检查 WeChat 进程和 macOS 辅助功能权限，不执行任何点击。"""
    try:
        result = subprocess.run(
            ["osascript", "-e", _PREFLIGHT_SCRIPT],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DesktopAuthPreflight(False, "OSASCRIPT_UNAVAILABLE")
    output = (result.stdout or "").strip()
    if result.returncode == 0 and output == "READY":
        return DesktopAuthPreflight(True, "READY")
    error_text = (result.stderr or "").lower()
    permission_markers = (
        "not authorized",
        "not allowed assistive",
        "不允许辅助访问",
        "不允许辅助功能",
    )
    if any(marker in error_text for marker in permission_markers):
        return DesktopAuthPreflight(False, "ACCESSIBILITY_DENIED")
    return DesktopAuthPreflight(False, output or "PREFLIGHT_FAILED")


class WeChatDesktopAuthWatcher:
    """在受限时间窗内轮询 WeChat 登录/授权窗口；失败不抛异常。"""

    def __init__(self, timeout_seconds: int, poll_interval_seconds: float = 0.5) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.clicked = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll, name="wechat-desktop-auth", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _poll(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    ["osascript", "-e", _CLICK_AUTH_SCRIPT],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if result.returncode == 0 and (result.stdout or "").strip() == "CLICKED_LOGIN":
                    self.clicked = True
                    logger.info("WeChat desktop scoped login authorization clicked.")
                    return
            except (OSError, subprocess.TimeoutExpired):
                logger.warning("WeChat desktop authorization watcher could not invoke osascript.")
                return
            self._stop_event.wait(self.poll_interval_seconds)

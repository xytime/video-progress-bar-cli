"""macOS WeChat 桌面快捷授权辅助。

该模块只在网页已主动点击“微信快捷登录”后短时运行。它不会启动微信、不会扫描
二维码，也不会点击普通聊天窗口中的通用“允许/确认”按钮；仅“视频号创作平台
申请使用”窗口中的“允许”在白名单内。没有明确的登录/授权窗口或辅助功能权限时
返回失败，由调用方回退二维码或 LOGIN_REQUIRED。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.10.0 | 2026-09-27 | Antigravity | 区分上下文文本置信度(>=0.3)与按钮精确置信度(>=0.8)，适配 Apple Vision 对中文短语的标称置信度。 |
| 1.9.0 | 2026-09-26 | Codex | 视觉后备改为限定小窗口与离线文字验证；校验坐标、窗口身份及停止期限后才点击。 |
| 1.8.0 | 2026-09-26 | Codex | 只读识别桌面登录页，明确报告 DESKTOP_LOGIN_REQUIRED，阻止无效桌面授权监听。 |
| 1.7.0 | 2026-09-26 | Codex | 短暂辅助功能超时在截止前重试；停止后禁止视觉点击，保留明确诊断状态。 |
| 1.0.0 | 2026-08-25 | Codex | 新增受限 WeChat 桌面登录授权监听、无点击预检与超时退出。 |
| 1.1.0 | 2026-08-25 | Codex | 仅在“视频号创作平台 申请使用”窗口中允许点击“允许”，覆盖实际快捷登录授权弹窗且不放宽通用确认。 |
| 1.2.0 | 2026-08-25 | Codex | 以辅助功能文本而非窗口标题识别视频号申请弹窗，适配 WeChat 自绘窗口。 |
| 1.3.0 | 2026-08-25 | Codex | 递归枚举 WeChat 自绘窗口内容，并同时检查元素名称和值以定位实际申请提示。 |
| 1.4.0 | 2026-08-25 | Codex | 在同一已确认申请窗口的深层元素中定位精确“允许”按钮，适配自绘按钮层级。 |
| 1.5.0 | 2026-08-25 | Codex | 辅助功能树不暴露原生许可弹窗时，新增受限视觉定位后备，仅点击唯一的大号微信绿授权按钮。 |
| 1.6.0 | 2026-08-25 | Codex | 视觉核验前受限激活 WeChat，避免其他前台应用遮挡原生许可框导致错误跳过。 |
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("wechat_desktop_auth")


_PREFLIGHT_SCRIPT = r'''
on loginButtonNames(pane, remainingDepth)
    set matches to {}
    tell application "System Events"
        try
            repeat with candidate in buttons of pane
                set labels to {}
                try
                    set end of labels to name of candidate
                end try
                try
                    set end of labels to description of candidate
                end try
                repeat with expected in {"仅传输文件", "二维码", "进入微信"}
                    if labels contains (expected as text) then set end of matches to (expected as text)
                end repeat
            end repeat
        end try
        if remainingDepth > 0 then
            try
                repeat with childPane in UI elements of pane
                    set matches to matches & (my loginButtonNames(childPane, remainingDepth - 1))
                end repeat
            end try
        end if
    end tell
    return matches
end loginButtonNames

tell application "System Events"
    if not (exists process "WeChat") then return "NO_WECHAT_PROCESS"
    tell process "WeChat"
        if (count of windows) is 0 then return "NO_WECHAT_WINDOW"
        repeat with w in windows
            -- 仅小型登录窗口、有限层级、固定按钮名；不读取聊天正文和二维码内容。
            set windowSize to size of w
            if (item 1 of windowSize) <= 700 and (item 2 of windowSize) <= 900 then
                set loginNames to my loginButtonNames(w, 3)
                if (loginNames contains "仅传输文件") and ((loginNames contains "二维码") or (loginNames contains "进入微信")) then return "DESKTOP_LOGIN_REQUIRED"
            end if
        end repeat
    end tell
end tell
return "READY"
'''

# 只接受名字明确指向登录动作的窗口和按钮。仅视频号申请窗口例外允许“允许”。
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
            set isVideoAccountApplication to false
            try
                repeat with element in entire contents of w
                    set elementName to ""
                    set elementValue to ""
                    try
                        set elementName to (name of element) as text
                    end try
                    try
                        set elementValue to (value of element) as text
                    end try
                    if (my containsText(elementName, "视频号创作平台") and my containsText(elementName, "申请使用")) or (my containsText(elementValue, "视频号创作平台") and my containsText(elementValue, "申请使用")) then
                        set isVideoAccountApplication to true
                        exit repeat
                    end if
                end repeat
            end try
            if isVideoAccountApplication then
                repeat with element in entire contents of w
                    set elementName to ""
                    try
                        set elementName to (name of element) as text
                    end try
                    if elementName is "允许" then
                        click element
                        return "CLICKED_LOGIN"
                    end if
                end repeat
            else if my containsText(windowName, "登录") or my containsText(windowName, "授权") or my containsText(windowName, "视频号") or my containsText(windowName, "创作平台") then
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

_FRONTMOST_PROCESS_SCRIPT = r'''
tell application "System Events"
    set frontApps to application processes whose frontmost is true
    if (count of frontApps) is not 1 then return ""
    return name of item 1 of frontApps
end tell
'''

_ACTIVATE_WECHAT_SCRIPT = r'''
tell application "System Events"
    tell process "WeChat" to set frontmost to true
end tell
'''


@dataclass(frozen=True)
class DesktopAuthPreflight:
    ready: bool
    code: str


def desktop_auth_preflight() -> DesktopAuthPreflight:
    """检查进程、辅助功能和明确的桌面登录页；READY 不证明网页登录成功。"""
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


def _frontmost_process_name() -> str:
    """返回当前前台进程名；无法可靠识别时宁可不做视觉点击。"""
    try:
        result = subprocess.run(
            ["osascript", "-e", _FRONTMOST_PROCESS_SCRIPT],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def _activate_wechat() -> bool:
    """只将 WeChat 置前；后续仍须通过视觉候选门禁才会点击。"""
    try:
        result = subprocess.run(
            ["osascript", "-e", _ACTIVATE_WECHAT_SCRIPT],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _find_visual_allow_button(image) -> tuple[int, int] | None:
    """返回唯一大号微信绿按钮中心；任何歧义均返回 None。"""
    try:
        import cv2
    except ImportError:
        return None
    if image is None or getattr(image, "ndim", 0) != 3:
        return None
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # 微信绿 #07C160 的 HSV 附近，容纳屏幕色彩配置和抗锯齿造成的小幅偏差。
    mask = cv2.inRange(hsv, (40, 100, 100), (90, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, button_width, button_height = cv2.boundingRect(contour)
        ratio = button_width / button_height if button_height else 0
        if button_width < max(120, width // 25) or button_height < max(30, height // 40):
            continue
        if not 1.8 <= ratio <= 6.0:
            continue
        if not (width * 0.2 <= x + button_width / 2 <= width * 0.85):
            continue
        if not (height * 0.2 <= y + button_height / 2 <= height * 0.9):
            continue
        candidates.append((x, y, button_width, button_height))
    if len(candidates) != 1:
        return None
    x, y, button_width, button_height = candidates[0]
    return (x + button_width // 2, y + button_height // 2)


def _vision_command(*args: str, timeout: float = 3):
    """系统离线识别适配器；不输出图片文字、账号或授权参数到日志。"""
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", str(Path(__file__).with_name("wechat_auth_vision.js")), *args],
            capture_output=True, text=True, timeout=max(0.01, timeout), check=False,
        )
        return json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _verified_visual_allow_center(image, observations) -> tuple[int, int] | None:
    """同一窗口必须同时具备申请方、申请提示和绿色按钮内的精确“允许”。"""
    if not isinstance(observations, list):
        return None
    center = _find_visual_allow_button(image)
    if center is None:
        return None
    height, width = image.shape[:2]
    lines = []
    allows = []
    for item in observations:
        try:
            text = re.sub(r"\s+", "", item["text"])
            x, y, w, h = item["box"]
            conf = float(item["confidence"])
            if not (0 <= x < x+w <= 1 and 0 <= y < y+h <= 1):
                continue
            box = (x*width, (1-y-h)*height, (x+w)*width, (1-y)*height)
            if conf >= 0.3:
                lines.append((text, box))
            if conf >= 0.8 and text == "允许":
                allows.append(box)
        except (KeyError, TypeError, ValueError):
            continue
    combined = "".join(text for text, _ in lines)
    if "视频号创作平台" not in combined or "申请使用" not in combined:
        return None
    if len(allows) != 1:
        return None
    left, top, right, bottom = allows[0]
    if not (left <= center[0] <= right and top <= center[1] <= bottom):
        return None
    return center


def _try_visual_allow_click(*, cancelled=lambda: False, deadline: float | None = None) -> bool:
    """只截取候选授权小窗口；离线 OCR 与颜色均通过后才允许受限点击。"""
    deadline = deadline if deadline is not None else time.monotonic() + 10
    def stopped():
        return cancelled() or time.monotonic() >= deadline
    def remaining():
        return max(0.01, min(3, deadline - time.monotonic()))
    if stopped() or not _activate_wechat() or stopped():
        return False
    windows = _vision_command("windows", timeout=remaining())
    if not isinstance(windows, list) or not 1 <= len(windows) <= 3:
        return False
    try:
        import cv2
    except ImportError:
        return False
    candidates = []
    with tempfile.TemporaryDirectory(prefix="wechat-desktop-auth-") as temp_dir:
        for window in windows:
            if stopped():
                return False
            try:
                window_id = int(window["id"])
                bounds = window["bounds"]
                if window_id <= 0 or not (200 <= bounds["Width"] <= 700 and 120 <= bounds["Height"] <= 900):
                    return False
                screenshot = Path(temp_dir) / f"{window_id}.png"
                capture = subprocess.run(
                    ["screencapture", "-x", "-o", "-l", str(window_id), str(screenshot)],
                    capture_output=True, text=True, timeout=remaining(), check=False,
                )
                if capture.returncode != 0 or stopped():
                    return False
                image = cv2.imread(str(screenshot))
                observations = _vision_command("ocr", str(screenshot), timeout=remaining())
                center = _verified_visual_allow_center(image, observations)
                if center:
                    height, width = image.shape[:2]
                    point = (round(bounds["X"] + center[0]*bounds["Width"]/width),
                             round(bounds["Y"] + center[1]*bounds["Height"]/height))
                    candidates.append((window, point))
            except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired):
                return False
    if len(candidates) != 1 or stopped():
        return False
    window, (click_x, click_y) = candidates[0]
    # OCR 期间窗口可能消失或移动；同一编号、进程与几何必须仍在可见白名单内。
    current = _vision_command("windows", timeout=remaining())
    if not isinstance(current, list) or window not in current or stopped():
        return False
    if _frontmost_process_name() != "WeChat" or stopped():
        return False
    target = {"window": window, "x": click_x, "y": click_y,
              "expiresAt": (time.time() + max(0, deadline - time.monotonic())) * 1000}
    return _vision_command("click", json.dumps(target), timeout=remaining()) is True



class WeChatDesktopAuthWatcher:
    """在受限时间窗内轮询 WeChat 登录/授权窗口；失败不抛异常。"""

    def __init__(self, timeout_seconds: int, poll_interval_seconds: float = 0.5,
                 enable_visual_fallback: bool = False) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self.enable_visual_fallback = enable_visual_fallback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.clicked = False
        self.last_result = "NOT_STARTED"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.clicked = False
        preflight = desktop_auth_preflight()
        self.last_result = preflight.code
        if not preflight.ready:
            logger.warning("WeChat desktop authorization unavailable: %s", preflight.code)
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
                    timeout=max(0.01, min(3, deadline - time.monotonic())),
                    check=False,
                )
                if result.returncode == 0 and (result.stdout or "").strip() == "CLICKED_LOGIN":
                    self.clicked = True
                    self.last_result = "CLICKED_LOGIN"
                    logger.info("WeChat desktop scoped login authorization clicked.")
                    return
                if result.returncode != 0:
                    # Qt 自绘控件的 AXPress 不支持，可交给严格文字验证的原生点击；权限错误不能降级。
                    if "-25208" in (result.stderr or ""):
                        self.last_result = "AX_CLICK_UNSUPPORTED"
                    else:
                        self.last_result = "AUTOMATION_FAILED"
                        logger.warning("WeChat desktop authorization automation failed.")
                        return
                else:
                    self.last_result = "NO_SCOPED_AUTH_WINDOW"
            except subprocess.TimeoutExpired:
                self.last_result = "AUTOMATION_TIMEOUT"
                # 短暂 AX 卡顿不代表整个授权流程失败，也不据此放宽到视觉点击。
                self._stop_event.wait(self.poll_interval_seconds)
                continue
            except OSError:
                self.last_result = "OSASCRIPT_UNAVAILABLE"
                logger.warning("WeChat desktop authorization watcher could not invoke osascript.")
                return
            if self._stop_event.is_set() or time.monotonic() >= deadline:
                return
            if self.enable_visual_fallback and _try_visual_allow_click(
                cancelled=self._stop_event.is_set, deadline=deadline,
            ):
                self.clicked = True
                self.last_result = "CLICKED_VISUAL"
                logger.info("WeChat desktop visual authorization fallback clicked.")
                return
            self._stop_event.wait(self.poll_interval_seconds)

"""macOS WeChat 桌面快捷授权的安全边界测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-25 | Codex | 覆盖无点击预检、受限成功信号和失败不抛异常的边界。 |
| 1.1.0 | 2026-08-25 | Codex | 固化视频号申请窗口的允许按钮白名单，防止扩展为通用允许。 |
| 1.2.0 | 2026-08-25 | Codex | 断言提示文本由辅助功能树精确匹配，不依赖 WeChat 自绘窗口标题。 |
| 1.3.0 | 2026-08-25 | Codex | 覆盖 AppleScript 在 System Events 术语作用域内直接枚举 UI 元素的可编译实现。 |
| 1.4.0 | 2026-08-25 | Codex | 固化深层自绘内容枚举及名称和值双通道匹配。 |
| 1.5.0 | 2026-08-25 | Codex | 断言允许按钮也从已确认窗口的深层内容精确定位。 |
"""

from unittest.mock import MagicMock, patch

import numpy as np

from scripts.wechat_desktop_auth import (
    WeChatDesktopAuthWatcher,
    _CLICK_AUTH_SCRIPT,
    _find_visual_allow_button,
    desktop_auth_preflight,
)


def test_preflight_reports_ready_only_for_explicit_ready_signal():
    completed = MagicMock(returncode=0, stdout="READY\n", stderr="")

    with patch("scripts.wechat_desktop_auth.subprocess.run", return_value=completed):
        result = desktop_auth_preflight()

    assert result.ready is True
    assert result.code == "READY"


def test_preflight_never_treats_unknown_result_as_authorized():
    completed = MagicMock(returncode=0, stdout="NO_WECHAT_PROCESS\n", stderr="")

    with patch("scripts.wechat_desktop_auth.subprocess.run", return_value=completed):
        result = desktop_auth_preflight()

    assert result.ready is False
    assert result.code == "NO_WECHAT_PROCESS"


def test_preflight_classifies_localized_accessibility_denial():
    completed = MagicMock(returncode=1, stdout="", stderr="osascript 不允许辅助访问")

    with patch("scripts.wechat_desktop_auth.subprocess.run", return_value=completed):
        result = desktop_auth_preflight()

    assert result.ready is False
    assert result.code == "ACCESSIBILITY_DENIED"


def test_watcher_marks_success_only_for_scoped_login_click_signal():
    completed = MagicMock(returncode=0, stdout="CLICKED_LOGIN\n", stderr="")
    watcher = WeChatDesktopAuthWatcher(timeout_seconds=1)

    with patch("scripts.wechat_desktop_auth.subprocess.run", return_value=completed):
        watcher._poll()

    assert watcher.clicked is True


def test_watcher_does_not_promote_unscoped_window_to_success():
    completed = MagicMock(returncode=0, stdout="NO_SCOPED_AUTH_WINDOW\n", stderr="")
    watcher = WeChatDesktopAuthWatcher(timeout_seconds=1, poll_interval_seconds=0.1)

    with patch("scripts.wechat_desktop_auth.subprocess.run", return_value=completed):
        with patch.object(watcher._stop_event, "wait", side_effect=lambda *_args: watcher._stop_event.set()):
            watcher._poll()

    assert watcher.clicked is False


def test_watcher_allows_allow_only_in_the_explicit_video_account_application_window():
    assert "repeat with element in entire contents of w" in _CLICK_AUTH_SCRIPT
    assert 'containsText(elementName, "视频号创作平台") and my containsText(elementName, "申请使用")' in _CLICK_AUTH_SCRIPT
    assert 'containsText(elementValue, "视频号创作平台") and my containsText(elementValue, "申请使用")' in _CLICK_AUTH_SCRIPT
    assert "if isVideoAccountApplication then" in _CLICK_AUTH_SCRIPT
    assert 'if elementName is "允许" then' in _CLICK_AUTH_SCRIPT
    assert 'candidateName in {"登录", "授权登录", "确认登录"}' in _CLICK_AUTH_SCRIPT


def test_visual_fallback_returns_the_unique_large_wechat_green_button_center():
    image = np.zeros((900, 1200, 3), dtype=np.uint8)
    image[500:580, 600:960] = (96, 193, 7)  # BGR for #07C160

    assert _find_visual_allow_button(image) == (780, 540)


def test_visual_fallback_rejects_ambiguous_green_button_candidates():
    image = np.zeros((900, 1200, 3), dtype=np.uint8)
    image[500:580, 300:660] = (96, 193, 7)
    image[500:580, 700:1060] = (96, 193, 7)

    assert _find_visual_allow_button(image) is None

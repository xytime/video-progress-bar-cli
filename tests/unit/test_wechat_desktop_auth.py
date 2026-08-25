"""macOS WeChat 桌面快捷授权的安全边界测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-25 | Codex | 覆盖无点击预检、受限成功信号和失败不抛异常的边界。 |
"""

from unittest.mock import MagicMock, patch

from scripts.wechat_desktop_auth import WeChatDesktopAuthWatcher, desktop_auth_preflight


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

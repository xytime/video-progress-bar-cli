"""macOS WeChat 桌面快捷授权的安全边界测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.8.0 | 2026-09-26 | Codex | 覆盖离线授权文字、错误按钮、窗口变化、停止和多屏缩放边界。 |
| 1.7.0 | 2026-09-26 | Codex | 桌面登录页不能视为就绪；未登录时不启动点击线程。 |
| 1.6.0 | 2026-09-26 | Codex | 覆盖临时超时重试、停止后零点击及自动化失败不降级视觉。 |
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
    _activate_wechat,
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


def test_activate_wechat_returns_false_when_osascript_fails():
    completed = MagicMock(returncode=1, stdout="", stderr="activation failed")

    with patch("scripts.wechat_desktop_auth.subprocess.run", return_value=completed):
        assert _activate_wechat() is False


def test_transient_automation_timeout_retries_until_scoped_success():
    import subprocess
    watcher = WeChatDesktopAuthWatcher(timeout_seconds=1, poll_interval_seconds=0.1)
    success = MagicMock(returncode=0, stdout='CLICKED_LOGIN', stderr='')
    with patch('scripts.wechat_desktop_auth.subprocess.run', side_effect=[subprocess.TimeoutExpired('osascript', 3), success]) as run:
        watcher._poll()
    assert watcher.clicked
    assert watcher.last_result == 'CLICKED_LOGIN'
    assert run.call_count == 2


def test_stopped_watcher_never_starts_visual_click():
    watcher = WeChatDesktopAuthWatcher(timeout_seconds=1, enable_visual_fallback=True)
    def stop_during_check(*args, **kwargs):
        watcher._stop_event.set()
        return MagicMock(returncode=0, stdout='NO_SCOPED_AUTH_WINDOW', stderr='')
    with patch('scripts.wechat_desktop_auth.subprocess.run', side_effect=stop_during_check), patch('scripts.wechat_desktop_auth._try_visual_allow_click') as visual:
        watcher._poll()
    visual.assert_not_called()
    assert not watcher.clicked


def test_automation_error_does_not_fall_back_to_unproven_visual_click():
    watcher = WeChatDesktopAuthWatcher(timeout_seconds=1, enable_visual_fallback=True)
    with patch('scripts.wechat_desktop_auth.subprocess.run', return_value=MagicMock(returncode=1, stdout='', stderr='denied')), patch('scripts.wechat_desktop_auth._try_visual_allow_click') as visual:
        watcher._poll()
    visual.assert_not_called()
    assert watcher.last_result == 'AUTOMATION_FAILED'
    assert not watcher.clicked


def test_preflight_reports_desktop_login_required_instead_of_ready():
    completed = MagicMock(returncode=0, stdout='DESKTOP_LOGIN_REQUIRED\n', stderr='')
    with patch('scripts.wechat_desktop_auth.subprocess.run', return_value=completed):
        result = desktop_auth_preflight()
    assert result.ready is False
    assert result.code == 'DESKTOP_LOGIN_REQUIRED'


def test_watcher_never_starts_clicking_when_desktop_login_is_required():
    from scripts.wechat_desktop_auth import DesktopAuthPreflight
    watcher = WeChatDesktopAuthWatcher(timeout_seconds=1, enable_visual_fallback=True)
    with patch('scripts.wechat_desktop_auth.desktop_auth_preflight', return_value=DesktopAuthPreflight(False, 'DESKTOP_LOGIN_REQUIRED')), patch('scripts.wechat_desktop_auth.threading.Thread') as thread:
        watcher.start()
    thread.assert_not_called()
    assert watcher.last_result == 'DESKTOP_LOGIN_REQUIRED'
    assert not watcher.clicked


def _visual_fixture():
    image = np.zeros((600, 600, 3), dtype=np.uint8)
    image[340:401, 180:421] = (96, 193, 7)
    observations = [
        {'text': '视频号创作平台', 'confidence': 1, 'box': [0.25, 0.8, 0.5, 0.06]},
        {'text': '申请使用', 'confidence': 1, 'box': [0.4, 0.7, 0.2, 0.06]},
        {'text': '允许', 'confidence': 1, 'box': [0.45, 0.36, 0.1, 0.06]},
    ]
    return image, observations


def test_visual_click_requires_real_authorization_words_and_allow_inside_button():
    from scripts.wechat_desktop_auth import _verified_visual_allow_center
    image, observations = _visual_fixture()
    assert _verified_visual_allow_center(image, observations) == (300, 370)
    assert _verified_visual_allow_center(image, []) is None
    assert _verified_visual_allow_center(image, observations[1:]) is None
    assert _verified_visual_allow_center(image, observations[:1] + observations[2:]) is None
    observations[-1]['text'] = '发送'
    assert _verified_visual_allow_center(image, observations) is None


def test_visual_click_rejects_low_confidence_ambiguous_and_misplaced_allow():
    from scripts.wechat_desktop_auth import _verified_visual_allow_center
    image, observations = _visual_fixture()
    observations[-1]['confidence'] = 0.5
    assert _verified_visual_allow_center(image, observations) is None
    observations[-1]['confidence'] = 1
    assert _verified_visual_allow_center(image, observations + [observations[-1]]) is None
    observations[-1]['box'] = [0.1, 0.1, 0.1, 0.06]
    assert _verified_visual_allow_center(image, observations) is None


def test_visual_click_rejects_blank_unreadable_or_malformed_capture():
    from scripts.wechat_desktop_auth import _verified_visual_allow_center
    image, observations = _visual_fixture()
    assert _verified_visual_allow_center(None, observations) is None
    assert _verified_visual_allow_center(image, None) is None
    assert _verified_visual_allow_center(image, [{'unexpected': 'data'}]) is None
    assert _verified_visual_allow_center(np.zeros_like(image), observations) is None


def test_cancelled_visual_check_never_activates_or_captures_desktop():
    from scripts.wechat_desktop_auth import _try_visual_allow_click
    with patch('scripts.wechat_desktop_auth.subprocess.run') as run:
        assert not _try_visual_allow_click(cancelled=lambda: True)
    run.assert_not_called()


def test_visual_check_revalidates_window_and_stop_before_click():
    import json
    import cv2
    from scripts.wechat_desktop_auth import _try_visual_allow_click
    image, observations = _visual_fixture()
    window = {'id': 123, 'pid': 456, 'bounds': {'X': -600, 'Y': 100, 'Width': 300, 'Height': 300}}
    for mode in ('moved', 'cancelled', 'valid'):
        calls = []
        stopped = [False]
        window_reads = [0]
        def native_run(args, **kwargs):
            calls.append(args)
            output = ''
            if args[0] == 'screencapture':
                assert args[:4] == ['screencapture', '-x', '-o', '-l']
                cv2.imwrite(args[-1], image)
            elif 'windows' == args[-1]:
                window_reads[0] += 1
                if window_reads[0] == 2:
                    if mode == 'cancelled': stopped[0] = True
                    if mode == 'moved': return MagicMock(returncode=0, stdout='[]')
                output = json.dumps([window])
            elif 'ocr' in args:
                output = json.dumps(observations)
            elif 'click' in args:
                output = 'true'
            elif args[:2] == ['osascript', '-e']:
                if 'frontApps' in args[-1]: output = 'WeChat'
            return MagicMock(returncode=0, stdout=output)
        with patch('scripts.wechat_desktop_auth.subprocess.run', side_effect=native_run):
            assert _try_visual_allow_click(cancelled=lambda: stopped[0]) is (mode == 'valid')
        clicks = [c for c in calls if c[0] == 'osascript' and 'click' in c]
        if mode == 'valid':
            assert len(clicks) == 1
            assert (json.loads(clicks[0][-1])['x'], json.loads(clicks[0][-1])['y']) == (-450, 285)  # 负坐标屏幕 + retina 缩放
        else:
            assert clicks == []


def test_unsupported_ax_click_can_use_strict_visual_fallback():
    watcher = WeChatDesktopAuthWatcher(timeout_seconds=1, enable_visual_fallback=True)
    result = MagicMock(returncode=1, stdout='', stderr='System Events error (-25208)')
    with patch('scripts.wechat_desktop_auth.subprocess.run', return_value=result), patch('scripts.wechat_desktop_auth._try_visual_allow_click', return_value=True) as visual:
        watcher._poll()
    visual.assert_called_once()
    assert watcher.clicked and watcher.last_result == 'CLICKED_VISUAL'

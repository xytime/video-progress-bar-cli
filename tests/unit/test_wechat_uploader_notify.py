"""tests/unit/test_wechat_uploader_notify.py — 微信自动登录与续约 Telegram 通知单元测试

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-27 | Antigravity | 新增自动登录/续约成功后的 Telegram 回报通知与方法标识测试。 |
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_src = str(Path(__file__).parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

_scripts = str(Path(__file__).parent.parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from scripts.wechat_uploader import _notify_wechat_login_success, _wait_and_save_login


def test_notify_wechat_login_success_desktop_quick():
    with patch("video_processing.telegram_delivery.send_text") as mock_send:
        _notify_wechat_login_success("desktop_quick", Path("output/wechat_state.json"))
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["event_type"] == "WECHAT_LOGIN_RENEWED"
        assert kwargs["priority"] == "NORMAL"
        assert kwargs["cooldown_seconds"] == 30
        assert "桌面快捷授权（免扫码）" in kwargs["text"]
        assert "wechat_state.json" in kwargs["text"]
        assert "BJ" in kwargs["text"]


def test_notify_wechat_login_success_scan_qr():
    with patch("video_processing.telegram_delivery.send_text") as mock_send:
        _notify_wechat_login_success("scan_qr", Path("output/wechat_state.json"))
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        assert "手机扫码登录" in kwargs["text"]


def test_wait_and_save_login_triggers_notification_and_cleanup(tmp_path):
    page = MagicMock()
    page.url = "https://channels.weixin.qq.com/platform/post/create"

    reuse_page = MagicMock()
    reuse_page.url = "https://channels.weixin.qq.com/platform/post/create"
    reuse_context = MagicMock()
    reuse_context.new_page.return_value = reuse_page

    browser = MagicMock()
    browser.new_context.return_value = reuse_context

    context = MagicMock()
    context.browser = browser

    def fake_storage_state(path=None):
        if path:
            Path(path).write_text('{"cookies": [{"name": "auth", "value": "1"}]}')
        return {"cookies": []}

    context.storage_state.side_effect = fake_storage_state

    state_file = tmp_path / "wechat_state.json"
    qr_file = tmp_path / "login_qr.png"
    qr_file.write_text("dummy qr")

    with patch("scripts.wechat_uploader._stamp_login_success") as mock_stamp, \
         patch("scripts.wechat_uploader._notify_wechat_login_success") as mock_notify, \
         patch("video_processing.core.wechat_page_contract.wait_for_publish_ready_with_spa_guard", return_value=(True, None)):
        _wait_and_save_login(page, context, state_file, qr_path=qr_file, method="desktop_quick")

        page.wait_for_url.assert_called_once_with("**/post/create", timeout=600000)
        assert state_file.is_file()
        mock_stamp.assert_called_once_with(state_file, method="desktop_quick")
        assert not qr_file.exists()  # QR cleaned up
        mock_notify.assert_called_once_with(method="desktop_quick", state_file=state_file)


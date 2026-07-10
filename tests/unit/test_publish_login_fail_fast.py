"""自动发布遇到失效微信登录态时的快速失败契约测试。"""

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_automatic_upload_returns_login_required_without_waiting_for_qr(tmp_path: Path):
    from scripts.wechat_uploader import run_uploader

    video = tmp_path / "video.mp4"
    copy = tmp_path / "copy.txt"
    video.write_bytes(b"video")
    copy.write_text("copy", encoding="utf-8")

    page = MagicMock()
    page.url = "https://channels.weixin.qq.com/login.html"
    browser = MagicMock()
    context = MagicMock()
    context.new_page.return_value = page
    browser.new_context.return_value = context

    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.launch.return_value = browser

    with patch("scripts.wechat_uploader.sync_playwright", return_value=playwright):
        result = run_uploader(
            video_path=str(video),
            copy_path=str(copy),
            state_path=str(tmp_path / "wechat_state.json"),
            fail_fast_login=True,
        )

    assert result == 2
    browser.close.assert_called_once()
    # 快速失败发生在二维码捕获与等待之前。
    page.wait_for_url.assert_not_called()

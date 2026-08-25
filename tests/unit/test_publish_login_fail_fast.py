"""自动发布遇到失效微信登录态时的快速失败契约测试。"""

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from playwright._impl._errors import TargetClosedError
from video_processing.core.cover_policy import compliant_cover_layout_policy


def test_automatic_upload_returns_login_required_without_waiting_for_qr(tmp_path: Path):
    from scripts.wechat_uploader import run_uploader

    video = tmp_path / "video.mp4"
    copy = tmp_path / "copy.txt"
    video.write_bytes(b"video")
    copy.write_text("copy", encoding="utf-8")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"dedicated-cover")
    (tmp_path / "cover_provenance.json").write_text(
        json.dumps({
            "cover_kind": "dedicated_generated_image",
            "uses_video_frame": False,
            "cover_filename": cover.name,
            "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
            "layout_policy": compliant_cover_layout_policy(),
        }),
        encoding="utf-8",
    )

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
            cover_path=str(cover),
            state_path=str(tmp_path / "wechat_state.json"),
            fail_fast_login=True,
        )

    assert result == 2
    browser.close.assert_called_once()
    # 快速失败发生在二维码捕获与等待之前。
    page.wait_for_url.assert_not_called()


def test_fail_fast_attempts_enabled_desktop_quick_login_before_returning_login_required(tmp_path: Path):
    from scripts.wechat_uploader import run_uploader

    video = tmp_path / "video.mp4"
    copy = tmp_path / "copy.txt"
    video.write_bytes(b"video")
    copy.write_text("copy", encoding="utf-8")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"dedicated-cover")
    (tmp_path / "cover_provenance.json").write_text(
        json.dumps({
            "cover_kind": "dedicated_generated_image",
            "uses_video_frame": False,
            "cover_filename": cover.name,
            "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
            "layout_policy": compliant_cover_layout_policy(),
        }),
        encoding="utf-8",
    )

    page = MagicMock()
    page.url = "https://channels.weixin.qq.com/login.html"
    browser = MagicMock()
    context = MagicMock()
    context.new_page.return_value = page
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.launch.return_value = browser

    desktop_settings = MagicMock(
        enable_wechat_desktop_quick_login=True,
        wechat_desktop_quick_login_timeout_seconds=15,
        enable_wechat_desktop_visual_auth_fallback=True,
    )
    with (
        patch("scripts.wechat_uploader.sync_playwright", return_value=playwright),
        patch("scripts.wechat_uploader.settings", desktop_settings),
        patch("scripts.wechat_uploader.WeChatDesktopAuthWatcher") as watcher_cls,
        patch("scripts.wechat_uploader._try_wechat_quick_login", return_value=False) as quick_login,
    ):
        result = run_uploader(
            video_path=str(video),
            copy_path=str(copy),
            cover_path=str(cover),
            state_path=str(tmp_path / "wechat_state.json"),
            fail_fast_login=True,
        )

    assert result == 2
    watcher_cls.assert_called_once_with(15, enable_visual_fallback=True)
    quick_login.assert_called_once_with(
        page,
        desktop_auth=watcher_cls.return_value,
        timeout_ms=15_000,
    )
    page.wait_for_url.assert_not_called()


def test_cli_returns_unconfirmed_when_playwright_target_closes(tmp_path: Path):
    from scripts import wechat_uploader

    video = tmp_path / "video.mp4"
    copy = tmp_path / "copy.txt"
    video.write_bytes(b"video")
    copy.write_text("copy", encoding="utf-8")

    argv = [
        "wechat_uploader.py",
        "--video",
        str(video),
        "--copy",
        str(copy),
        "--state",
        str(tmp_path / "wechat_state.json"),
    ]
    with (
        patch.object(sys, "argv", argv),
        patch(
            "scripts.wechat_uploader.run_uploader",
            side_effect=TargetClosedError("Target page, context or browser has been closed"),
        ),
        pytest.raises(SystemExit) as exit_info,
    ):
        wechat_uploader.main()

    assert exit_info.value.code == 3

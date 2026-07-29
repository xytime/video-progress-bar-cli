"""微信封面硬门禁回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 锁定封面缺失、封面编辑未关闭和证据不足时禁止发表 |
"""

from pathlib import Path
from unittest.mock import Mock, patch

from scripts import wechat_uploader


class _Body:
    def __init__(self, text: str):
        self.text = text

    def inner_text(self, **_kwargs):
        return self.text


class _Page:
    def __init__(self, text: str):
        self.text = text

    def locator(self, selector: str):
        assert selector == "body"
        return _Body(self.text)


def test_missing_requested_cover_stops_before_browser_launch(tmp_path: Path):
    video = tmp_path / "video.mp4"
    copy = tmp_path / "copy.txt"
    video.write_bytes(b"video")
    copy.write_text("copy", encoding="utf-8")

    with patch("scripts.wechat_uploader.sync_playwright") as playwright:
        result = wechat_uploader.run_uploader(
            video_path=str(video),
            copy_path=str(copy),
            cover_path=str(tmp_path / "missing.jpg"),
            state_path=str(tmp_path / "wechat_state.json"),
        )

    assert result == 1
    playwright.assert_not_called()


def test_cover_is_not_accepted_while_cover_editor_remains_open(monkeypatch):
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: object())

    assert wechat_uploader._is_wechat_cover_applied(_Page("封面已更新"), Mock(), "before") is False


def test_cover_requires_success_marker_or_preview_change(monkeypatch):
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: None)
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_signature", lambda _card: "unchanged")

    assert wechat_uploader._is_wechat_cover_applied(_Page("表单已保存"), Mock(), "unchanged") is False
    assert wechat_uploader._is_wechat_cover_applied(_Page("封面已更新"), Mock(), "unchanged") is True


def test_cover_preview_change_is_accepted_after_editor_closes(monkeypatch):
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: None)
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_signature", lambda _card: "after")

    assert wechat_uploader._is_wechat_cover_applied(_Page(""), Mock(), "before") is True

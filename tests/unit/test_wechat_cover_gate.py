"""微信封面硬门禁回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 锁定封面缺失、封面编辑未关闭和证据不足时禁止发表 |
| 1.1.0 | 2026-07-30 | Codex | 禁止仅凭封面成功提示放行，必须确认预览发生变化 |
| 1.2.0 | 2026-07-30 | Codex | 封面变化改为比较卡片内全部图片来源，避免首图误判 |
| 1.3.0 | 2026-07-30 | Codex | 同 URL 刷新时以封面卡片视觉指纹作为受限变化证据 |
| 1.4.0 | 2026-07-30 | Codex | 覆写必须仍以平台成功提示为前置条件 |
| 1.5.0 | 2026-07-31 | Codex | 提示短暂消退时复用确认后即时捕获的成功证据 |
| 1.6.0 | 2026-07-31 | Codex | 封面确认后等待保存中的弹层关闭 |
| 1.7.0 | 2026-07-31 | Codex | 直接识别可见 toast，避免正文读取滞后造成假失败 |
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


class _VisibleToast:
    last = None

    def __init__(self):
        self.last = self

    def is_visible(self):
        return True

    def count(self):
        return 1


class _ToastPage(_Page):
    def locator(self, selector: str):
        if selector == "text=封面已更新":
            return _VisibleToast()
        return super().locator(selector)


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

    assert wechat_uploader._is_wechat_cover_applied(
        _Page("封面已更新"), Mock(), frozenset({"before"}), None
    ) is False


def test_waits_for_cover_editor_to_close_after_confirmation(monkeypatch):
    states = iter([object(), object(), None])
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: next(states))
    page = Mock()

    assert wechat_uploader._wait_for_wechat_cover_dialog_to_close(page, attempts=3) is True
    assert page.wait_for_timeout.call_count == 2


def test_cover_requires_preview_change_even_when_success_marker_exists(monkeypatch):
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: None)
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_signatures", lambda _card: frozenset({"unchanged"}))
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_visual_signature", lambda _card: "same")

    before = frozenset({"unchanged"})
    assert wechat_uploader._is_wechat_cover_applied(_Page("表单已保存"), Mock(), before, "same") is False
    assert wechat_uploader._is_wechat_cover_applied(_Page("封面已更新"), Mock(), before, "same") is False


def test_cover_requires_success_marker_after_preview_change(monkeypatch):
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: None)
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_signatures", lambda _card: frozenset({"after"}))
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_visual_signature", lambda _card: "same")

    assert wechat_uploader._is_wechat_cover_applied(_Page(""), Mock(), frozenset({"before"}), "same") is False


def test_cover_accepts_captured_success_marker_after_toast_disappears(monkeypatch):
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: None)
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_signatures", lambda _card: frozenset({"after"}))
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_visual_signature", lambda _card: "same")

    assert wechat_uploader._is_wechat_cover_applied(
        _Page(""),
        Mock(),
        frozenset({"before"}),
        "same",
        success_marker_observed=True,
    ) is True


def test_cover_is_accepted_only_when_preview_changes_and_platform_confirms(monkeypatch):
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: None)
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_signatures", lambda _card: frozenset({"after"}))
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_visual_signature", lambda _card: "same")

    assert wechat_uploader._is_wechat_cover_applied(_Page("封面已更新"), Mock(), frozenset({"before"}), "same") is True


def test_cover_visual_change_is_accepted_when_platform_reuses_image_url(monkeypatch):
    monkeypatch.setattr(wechat_uploader, "_find_wechat_cover_dialog", lambda _page: None)
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_signatures", lambda _card: frozenset({"same-url"}))
    monkeypatch.setattr(wechat_uploader, "_wechat_cover_preview_visual_signature", lambda _card: "after-pixels")

    assert wechat_uploader._is_wechat_cover_applied(
        _Page("封面已更新"), Mock(), frozenset({"same-url"}), "before-pixels"
    ) is True


def test_manual_cover_override_still_requires_platform_success_marker():
    assert wechat_uploader._has_wechat_cover_success_marker(_Page("封面已更新")) is True
    assert wechat_uploader._has_wechat_cover_success_marker(_Page("表单已保存")) is False


def test_cover_success_marker_accepts_visible_toast_when_body_text_lags():
    assert wechat_uploader._has_wechat_cover_success_marker(_ToastPage("")) is True

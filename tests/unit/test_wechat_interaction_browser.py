"""视频号评论浏览器安全边界与共享会话锁单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Codex | 覆盖前置门禁、规范锁路径、进程争用与崩溃释放。 |
"""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from video_processing.core.wechat_session_lock import (
    WeChatSessionLock,
    WeChatSessionLockBusy,
    canonical_wechat_session_lock_path,
    guarded_wechat_browser_session,
)
from video_processing.interaction.browser_commenter import (
    BrowserCommenter,
    COMMENT_SUBMIT_PATH,
    _SubmissionResponseWindow,
)


def _hold_lock_until_stopped(state_path: str, ready, stop) -> None:
    with WeChatSessionLock(state_path):
        ready.set()
        stop.wait(10)


def test_live_requires_durable_callback_before_browser(tmp_path: Path):
    state = tmp_path / "wechat_state.json"
    state.write_text("{}", encoding="utf-8")
    commenter = BrowserCommenter(state_path=state)

    status, evidence, error = commenter.post_comment("完整测试评论", "native-post")

    assert status == "FAILED"
    assert evidence is None
    assert "before_submit" in (error or "")


def test_lock_path_is_derived_from_canonical_state_path(tmp_path: Path):
    state = tmp_path / "folder" / ".." / "wechat_state.json"
    expected = tmp_path / ".wechat_state.json.browser.lock"
    assert canonical_wechat_session_lock_path(state) == expected.resolve()


def test_lock_contention_is_bounded_and_crash_releases_lock(tmp_path: Path):
    state = tmp_path / "wechat_state.json"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    stop = context.Event()
    process = context.Process(
        target=_hold_lock_until_stopped,
        args=(str(state), ready, stop),
    )
    process.start()
    assert ready.wait(5), "子进程未及时取得会话锁"

    with pytest.raises(WeChatSessionLockBusy, match="wechat session lock busy"):
        WeChatSessionLock(state, timeout_seconds=0.1, poll_interval_seconds=0.01).acquire()

    process.terminate()
    process.join(5)
    assert not process.is_alive()

    # flock 由内核绑定到文件描述符；持锁进程崩溃后必须可立即重新获取。
    with WeChatSessionLock(state, timeout_seconds=0.2):
        pass


def test_delayed_response_from_request_before_submit_window_is_ignored():
    class Request:
        method = "POST"
        url = f"https://channels.weixin.qq.com{COMMENT_SUBMIT_PATH}"
        post_data_json = {"objectId": "native-post", "content": "完整评论"}

    class Response:
        url = Request.url

        def __init__(self, request):
            self.request = request

        @staticmethod
        def json():
            return {
                "errCode": 0,
                "data": {"objectId": "native-post", "commentId": "comment-1"},
            }

    window = _SubmissionResponseWindow(
        "https://channels.weixin.qq.com/platform/interaction/comment",
        "native-post",
        "完整评论",
    )
    old_request = Request()
    # 旧请求未在本窗口捕获；即使它的响应延迟到窗口开启后到达也必须忽略。
    window.capture_response(Response(old_request))
    assert window.responses == []

    fresh_request = Request()
    window.capture_request(fresh_request)
    window.capture_response(Response(fresh_request))
    assert len(window.responses) == 1


def test_guard_disabled_preserves_call_and_creates_no_lock(tmp_path: Path):
    state = tmp_path / "default-state.json"
    calls = []

    @guarded_wechat_browser_session(
        enabled=lambda: False,
        state_parameter="state_path",
        busy_result=91,
    )
    def operation(state_path: str = str(state)) -> int:
        calls.append(state_path)
        return 7

    assert operation() == 7
    assert calls == [str(state)]
    assert not canonical_wechat_session_lock_path(state).exists()


def test_guard_enabled_binds_default_state_parameter(tmp_path: Path):
    state = tmp_path / "default-state.json"
    calls = []

    @guarded_wechat_browser_session(
        enabled=lambda: True,
        state_parameter="state_path",
        busy_result=91,
    )
    def operation(state_path: str = str(state)) -> int:
        calls.append(state_path)
        return 7

    assert operation() == 7
    assert calls == [str(state)]
    assert canonical_wechat_session_lock_path(state).is_file()


def test_guard_busy_returns_sentinel_without_calling_function(tmp_path: Path):
    state = tmp_path / "busy-state.json"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    stop = context.Event()
    process = context.Process(
        target=_hold_lock_until_stopped,
        args=(str(state), ready, stop),
    )
    process.start()
    assert ready.wait(5)
    calls = []

    @guarded_wechat_browser_session(
        enabled=lambda: True,
        state_parameter="state_path",
        busy_result=91,
    )
    def operation(state_path: str = str(state)) -> int:
        calls.append(state_path)
        return 7

    try:
        assert operation() == 91
        assert calls == []
    finally:
        stop.set()
        process.join(5)


class _FakeLocator:
    def __init__(self, count: int = 0, items: list | None = None, text: str = ""):
        self._count = count
        self._items = items or []
        self._text = text

    def count(self) -> int:
        if self._items:
            return len(self._items)
        return self._count

    def nth(self, idx: int):
        if idx < len(self._items):
            return self._items[idx]
        return _FakeLocator(count=0)

    def filter(self, has=None, has_text: str | None = None):
        if has_text is not None:
            filtered = [item for item in self._items if has_text in item._text]
            return _FakeLocator(items=filtered)
        return self


class _FakePage:
    def __init__(self, locators: dict[str, _FakeLocator] | None = None, url: str = "https://channels.weixin.qq.com/platform/interaction/comment"):
        self._locators = locators or {}
        self.url = url

    def locator(self, selector: str):
        for k, loc in self._locators.items():
            if k in selector or selector in k:
                return loc
        return _FakeLocator(count=0)


def test_resolve_target_card_by_direct_id_attribute():
    direct_card = _FakeLocator(count=1)
    page = _FakePage({"data-object-id": direct_card})
    resolved = BrowserCommenter.resolve_target_card(page, "export/native_id_1")
    assert resolved.count() == 1


def test_resolve_target_card_prefers_captured_post_ids_index_over_duplicate_title():
    # 模拟后台卡片：2 个卡片拥有相同标题前缀，但原生 ID 分别为 post_1 和 post_2
    card_0 = _FakeLocator(count=1, text="跟随 BNN Bloomberg 原声 标题前缀 第1集")
    card_1 = _FakeLocator(count=1, text="跟随 BNN Bloomberg 原声 标题前缀 第2集")
    feed_wraps = _FakeLocator(items=[card_0, card_1])

    page = _FakePage({".comment-feed-wrap:visible": feed_wraps})
    captured = ["export/post_1", "export/post_2"]

    # 目标为第二个视频 post_2
    resolved = BrowserCommenter.resolve_target_card(
        page,
        platform_post_id="export/post_2",
        video_title="跟随 BNN Bloomberg 原声",
        captured_post_ids=captured,
    )
    assert resolved.count() == 1
    assert resolved == card_1  # 严格依据 post_list 索引定位到 card_1，而不是因标题前缀匹配多张卡片报错


def test_resolve_target_card_falls_back_to_title_when_id_not_captured():
    card_0 = _FakeLocator(count=1, text="其他不相关的标题")
    card_1 = _FakeLocator(count=1, text="唯一特定标题的视频")
    feed_wraps = _FakeLocator(items=[card_0, card_1])

    page = _FakePage({".comment-feed-wrap:visible": feed_wraps})

    resolved = BrowserCommenter.resolve_target_card(
        page,
        platform_post_id="export/unseen_id",
        video_title="唯一特定标题的视频",
        captured_post_ids=["export/other_id"],
    )
    assert resolved.count() == 1
    assert resolved._items[0] == card_1


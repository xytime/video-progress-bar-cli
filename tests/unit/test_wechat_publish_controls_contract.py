"""正向视频发布控件单一真相源合约与正负例回归测试。

# Modification History
| Version | Date       | Author      | Description                                                        |
|---------|------------|-------------|--------------------------------------------------------------------|
| 1.2.0   | 2026-09-28 | Antigravity | 精简精确定位、支持 get_by_role / get_by_text 祖先核验、无 frames 适配正例及重复控件负例 |
| 1.1.0   | 2026-09-28 | Antigravity | 精确 key 映射、严格 DOM_ERROR 异常穿透与全量正负例隔离校验          |
| 1.0.0   | 2026-09-28 | Antigravity | 覆盖官方同源子 iframe 视频 input、选择视频上传容器及全套安全负例门禁 |
"""

from types import SimpleNamespace
from typing import Any
import pytest

from video_processing.core.wechat_page_contract import (
    check_strong_video_publish_controls,
    wait_for_publish_ready_with_spa_guard,
)


class MockLocator:
    def __init__(
        self,
        count: int = 0,
        visible: bool = False,
        raises_error: bool = False,
        eval_result: Any = True,
    ):
        self._count = count
        self._visible = visible
        self._raises_error = raises_error
        self._eval_result = eval_result

    def count(self) -> int:
        if self._raises_error:
            raise RuntimeError("DOM query failed during count()")
        return self._count

    @property
    def first(self) -> "MockLocator":
        return self

    def nth(self, idx: int) -> "MockLocator":
        return self

    def is_visible(self, **kwargs) -> bool:
        if self._raises_error:
            raise RuntimeError("DOM query failed during is_visible()")
        return self._visible

    def evaluate(self, script: str, **kwargs) -> Any:
        if self._raises_error:
            raise RuntimeError("DOM evaluation failed on locator")
        if callable(self._eval_result):
            return self._eval_result(script)
        return self._eval_result


class MockFrame(SimpleNamespace):
    __hash__ = object.__hash__

    def evaluate(self, script: str, **kwargs) -> Any:
        eval_fn = getattr(self, "_eval_fn", None)
        if callable(eval_fn):
            return eval_fn(script)
        return False


class MockPage:
    def __init__(
        self,
        url: str = "https://channels.weixin.qq.com/platform/post/create",
        frames: list[Any] | None = None,
        role_locators: dict[tuple[str, str, bool], MockLocator] | None = None,
        text_locators: dict[tuple[str, bool], MockLocator] | None = None,
        exact_locators: dict[str, MockLocator] | None = None,
        page_eval_fn: Any = None,
        locator_error: bool = False,
    ):
        self.url = url
        self.main_frame = MockFrame(url=url, _eval_fn=page_eval_fn)
        self.frames = frames if frames is not None else [self.main_frame]
        self._role_locators = role_locators or {}
        self._text_locators = text_locators or {}
        self._exact_locators = exact_locators or {}
        self._page_eval_fn = page_eval_fn
        self._locator_error = locator_error

    def evaluate(self, script: str, **kwargs) -> Any:
        if callable(self._page_eval_fn):
            return self._page_eval_fn(script)
        return False

    def get_by_role(self, role: str, name: str | None = None, exact: bool = False, **kwargs) -> MockLocator:
        if self._locator_error:
            raise RuntimeError("Locator creation threw DOM exception")
        key = (role, name or "", exact)
        return self._role_locators.get(key, MockLocator(count=0, visible=False))

    def get_by_text(self, text: str, exact: bool = False, **kwargs) -> MockLocator:
        if self._locator_error:
            raise RuntimeError("Locator creation threw DOM exception")
        key = (text, exact)
        return self._text_locators.get(key, MockLocator(count=0, visible=False))

    def locator(self, selector: str, **kwargs) -> MockLocator:
        if self._locator_error:
            raise RuntimeError("Locator creation threw DOM exception")
        return self._exact_locators.get(selector, MockLocator(count=0, visible=False))

    def wait_for_timeout(self, ms: int) -> None:
        pass


# =========================================================================
# 正例 (Positives)
# =========================================================================

def test_positive_official_channels_iframe_with_video_input():
    """正例 1：官方 CREATE 路由下，子 iframe 来源于 channels 且包含真实视频 input。"""
    sub_frame = MockFrame(
        url="https://channels.weixin.qq.com/platform/uploader",
        _eval_fn=lambda s: True if "video" in s or "mp4" in s else False,
    )
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        frames=[MockFrame(url="https://channels.weixin.qq.com/platform/post/create"), sub_frame],
    )

    ready, err = check_strong_video_publish_controls(page)
    assert ready is True
    assert err is None

    spa_ready, spa_err = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=0.5)
    assert spa_ready is True
    assert spa_err is None


def test_positive_page_without_frames_adapter():
    """正例 2：无 frames 属性的测试/轻量 MockPage，直接由顶层 evaluate 探针识别。"""
    class BarePage:
        def __init__(self):
            self.url = "https://channels.weixin.qq.com/platform/post/create"

        def evaluate(self, script: str) -> bool:
            return "video" in script or "mp4" in script

        def locator(self, selector: str) -> MockLocator:
            return MockLocator(count=0, visible=False)

        def wait_for_timeout(self, ms: int) -> None:
            pass

    page = BarePage()
    ready, err = check_strong_video_publish_controls(page)
    assert ready is True
    assert err is None


def test_positive_visible_upload_container_with_choose_video_button():
    """正例 3：官方 CREATE 路由下，get_by_text('选择视频', exact=True) 唯一可见且处于上传容器内。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        text_locators={
            ("选择视频", True): MockLocator(count=1, visible=True, eval_result=True),
        },
    )

    ready, err = check_strong_video_publish_controls(page)
    assert ready is True
    assert err is None

    spa_ready, spa_err = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=0.5)
    assert spa_ready is True
    assert spa_err is None


def test_positive_legacy_upload_video_button():
    """正例 4：兼容旧版精确 get_by_role('button', name='上传视频', exact=True) 唯一可见。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        role_locators={
            ("button", "上传视频", True): MockLocator(count=1, visible=True),
        },
    )

    ready, err = check_strong_video_publish_controls(page)
    assert ready is True
    assert err is None


# =========================================================================
# 负例 (Negatives)
# =========================================================================

def test_negative_bare_choose_video_without_upload_ancestor_rejected():
    """负例 1：孤立的 '选择视频' 文本脱离上传容器（eval_result 为 False，无 upload 祖先）时拒绝。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        text_locators={
            ("选择视频", True): MockLocator(count=1, visible=True, eval_result=False),
        },
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "PAGE_UNREADY"


def test_negative_hidden_upload_container_button_rejected():
    """负例 2：上传容器内控件存在但为隐藏状态时（visible=False），绝不误判为就绪。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        text_locators={
            ("选择视频", True): MockLocator(count=1, visible=False, eval_result=True),
        },
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "PAGE_UNREADY"


def test_negative_duplicate_visible_choose_video_buttons_rejected():
    """负例 3：页面存在多个重复可见的 '选择视频' 控件时，判定为冲突状态拒绝。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        text_locators={
            ("选择视频", True): MockLocator(count=2, visible=True, eval_result=True),
        },
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "PAGE_UNREADY"


def test_negative_duplicate_visible_legacy_upload_video_buttons_rejected():
    """负例 4：页面存在多个重复可见的旧版 '上传视频' 按钮时，拒绝。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        role_locators={
            ("button", "上传视频", True): MockLocator(count=2, visible=True),
        },
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "PAGE_UNREADY"


def test_negative_untrusted_iframe_with_video_input_rejected():
    """负例 5：非官方域名、非默认端口或带有 userinfo 的 iframe 内部 input 必须严格拒绝。"""
    untrusted_urls = [
        "https://evil.example.com/uploader",
        "https://channels.weixin.qq.com:8443/uploader",
        "https://attacker@channels.weixin.qq.com/uploader",
        "http://channels.weixin.qq.com/uploader",
    ]
    for bad_url in untrusted_urls:
        bad_frame = MockFrame(
            url=bad_url,
            _eval_fn=lambda s: True,  # 即使其声明包含 video input
        )
        page = MockPage(
            url="https://channels.weixin.qq.com/platform/post/create",
            frames=[MockFrame(url="https://channels.weixin.qq.com/platform/post/create"), bad_frame],
        )
        ready, err = check_strong_video_publish_controls(page)
        assert ready is False
        assert err == "PAGE_UNREADY"


def test_negative_open_weixin_iframe_cannot_supply_publish_input():
    """负例 6：微信开放平台 (open.weixin.qq.com) 仅用于登录扫码，其内部 input 绝不能当作视频发布控件。"""
    open_frame = MockFrame(
        url="https://open.weixin.qq.com/connect/login",
        _eval_fn=lambda s: True,
    )
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        frames=[MockFrame(url="https://channels.weixin.qq.com/platform/post/create"), open_frame],
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "PAGE_UNREADY"


def test_negative_image_only_file_input_rejected():
    """负例 7：纯图片类型的 input[type='file']（如封面/头像）必须拒绝。"""
    def eval_image_only(script: str) -> bool:
        if "video" in script or "mp4" in script:
            return False
        return True

    sub_frame = MockFrame(
        url="https://channels.weixin.qq.com/platform/uploader",
        _eval_fn=eval_image_only,
    )
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        frames=[MockFrame(url="https://channels.weixin.qq.com/platform/post/create"), sub_frame],
        page_eval_fn=eval_image_only,
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "PAGE_UNREADY"


def test_negative_explicit_login_prompt_blocks_positive_controls():
    """负例 8：即使存在有效视频控件，但若页面出现明确登录扫码提示，SPA guard 必须返回 LOGIN_REQUIRED。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        exact_locators={
            ".login-box": MockLocator(count=1, visible=True),
        },
        text_locators={
            ("选择视频", True): MockLocator(count=1, visible=True, eval_result=True),
        },
    )
    spa_ready, spa_err = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=0.5)
    assert spa_ready is False
    assert spa_err == "LOGIN_REQUIRED"


def test_negative_non_create_url_blocks_even_with_controls():
    """负例 9：若处于作品列表页 (/platform/post/list)，即便存在控件也必须返回 PAGE_UNREADY。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/list",
        text_locators={
            ("选择视频", True): MockLocator(count=1, visible=True, eval_result=True),
        },
    )
    spa_ready, spa_err = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=0.5)
    assert spa_ready is False
    assert spa_err == "PAGE_UNREADY"


def test_negative_subframe_evaluate_exception_propagates_dom_error():
    """负例 10 (Fail-Closed 核心)：官方子 frame evaluate 抛出异常时，不得吞掉，必须返回 DOM_ERROR。"""
    def eval_throw(s):
        raise RuntimeError("Context destroyed during probe")

    sub_frame = MockFrame(
        url="https://channels.weixin.qq.com/platform/uploader",
        _eval_fn=eval_throw,
    )
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        frames=[MockFrame(url="https://channels.weixin.qq.com/platform/post/create"), sub_frame],
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "DOM_ERROR"


def test_negative_top_page_evaluate_exception_propagates_dom_error():
    """负例 11 (Fail-Closed 核心)：顶层页面 evaluate 抛出异常时，必须返回 DOM_ERROR。"""
    def eval_throw(s):
        raise RuntimeError("Top frame evaluate error")

    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        page_eval_fn=eval_throw,
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "DOM_ERROR"


def test_negative_locator_exception_propagates_dom_error():
    """负例 12 (Fail-Closed 核心)：控件查找抛出异常时，不得吞掉，必须返回 DOM_ERROR。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        locator_error=True,
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "DOM_ERROR"


def test_negative_subframe_navigation_race_condition():
    """负例 13：子 iframe evaluate 虽返回 True，但随后 URL 发生重定向或非官方漂移，防导航竞态。"""
    class NavigatingFrame(SimpleNamespace):
        __hash__ = object.__hash__

        def __init__(self):
            super().__init__(url="https://channels.weixin.qq.com/platform/uploader")

        def evaluate(self, script: str) -> bool:
            # 模拟导航竞态：eval 完成瞬间被重定向到非官方地址
            self.url = "https://evil.example.com/phishing"
            return True

    nav_frame = NavigatingFrame()
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        frames=[MockFrame(url="https://channels.weixin.qq.com/platform/post/create"), nav_frame],
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "PAGE_UNREADY"


def test_negative_candidate_count_exceeds_upper_bound_rejected():
    """负例 14：候选元素数量超过上限 (MAX_PROBE_CANDIDATES) 时，拒绝妄断唯一。"""
    page = MockPage(
        url="https://channels.weixin.qq.com/platform/post/create",
        text_locators={
            ("选择视频", True): MockLocator(count=25, visible=True, eval_result=True),
        },
    )
    ready, err = check_strong_video_publish_controls(page)
    assert ready is False
    assert err == "PAGE_UNREADY"


"""微信快捷登录资料授权回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 覆盖快捷登录后自动点击昵称头像授权页的允许按钮 |
"""

from scripts.wechat_uploader import _try_wechat_quick_login


class _Locator:
    def __init__(self, visible=True, on_click=None):
        self.visible = visible
        self.on_click = on_click

    @property
    def first(self):
        return self

    def count(self):
        return int(self.visible)

    def is_visible(self):
        return self.visible

    def filter(self, **_kwargs):
        return self

    def click(self, **_kwargs):
        if self.on_click:
            self.on_click()


class _AuthorizationFrame:
    url = "https://open.weixin.qq.com/connect/login"

    def __init__(self):
        self.quick_clicked = False
        self.allow_clicked = False

    def locator(self, _selector):
        return _Locator(on_click=lambda: setattr(self, "quick_clicked", True))

    def get_by_text(self, _text, exact=False):
        assert exact is False
        return _Locator(visible=self.quick_clicked)

    def get_by_role(self, role, name, exact):
        assert (role, name, exact) == ("button", "允许", True)
        return _Locator(
            visible=self.quick_clicked,
            on_click=lambda: setattr(self, "allow_clicked", True),
        )


class _AuthorizationPage:
    def __init__(self, frame):
        self.frames = [frame]
        self.waited_for = None

    def wait_for_timeout(self, _milliseconds):
        pass

    def wait_for_url(self, pattern, timeout):
        self.waited_for = (pattern, timeout)


def test_quick_login_approves_nickname_avatar_authorization_before_waiting_for_publish_page():
    frame = _AuthorizationFrame()
    page = _AuthorizationPage(frame)

    assert _try_wechat_quick_login(page) is True
    assert frame.allow_clicked is True
    assert page.waited_for == ("**/post/create", 30000)

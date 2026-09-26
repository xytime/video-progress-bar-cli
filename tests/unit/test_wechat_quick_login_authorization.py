"""微信快捷登录时序和授权来源回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-09-26 | Codex | 覆盖迟到授权、截止时间、可信来源、监听清理和即时跳转。 |
| 1.1.0 | 2026-08-25 | Codex | 断言桌面授权监听仅在网页快捷登录按钮点击后启动。 |
| 1.0.0 | 2026-07-29 | Codex | 覆盖快捷登录后自动点击昵称头像授权页的允许按钮。 |
"""
from types import SimpleNamespace
import pytest
from scripts import wechat_uploader as uploader


class Locator:
    def __init__(self, visible=False, on_click=lambda: None):
        self.visible, self.on_click = visible, on_click
    @property
    def first(self): return self
    def count(self): return int(self.visible)
    def is_visible(self): return self.visible
    def click(self, **kwargs): self.on_click()


class LoginPage:
    def __init__(self, delay=0, origin='https://open.weixin.qq.com', prompt='视频号创作平台申请使用你的昵称、头像'):
        self.now, self.delay, self.prompt = 0, delay, prompt
        self.url = 'https://channels.weixin.qq.com/platform/login'
        self.clicked = self.allowed = False
        self.frame = SimpleNamespace(url=origin+'/connect/login')
        self.frame.get_by_text = self.get_by_text
        self.frame.get_by_role = self.get_by_role
        self.frames = [self.frame]
    def get_by_text(self, text, exact=False):
        return Locator(self.clicked and self.now >= self.delay and bool(text.search(self.prompt)))
    def get_by_role(self, role, name, exact=True):
        assert (role, exact) == ('button', True)
        if name == '微信快捷登录':
            return Locator(True, lambda: setattr(self, 'clicked', True))
        assert name == '允许'
        return Locator(self.clicked and self.now >= self.delay, self.allow)
    def allow(self):
        self.allowed = True
        self.url = 'https://channels.weixin.qq.com/platform/post/create'
    def wait_for_timeout(self, milliseconds): self.now += milliseconds / 1000


@pytest.fixture
def login(monkeypatch):
    def make(**kwargs):
        page = LoginPage(**kwargs)
        # 不替换全局 time 模块，不影响隔离 runner 的真实时钟。
        monkeypatch.setattr(uploader, 'time', SimpleNamespace(monotonic=lambda: page.now))
        # Playwright Frame 可哈希；SimpleNamespace 用测试子类补足。
        class Frame(SimpleNamespace):
            __hash__ = object.__hash__
        page.frame = Frame(**vars(page.frame))
        page.frames = [page.frame]
        return page
    return make


@pytest.mark.parametrize('delay', [0, 11, 29])
def test_authorization_is_polled_throughout_entire_deadline(login, delay):
    page = login(delay=delay)
    assert uploader._try_wechat_quick_login(page)
    assert page.allowed
    assert page.now < 30


def test_split_authorization_text_is_accepted(login):
    page = login(prompt='视频号创作平台\n 申请使用你的昵称、头像')
    assert uploader._try_wechat_quick_login(page)


@pytest.mark.parametrize('kwargs', [
    {'delay': 31}, {'origin': 'https://unrelated.invalid'},
    {'prompt': '其他应用申请使用'},
])
def test_timeout_or_unrelated_authorization_does_not_succeed(login, kwargs):
    page = login(**kwargs)
    assert not uploader._try_wechat_quick_login(page)
    assert not page.allowed
    assert page.now <= 30


def test_watcher_lifecycle_is_scoped_to_clicked_quick_login(login):
    page = login()
    events = []
    def start():
        assert page.clicked
        events.append('start')
    watcher = SimpleNamespace(start=start, stop=lambda: events.append('stop'))
    assert uploader._try_wechat_quick_login(page, watcher)
    assert events == ['start', 'stop']


def test_immediate_redirect_does_not_wait_for_nonexistent_allow(login):
    page = login(delay=99)
    watcher = SimpleNamespace(start=lambda: setattr(page, 'url', 'https://channels.weixin.qq.com/platform/post/create'), stop=lambda: None)
    assert uploader._try_wechat_quick_login(page, watcher)
    assert page.now == 0
    assert not page.allowed


def test_watcher_stops_when_page_closes(login):
    page = login(delay=99)
    def closed(_): raise RuntimeError('page closed')
    page.wait_for_timeout = closed
    events = []
    watcher = SimpleNamespace(start=lambda: None, stop=lambda: events.append('stop'))
    with pytest.raises(RuntimeError): uploader._try_wechat_quick_login(page, watcher)
    assert events == ['stop']

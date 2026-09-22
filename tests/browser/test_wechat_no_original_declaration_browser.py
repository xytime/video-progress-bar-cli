"""隔离 Chromium 验证不声明原创的三态界面读取；不连接视频号。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 未勾选须有明确控件证据，已勾选、隐藏、重复与未知控件阻断。 |
"""
import pytest

from scripts.wechat_uploader import _original_declaration_ui_state, _original_declaration_publish_allowed
from tests.browser_fixtures import chromium


@pytest.mark.parametrize("html,state", [
    ('<label><input type="checkbox">声明原创</label>', "NOT_DECLARED"),
    ('<label><input type="checkbox" checked>声明原创</label>', "DECLARED"),
    ('<button role="switch" aria-checked="false">原创声明</button>', "NOT_DECLARED"),
    ('<button role="switch" aria-checked="true">原创声明</button>', "DECLARED"),
    ('<button role="checkbox" aria-checked="mixed">声明原创</button>', "UNKNOWN"),
    ('<button role="checkbox">声明原创</button>', "UNKNOWN"),
    ('<label style="display:none"><input type="checkbox">声明原创</label>', "UNKNOWN"),
    ('<label><input type="checkbox">声明原创</label>' * 2, "UNKNOWN"),
    ('<label><input type="checkbox">我已阅读原创声明</label>', "UNKNOWN"),
    ('<label><input type="checkbox">其他设置</label><span>声明原创</span>', "UNKNOWN"),
    ('<label><input type="checkbox">声明原创</label><script>document.querySelector("input").indeterminate=true</script>', "UNKNOWN"),
])
def test_no_original_requires_unambiguous_visible_control(chromium, html, state):
    page = chromium.new_page()
    try:
        page.set_content(html)
        actual = _original_declaration_ui_state(page)
        assert actual == state
        assert _original_declaration_publish_allowed(
            declare_original=False, require_original_declaration=False,
            declaration_applied=actual == "DECLARED", declaration_absent_confirmed=actual == "NOT_DECLARED",
        ) is (state == "NOT_DECLARED")
    finally:
        page.close()


def test_changed_checked_state_is_not_a_negative_confirmation(chromium):
    page = chromium.new_page()
    try:
        page.set_content('<label><input type="checkbox">声明原创</label>')
        assert _original_declaration_ui_state(page) == "NOT_DECLARED"
        page.get_by_role("checkbox", name="声明原创").check()
        assert _original_declaration_ui_state(page) == "DECLARED"
    finally:
        page.close()

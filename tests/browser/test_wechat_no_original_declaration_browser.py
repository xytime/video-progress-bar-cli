"""隔离 Chromium 验证不声明原创的三态界面读取；不连接视频号。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-22 | Codex | 原创三态与真实分列 Shadow DOM 表单、直接发表提醒及异常状态阻断。 |
"""
import pytest

from scripts.wechat_uploader import (
    _confirm_no_original_interceptor, _original_declaration_ui_state,
    _original_declaration_publish_allowed,
)
from tests.browser_fixtures import chromium


def _live_form(checked="", label="声明原创"):
    """2026-09-22 页面实证：字段名在左列，控件与说明位于右列。"""
    return f'''<div class="form-item cell-center post-with-link">
      <div class="label with-tip-label"><span>{label}</span></div>
      <div class="form-item-body"><div class="declare-original-checkbox">
        <label class="ant-checkbox-wrapper"><span class="ant-checkbox">
          <input type="checkbox" class="ant-checkbox-input" {checked}>
          <span class="ant-checkbox-inner"></span></span>
          <span>声明后，作品将展示原创标记，有机会获得广告收入。</span>
        </label></div></div>
      <div class="declare-original-dialog" style="display:none">
        <label><input type="checkbox">我已阅读原创声明</label><button>声明原创</button>
      </div></div>'''


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


@pytest.mark.parametrize("html,state", [
    (_live_form(), "NOT_DECLARED"),
    (_live_form("checked"), "DECLARED"),
    (_live_form() * 2, "UNKNOWN"),
    (_live_form(label="其他设置"), "UNKNOWN"),
    ('<div style="display:none">' + _live_form() + '</div>', "UNKNOWN"),
    (_live_form() + '<label><input type="checkbox" checked>声明原创</label>', "UNKNOWN"),
    (_live_form().replace('class="declare-original-checkbox"', 'class="unrecognized"'), "UNKNOWN"),
])
def test_live_split_label_structure_inside_shadow_root(chromium, html, state):
    page = chromium.new_page()
    try:
        page.set_content('<div id="micro-app"></div>')
        page.locator('#micro-app').evaluate(
            '(node, html) => { node.attachShadow({mode:"open"}).innerHTML = html; }', html,
        )
        assert _original_declaration_ui_state(page) == state
    finally:
        page.close()


def test_live_control_state_is_reread_and_indeterminate_is_rejected(chromium):
    page = chromium.new_page()
    try:
        page.set_content(_live_form())
        checkbox = page.locator('.declare-original-checkbox input')
        assert _original_declaration_ui_state(page) == 'NOT_DECLARED'
        checkbox.check()
        assert _original_declaration_ui_state(page) == 'DECLARED'
        checkbox.evaluate('node => { node.checked = false; node.indeterminate = true; }')
        assert _original_declaration_ui_state(page) == 'UNKNOWN'
    finally:
        page.close()


@pytest.mark.parametrize('form,duplicate,allowed', [
    (_live_form(), False, True),
    (_live_form('checked'), False, False),
    (_live_form(label='未知设置'), False, False),
    (_live_form(), True, False),
])
def test_original_reminder_only_direct_submission_is_allowed(chromium, tmp_path, form, duplicate, allowed):
    page = chromium.new_page()
    footer = '''<div class="original-interceptor-footer"><div class="no-tip-btn">不再提醒</div>
      <div class="btn-wrapper"><button onclick="window.action='direct'">直接发表</button>
      <button onclick="window.action='original'">声明原创</button></div></div>'''
    try:
        page.set_content(form + footer * (2 if duplicate else 1))
        assert _confirm_no_original_interceptor(page, tmp_path) is allowed
        assert page.evaluate('window.action || null') == ('direct' if allowed else None)
        assert (tmp_path / 'original_declaration_receipt.json').exists() is allowed
        assert (tmp_path / 'no_original_interceptor_before_confirm.png').exists() is allowed
    finally:
        page.close()

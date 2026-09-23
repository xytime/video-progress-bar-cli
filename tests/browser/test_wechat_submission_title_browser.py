"""真实隔离 Chromium 核验提交前短标题回读，不连接平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-24 | Codex | 表单实际值用于精确绑定；Shadow DOM、歧义和提交前漂移均验证。 |
"""
import pytest

from scripts.wechat_uploader import _read_confirmed_submission_title
from tests.browser_fixtures import chromium


@pytest.mark.parametrize("shadow", [False, True])
def test_confirmed_title_tracks_live_form_without_guessing(chromium, shadow, tmp_path):
    page = chromium.new_page()
    try:
        form = '<div class="post-short-title-wrap"><input placeholder="概括视频主要内容，字数建议6-16个字符"></div>'
        if shadow:
            page.set_content('<div id="app"></div>')
            page.locator('#app').evaluate('(node, html) => { node.attachShadow({mode:"open"}).innerHTML = html; }', form)
        else:
            page.set_content(form)
        field = page.locator('input')
        field.fill('英语世界NASDAQ创新高')
        field.blur()
        assert _read_confirmed_submission_title(page, '英语世界NASDAQ创新高') == '英语世界NASDAQ创新高'
        assert _read_confirmed_submission_title(page, '英语世界｜NASDAQ创新高后回调') == ''
        page.screenshot(path=str(tmp_path / 'confirmed-short-title.png'))
        field.fill('用户刚改成另一个标题')
        assert _read_confirmed_submission_title(page, '英语世界NASDAQ创新高') == ''
        field.evaluate('node => node.style.display = "none"')
        assert _read_confirmed_submission_title(page, '用户刚改成另一个标题') == ''
        page.set_content(form * 2)
        assert _read_confirmed_submission_title(page, '英语世界NASDAQ创新高') == ''
    finally:
        page.close()

"""已展开观众子回复时，真实 Chromium 验证根评论控件作用域与歧义阻断。"""
import pytest
from tests.browser_fixtures import chromium
from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplyBrowserAdapter


@pytest.mark.parametrize('root_buttons', [1, 2])
def test_reply_trigger_excludes_nested_audience_reply(chromium, tmp_path, root_buttons):
    page = chromium.new_page()
    try:
        buttons = '<button class="action-icon weui-icon-outlined-comment" onclick="openRoot()">回复</button>' * root_buttons
        page.set_content('''<div class="comment-item" id="root">
          <div class="comment-item-main"><div class="comment-main-content">父评论
          <div class="comment-row"><div class="comment-actions">ROOT_BUTTONS</div></div>
          <div class="comment-reply-list"><div class="comment-item">
            <div class="comment-item-main">另一观众的回复
              <button class="action-icon weui-icon-outlined-comment" onclick="window.childClicked=true">回复</button>
            </div>
          </div></div></div></div>
        </div><script>
        window.rootClicked=0; window.childClicked=false;
        function openRoot(){window.rootClicked++;document.querySelector('#root').insertAdjacentHTML('beforeend',
        '<textarea data-comment-editor></textarea><button data-submit disabled>评论</button>');}
        </script>'''.replace('ROOT_BUTTONS', buttons))
        adapter = SecondaryReplyBrowserAdapter(state_path=tmp_path/'state.json')
        result = adapter._open_and_bind_reply_controls(page, page.locator('#root'), root_comment_id='root')
        assert page.evaluate('window.childClicked') is False
        if root_buttons == 1:
            assert result['ok'] is True
            assert page.evaluate('window.rootClicked') == 1
            assert result['textarea'].input_value() == ''
            assert result['submit_btn'].is_disabled()
        else:
            assert result['ok'] is False and '歧义' in result['error']
            assert page.evaluate('window.rootClicked') == 0
    finally:
        page.close()

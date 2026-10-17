"""无夹具 data-author-id 的接口回读，以及危险按钮相邻控件回归。"""
import pytest

from tests.browser_fixtures import chromium
from tests.browser.test_secondary_reply_browser import secondary_reply_harness
from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplyBrowserAdapter, SecondaryReplySubmissionGuard


@pytest.mark.parametrize('author, flag, expected', [('native@author', 0, True), ('audience', 0, False), ('audience', None, False)])
def test_native_identity_and_unknown_pagination(chromium, author, flag, expected):
    page = chromium.new_page()
    try:
        page.set_content('<div class="comment-item">完整原文<div class="comment-reply-list">回复</div></div>')
        adapter = SecondaryReplyBrowserAdapter()
        adapter._active_export_id = 'export/test'
        adapter._captured_comments['root'] = {
            'export_id': 'export/test', 'content_prefix': '完整原文', 'downContinueFlag': flag,
            'levelTwoComment': [{'username': author, 'commentNickname': '假装作者', 'commentId': 'r', 'commentContent': '回复'}],
        }
        replied, complete, parent = adapter._check_author_already_replied(page, 'root', 'native@author')
        assert replied is expected and parent is not None
        assert complete == ('PAGINATION_UNKNOWN' if flag is None else 'COMPLETE')
    finally:
        page.close()


def test_native_readback_uses_fresh_api_identity_and_exact_body(chromium):
    page = chromium.new_page()
    adapter = SecondaryReplyBrowserAdapter()
    try:
        page.set_content('<div class="comment-feed-wrap" onclick="console.log(\'load-comments\')">目标作品</div><div class="comment-item">完整原文</div>')
        def populate(message):
            if message.text == 'load-comments':
                adapter._active_export_id = 'export/test'
                adapter._captured_comments['root'] = {
                    'export_id': 'export/test', 'content_prefix': '完整原文', 'downContinueFlag': 0,
                    'levelTwoComment': [{'username': 'native@author', 'commentId': 'r', 'commentContent': '完整回复'}],
                }
        page.on('console', populate)
        adapter._post_descriptions['export/test'] = '目标作品'
        kwargs = dict(platform_post_id='export/test', root_comment_id='root', author_id='native@author')
        assert adapter.find_author_reply(page, reply_content='完整回复', **kwargs) == ('FOUND', 'r')
        assert adapter.find_author_reply(page, reply_content='完整回复 ', **kwargs) == ('NOT_FOUND', '')
    finally:
        page.close()


def test_expand_reloads_api_author_and_cursor(chromium):
    page = chromium.new_page()
    adapter = SecondaryReplyBrowserAdapter()
    try:
        page.set_content('<div class="comment-item">完整原文<button class="show-more-replies" onclick="console.log(\'expanded\'); this.remove()">展开</button></div>')
        adapter._active_export_id = 'export/test'
        adapter._captured_comments['root'] = {
            'export_id': 'export/test', 'content_prefix': '完整原文', 'downContinueFlag': 1, 'levelTwoComment': []}
        def expanded(message):
            adapter._captured_comments['root'] = {
                'export_id': 'export/test', 'content_prefix': '完整原文', 'downContinueFlag': 0,
                'levelTwoComment': [{'username': 'native@author', 'commentId': 'r'}]}
        page.on('console', expanded)
        replied, complete, _ = adapter._check_author_already_replied(page, 'root', 'native@author')
        assert replied and complete == 'COMPLETE'
    finally:
        page.close()


@pytest.mark.parametrize('mode', ['like-only', 'missing-submit', 'disabled-submit'])
def test_no_wrong_button_or_premature_intent(secondary_reply_harness, mode):
    h = secondary_reply_harness
    page = h['page']
    page.goto('http://wechat-fixture.invalid/platform/interaction/comment')
    # 作品卡片处理器生成详情后，插入一个排在回复按钮之前的点赞按钮。
    page.evaluate('''(mode) => {
        document.addEventListener('click', () => {
            const p = document.querySelector('[data-comment-id="synth_cmt_101"]');
            if (!p || p.dataset.patched) return;
            p.dataset.patched = 'true';
            const like = document.createElement('button');
            like.textContent = '赞'; like.onclick = () => window.wrongClick = true;
            p.prepend(like);
            if (mode === 'like-only') p.querySelector('[data-reply]').remove();
            if (mode === 'missing-submit') p.querySelector('[data-submit]').remove();
            if (mode === 'disabled-submit') p.querySelector('[data-submit]').disabled = true;
        });
    }''', mode)
    adapter = SecondaryReplyBrowserAdapter(state_path=h['state_file'])
    guard = SecondaryReplySubmissionGuard('export/synth_video_888', 'synth_cmt_101', '谢谢。',
                                         expected_finder_id='v2_synthetic_author_finder_id@finder')
    intents = []
    status, _, _ = adapter._interact_with_page(
        page, task_id=1, platform_post_id='export/synth_video_888', root_comment_id='synth_cmt_101',
        reply_content='谢谢。', attempt_dir=h['tmp_path'], guard=guard,
        before_submit=lambda: intents.append(True) or True,
    )
    assert status == 'FAILED' and not intents
    assert page.evaluate('window.wrongClick === true') is False
    assert not h['writes']

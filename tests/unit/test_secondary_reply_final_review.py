"""最终正文和真实接口判重回归；不接触平台或生产状态。"""
from types import SimpleNamespace

import pytest

from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplyBrowserAdapter
from video_processing.interaction.secondary_reply_contract import SecondaryReplyContractError
from video_processing.interaction.secondary_reply_service import SecondaryReplyService


def test_final_review_rejects_unreviewed_formatted_body():
    service = SecondaryReplyService()
    with pytest.raises(SecondaryReplyContractError, match="FINAL_TEXT_DIFFERS"):
        service.validate_for_submission("谢谢分享。", "Thanks.", "完全不同的正文")
    assert service.validate_for_submission("谢谢分享。", "Thanks.", "谢谢分享。\nThanks.") == "谢谢分享。\nThanks."


def test_listener_without_send_guard_retains_native_identity_and_unknown_pagination():
    adapter = SecondaryReplyBrowserAdapter()
    handlers = {}
    page = SimpleNamespace(on=lambda event, fn: handlers.update({event: fn}))
    adapter._captured_comments['stale'] = {}
    adapter._active_export_id = 'old'
    adapter._setup_page_listeners(page)
    assert not adapter._captured_comments and adapter._active_export_id is None
    req = SimpleNamespace(method='POST', url='https://channels.weixin.qq.com/comment/comment_list',
                          post_data_json={'exportId': 'export/test'})
    handlers['request'](req)
    comment = {'commentId': 'root', 'commentContent': '完整原文', 'levelTwoComment': [
        {'commentId': 'reply', 'username': 'native@author', 'commentNickname': '普通昵称',
         'commentContent': '回复'}]}
    response = SimpleNamespace(url=req.url, request=req, status=200,
                               json=lambda: {'data': {'comment': [comment]}})
    handlers['response'](response)
    captured = adapter._captured_comments['root']
    assert captured['levelTwoComment'][0]['username'] == 'native@author'
    assert captured['downContinueFlag'] is None
    assert captured['export_id'] == 'export/test'
    adapter._setup_page_listeners(page)
    assert not adapter._captured_comments


def test_listener_rejects_foreign_response_origin():
    adapter = SecondaryReplyBrowserAdapter()
    handlers = {}
    adapter._setup_page_listeners(SimpleNamespace(on=lambda event, fn: handlers.update({event: fn})))
    handlers['response'](SimpleNamespace(url='https://evil.invalid/comment/comment_list', status=200))
    assert not adapter._captured_comments

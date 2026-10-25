"""隔离 Chromium 的原生活动及顶层续扫边界。

依赖：本测试 -> browser adapter -> context guard；合成传输只替换网络最末层。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1 | 2026-10-25 | Codex | 验证真请求模板、游标、共享列表预算与只读发布拦截。 |
"""
import json
from types import SimpleNamespace
from playwright.sync_api import Route
from tests.browser_fixtures import chromium
from video_processing.core import wechat_session_lock as locks
from video_processing.interaction.secondary_reply_browser_adapter import (
    SecondaryReplyBrowserAdapter, COMMENT_POST_LIST_PATH, COMMENT_LIST_PATH,
)


def test_activity_probe_and_comment_pages_stay_in_original_context_budget(chromium, monkeypatch, tmp_path):
    session=SimpleNamespace(_request_started=True,_request_limited=False,_request_count=0,
        _list_request_count=0,purpose='评论扫描',state_path=tmp_path/'state.json',
        request_guard=SimpleNamespace(observe_response=lambda response:False))
    token=locks._SESSION.set(session)
    context=chromium.new_context(); sent=[]
    def transport(route, **kwargs):
        data=route.request.post_data_json;sent.append((route.request.url,data))
        if route.request.url.endswith(COMMENT_POST_LIST_PATH):
            route.fulfill(status=201,json={'errCode':0,'data':{'list':[
                {'objectId':'native-post','desc':{'description':'完整文案，用于独立严格匹配本地发布记录，绝不使用标题或下标来猜测作品。'},
                 'commentCount':3,'unreadcommentCount':2}], 'lastBuff':'server-post-cursor'}})
        else:
            n={'':1,'server-comment-1':2,'server-comment-2':3}[data['lastBuff']]
            route.fulfill(status=201,json={'errCode':0,'data':{'comment':[
                {'commentId':str(n),'commentContent':'audience '+str(n)}],
                'downContinueFlag':int(n<3),'lastBuff':('server-comment-'+str(n)) if n<3 else ''}})
    monkeypatch.setattr(Route,'continue_',transport)
    try:
        locks.guard_wechat_context(context)
        page=context.new_page();a=SecondaryReplyBrowserAdapter()
        a._setup_page_listeners(page);a._setup_list_pagination(page,post_id='export/post')
        page.route('https://channels.weixin.qq.com/fixture',lambda route:route.fulfill(content_type='text/html',body='''
            <script>async function read(path,payload) {return (await fetch(path,{method:'POST',
              headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();}</script>'''))
        page.goto('https://channels.weixin.qq.com/fixture')
        post={'pageSize':10,'lastBuff':'','onlyUnread':False,'needAllCommentCount':True,'nativeField':'keep'}
        page.evaluate('args=>read(...args)',[COMMENT_POST_LIST_PATH,post])
        a._probe_unread_activity(page)
        assert sent[1][1]==dict(post,onlyUnread=True)
        assert a.observed_post_activity['native-post']['unread_count']==2
        page.evaluate('args=>read(...args)',[COMMENT_LIST_PATH,{'exportId':'native-post','lastBuff':'','nativeField':'keep'}])
        page.wait_for_timeout(50)
        a._bound_scene_post_id='native-post'
        payload,error,pages=a._collect_comment_pages(page)
        assert not error and pages==3
        assert [c['commentId'] for c in payload['data']['comment']]==['1','2','3']
        assert all(data['exportId']=='native-post' and data['nativeField']=='keep' for url,data in sent if url.endswith(COMMENT_LIST_PATH))
        # 后页游标在全新读取中只辅助具名作品导航，仍需真实父评论身份。
        a.set_root_page_hint('export/post','server-comment-2')
        page.evaluate('args=>read(...args)',[COMMENT_LIST_PATH,{'exportId':'native-post','lastBuff':''}])
        assert sent[-1][1]['lastBuff']=='server-comment-2'
        page.evaluate('args=>read(...args)',[COMMENT_LIST_PATH,{'exportId':'another-post','lastBuff':''}])
        assert sent[-1][1]['lastBuff']==''
        for _ in range(4):
            page.evaluate('args=>read(...args)',[COMMENT_POST_LIST_PATH,post])
        assert context._wechat_list_request_count==session._list_request_count==6
        try:
            page.evaluate('args=>read(...args)',[COMMENT_POST_LIST_PATH,post])
        except Exception:
            pass
        else:
            raise AssertionError('seventh native list request escaped budget')
        assert len([1 for url,_ in sent if url.endswith(COMMENT_POST_LIST_PATH)])==6
    finally:
        context.close();locks._SESSION.reset(token)

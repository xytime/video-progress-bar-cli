"""隔离 Chromium 验证旧作品分页跳转、共享预算与原生身份绑定。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| reply-cursor-v1 | 2026-10-25 | Codex | 覆盖普通账户真实 lastBuff 契约、跨上下文续扫及独立上下文目标重定位，预算仍为每上下文六次。 |
| reply-page-hint-v1 | 2026-10-25 | Codex | 原生分页合成响应经真实适配器和共享路由守卫；仅替换最终网络传输。 |
"""
import json
from types import SimpleNamespace

import pytest
from playwright.sync_api import Route

from config.settings import settings
from tests.browser_fixtures import chromium
from video_processing.core import wechat_session_lock as locks
from video_processing.interaction.secondary_reply_browser_adapter import (
    COMMENT_POST_LIST_PATH, SecondaryReplyBrowserAdapter,
)

ORIGIN = 'https://channels.weixin.qq.com'
URL = ORIGIN + '/platform/interaction/comment'
POST = 'export/page-120'


@pytest.mark.parametrize('hint_post, expected_first, bound', [(POST, 12, True), ('export/other', 1, False)])
def test_old_post_jump_preserves_request_budget_and_identity(chromium, monkeypatch, tmp_path, hint_post, expected_first, bound):
    monkeypatch.setattr(settings, 'wechat_interaction_list_request_budget', 6)
    session = SimpleNamespace(_request_started=True, _request_limited=False, _request_count=0,
        _list_request_count=0, purpose='回复', state_path=tmp_path/'wechat_state.json',
        request_guard=SimpleNamespace(observe_response=lambda response: False))
    token = locks._SESSION.set(session)
    context = chromium.new_context()
    sent = []

    def native_transport(route, **kwargs):
        data = route.request.post_data_json
        sent.append(data)
        first = (data['currentPage'] - 1) * 10
        route.fulfill(status=201, json={'data': {'list': [
            {'exportId': f'export/page-{i}', 'desc': f'作品完整文案 {i}'} for i in range(first, first + 10)]}})

    monkeypatch.setattr(Route, 'continue_', native_transport)
    try:
        locks.guard_wechat_context(context)
        page = context.new_page()
        page.route(URL, lambda route: route.fulfill(content_type='text/html', body='''
            <div id="feeds"></div><script>
            async function load(n) {
              try {
                const r = await fetch(''' + json.dumps(COMMENT_POST_LIST_PATH) + ''', {
                  method:'POST', headers:{'Content-Type':'application/json'},
                  body:JSON.stringify({pageSize:10,currentPage:n,onlyUnread:false,needAllCommentCount:true})});
                const data = await r.json();
                for (const item of data.data.list) {
                  const card = document.createElement('div'); card.className='comment-feed-wrap';
                  card.dataset.objectId=item.exportId; card.textContent=item.desc;
                  card.onclick=()=>document.querySelector('#feeds').dataset.currentObjectId=item.exportId;
                  document.querySelector('#feeds').append(card);
                }
                return true;
              } catch {return false;}
            }
            </script>'''))
        adapter = SecondaryReplyBrowserAdapter()
        adapter._setup_page_listeners(page)
        adapter.set_post_list_page_hint(hint_post, 12)
        adapter._setup_list_pagination(page, post_id=POST)
        page.goto(URL)
        assert [page.evaluate('n=>load(n)', n) for n in range(1, 8)] == [True] * 6 + [False]
        assert [data['currentPage'] for data in sent] == list(range(expected_first, expected_first + 6))
        assert all(data['pageSize'] == 10 and data['onlyUnread'] is False and data['needAllCommentCount'] is True for data in sent)
        assert context._wechat_list_request_count == session._list_request_count == 6
        if bound:
            assert adapter._select_and_bind_post_card(page, platform_post_id=POST, wait_ms=1)[0]
        else:
            # 错误提示不能把前 60 个作品中的任意一个冒充旧目标。
            assert adapter._resolve_scene_post_id(POST, None) is None
            assert page.locator(f'[data-object-id="{POST}"]').count() == 0
    finally:
        context.close()
        locks._SESSION.reset(token)


def test_native_cursor_continues_across_contexts_and_relocates_target(chromium, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'wechat_interaction_list_request_budget', 6)
    state = tmp_path/'wechat_state.json'
    target = 'export/public-target-75'
    description = lambda n: f'第 {n} 个已发布作品的完整文案用于唯一绑定原生评论场景，不能借助缓存跳过身份校验。'
    sent = []

    def native_transport(route, **kwargs):
        data = route.request.post_data_json
        assert 'currentPage' not in data
        first = int(data['lastBuff'].removeprefix('opaque-server-')) if data['lastBuff'] else 0
        sent.append(first)
        route.fulfill(status=201, json={'errCode': 0, 'data': {'lastBuff': f'opaque-server-{first+10}',
            'list': [{'objectId': f'native-{i}', 'desc': {'description': description(i)}} for i in range(first, first+10)]}})

    monkeypatch.setattr(Route, 'continue_', native_transport)
    for run in range(3):
        # 每次全新浏览器上下文，复用的仅是平台实际返回过的游标。
        session = SimpleNamespace(_request_started=True, _request_limited=False, _request_count=0,
            _list_request_count=0, _credential_generation='fixture-generation', purpose='回复', state_path=state,
            request_guard=SimpleNamespace(observe_response=lambda response: False))
        token = locks._SESSION.set(session)
        context = chromium.new_context()
        try:
            locks.guard_wechat_context(context)
            page = context.new_page()
            page.route(URL, lambda route: route.fulfill(content_type='text/html', body='''
                <div id="feeds"></div><script>let next=''; async function load() {
                  try {
                    const r=await fetch(''' + json.dumps(COMMENT_POST_LIST_PATH) + ''', {method:'POST',
                      headers:{'Content-Type':'application/json'},body:JSON.stringify({pageSize:10,
                      lastBuff:next,onlyUnread:false,needAllCommentCount:true,userpageType:13,forMcn:false})});
                    const d=(await r.json()).data; next=d.lastBuff;
                    for(const item of d.list){const card=document.createElement('div');
                      card.className='comment-feed-wrap';card.textContent=item.desc.description;
                      card.onclick=()=>document.querySelector('#feeds').dataset.currentObjectId=item.objectId;
                      document.querySelector('#feeds').append(card);} return true;
                  }catch{return false;}}
                </script>'''))
            adapter = SecondaryReplyBrowserAdapter(state_path=state)
            adapter._setup_page_listeners(page)
            adapter.set_post_list_page_hint(target, 7, published_description=description(75))
            adapter._setup_list_pagination(page, post_id=target)
            page.goto(URL)
            count = 7 if run < 2 else 1
            values = [page.evaluate('()=>load()') for _ in range(count)]
            page.wait_for_timeout(50)
            assert values == ([True]*6+[False] if run < 2 else [True])
            if run == 0:
                assert adapter._resolve_scene_post_id(target, description(75)) is None
            else:
                assert adapter._resolve_scene_post_id(target, description(75)) == 'native-75', (run, sent, adapter._post_descriptions)
                assert adapter._select_and_bind_post_card(page, platform_post_id=target,
                    published_description=description(75), wait_ms=1)[0]
                assert adapter._resolve_scene_post_id(target, description(200)) is None
            assert session._list_request_count == (6 if run < 2 else 1)
        finally:
            context.close()
            locks._SESSION.reset(token)
    assert sent == list(range(0, 120, 10)) + [70]

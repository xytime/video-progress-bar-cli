"""真实 Chromium 离线验证页面拦截器不能跳过账户停止闸门。"""
from tests.browser_fixtures import chromium
from config.settings import settings
from video_processing.core.wechat_session_lock import WeChatSessionLock, guard_wechat_context
from video_processing.core.wechat_browser_context import create_wechat_context


def test_page_reply_route_falls_through_to_account_stop(chromium, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'wechat_account_scheduler_enabled', False)
    sent = []
    with WeChatSessionLock(tmp_path / 'state.json', purpose='回复') as session:
        context = create_wechat_context(chromium)
        # 底层离线传输桩；重新安装守卫保证其位于桩之前。
        context.route('**/*', lambda route: (sent.append(route.request.url), route.fulfill(status=200, body='{}')))
        guard_wechat_context(context)
        page = context.new_page()
        page.route('**/comment/create_comment*', lambda route: route.fallback())
        session._request_limited = True
        result = page.evaluate("""async () => {
            try { await fetch('https://channels.weixin.qq.com/micro/cgi-bin/mmfinderassistant-bin/comment/create_comment', {method:'POST'}); return 'sent'; }
            catch(e) { return 'blocked'; }
        }""")
        assert result == 'blocked'
        assert sent == []
        context.close()

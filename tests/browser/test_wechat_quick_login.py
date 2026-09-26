"""隔离 Chromium 中验证迟到授权与可信 frame 边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-26 | Codex | 实际跨域 iframe 第 11 秒授权、完整导航及错误来源零点击。 |
"""
from tests.browser_fixtures import chromium
from scripts.wechat_uploader import _try_wechat_quick_login


def _page(chromium, *, host='open.weixin.qq.com', delay=11000):
    page = chromium.new_page()
    frame_html = '''<button onclick="setTimeout(() => document.querySelector('#auth').hidden=false, DELAY)">微信快捷登录</button>
    <section id="auth" hidden><p>视频号创作平台\n 申请使用你的昵称、头像</p>
    <button onclick="fetch('/clicked'); parent.postMessage('approved','https://channels.weixin.qq.com')">允许</button></section>'''.replace('DELAY', str(delay))
    clicks = []
    def route(r):
        if '/clicked' in r.request.url:
            clicks.append(r.request.url)
            r.fulfill(body='ok')
        elif '/connect/login' in r.request.url:
            r.fulfill(content_type='text/html; charset=utf-8', body=frame_html)
        elif '/post/create' in r.request.url:
            r.fulfill(content_type='text/html; charset=utf-8', body='<h1>发布页</h1>')
        else:
            r.fulfill(content_type='text/html; charset=utf-8', body=f'''<iframe src="https://{host}/connect/login"></iframe>
            <script>addEventListener('message', e => {{if(e.data==='approved') location.href='/platform/post/create'}})</script>''')
    page.route('**/*', route)
    page.goto('https://channels.weixin.qq.com/platform/login')
    page.frame_locator('iframe').get_by_role('button', name='微信快捷登录', exact=True).wait_for()
    return page, clicks


def test_real_iframe_authorization_after_old_ten_second_cutoff(chromium, tmp_path):
    page, clicks = _page(chromium)
    try:
        assert _try_wechat_quick_login(page, timeout_ms=15000)
        assert len(clicks) == 1
        assert page.get_by_role('heading', name='发布页').is_visible()
        page.screenshot(path=str(tmp_path/'late-authorization-success.png'))
    finally:
        page.close()


def test_untrusted_iframe_cannot_trigger_authorization(chromium):
    page, clicks = _page(chromium, host='wrong-origin.invalid', delay=0)
    try:
        assert not _try_wechat_quick_login(page, timeout_ms=1000)
        assert clicks == []
        assert page.url.endswith('/platform/login')
    finally:
        page.close()

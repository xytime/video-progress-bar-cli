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
            r.fulfill(
                content_type='text/html; charset=utf-8',
                body='<h1>发布页</h1><div class="upload-area"><input type="file" accept="video/mp4,video/*" /><button class="upload-btn">上传视频</button></div>',
            )
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


def test_wait_and_save_login_browser_none_rejected(tmp_path):
    """当 context.browser is None 时，_wait_and_save_login 必须 fail-closed 抛错拒绝，绝不跳过独立复用。"""
    from unittest.mock import MagicMock
    import pytest
    from scripts.wechat_uploader import _wait_and_save_login

    mock_page = MagicMock()
    mock_context = MagicMock()
    mock_context.browser = None
    state_file = tmp_path / "wechat_state.json"

    with pytest.raises(RuntimeError, match="browser instance unavailable"):
        _wait_and_save_login(mock_page, mock_context, state_file)


def test_wait_and_save_login_reuse_verification_failure_cleans_up(chromium, tmp_path):
    """独立全新上下文复用验证失败时，必须清理临时文件、拒绝提交会话，并记录 FAILED 状态（真实本地 route，不 mock 页面判据）。"""
    import json
    import pytest
    from unittest.mock import patch
    from scripts.wechat_uploader import _wait_and_save_login
    from video_processing.core.wechat_auth_state import read_wechat_auth_state

    state_file = tmp_path / "wechat_state.json"
    state_file.write_text(json.dumps({"cookies": [{"name": "old", "value": "val"}]}))

    context = chromium.new_context(viewport={"width": 1280, "height": 800})
    def main_route(r):
        if "/post/create" in r.request.url:
            r.fulfill(
                content_type="text/html; charset=utf-8",
                body='<html><body><h1>发布页</h1><input type="file" accept="video/mp4" /><button class="upload-btn">上传视频</button></body></html>',
            )
        else:
            r.fulfill(status=404, body="Not Found")

    context.route("**/*", main_route)
    page = context.new_page()
    page.goto("https://channels.weixin.qq.com/platform/post/create")

    # 包装 chromium.new_context：为全新上下文挂载本地 route，真实返回未就绪 HTML（绝不触碰外网，不 mock 页面判据）
    orig_new_context = chromium.new_context
    def reuse_new_context(*args, **kwargs):
        ctx = orig_new_context(*args, **kwargs)
        def reuse_route(r):
            if "/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='<!DOCTYPE html><html><body><h1>未就绪页面</h1><p>无正向发布控件</p></body></html>',
                )
            else:
                r.fulfill(status=404, body="Not Found")
        ctx.route("**/*", reuse_route)
        return ctx

    with patch.object(chromium, "new_context", side_effect=reuse_new_context):
        with pytest.raises(RuntimeError, match="Independent fresh context session reuse verification failed"):
            _wait_and_save_login(page, context, state_file, method="desktop_quick")

    # 1. 临时验证文件已被清理
    tmp_files = list(tmp_path.glob(".*verify*"))
    assert tmp_files == []

    # 2. 原 state_file 未被覆盖
    assert json.loads(state_file.read_text()) == {"cookies": [{"name": "old", "value": "val"}]}

    # 3. 记录了本次授权尝试失败（由真实 SPA guard 输出的 PAGE_UNREADY 转换而来）
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state.get("last_auth_attempt_status") == "FAILED"
    assert auth_state.get("last_auth_attempt_reason") == "PAGE_UNREADY"
    assert auth_state.get("last_auth_attempt_method") == "desktop_quick"


def test_wait_and_save_login_storage_failure_records_attempt_and_re_raises(chromium, tmp_path):
    """当 storage_state 写入异常或保存为空时，记录 STORAGE_FAILED 并清理临时文件。"""
    import json
    import pytest
    from unittest.mock import MagicMock, patch
    from scripts.wechat_uploader import _wait_and_save_login
    from video_processing.core.wechat_auth_state import read_wechat_auth_state

    state_file = tmp_path / "wechat_state.json"
    state_file.write_text(json.dumps({"cookies": [{"name": "keep_old", "value": "val"}]}))

    page = chromium.new_page()
    context = page.context

    # 模拟 storage_state 写入失败
    mock_context = MagicMock()
    mock_context.browser = chromium
    mock_context.storage_state.side_effect = OSError("Disk full simulation")

    mock_page = MagicMock()
    mock_page.wait_for_url.return_value = None

    with patch("video_processing.core.wechat_page_contract.wait_for_publish_ready_with_spa_guard", return_value=(True, None)):
        with pytest.raises(OSError, match="Disk full simulation"):
            _wait_and_save_login(mock_page, mock_context, state_file, method="desktop_quick")

    # 临时文件已被清理
    tmp_files = list(tmp_path.glob(".*verify*"))
    assert tmp_files == []

    # 原 state_file 未被覆盖
    assert json.loads(state_file.read_text()) == {"cookies": [{"name": "keep_old", "value": "val"}]}

    # 记录了 STORAGE_FAILED
    auth_state = read_wechat_auth_state(state_file)
    assert auth_state.get("last_auth_attempt_status") == "FAILED"
    assert auth_state.get("last_auth_attempt_reason") == "STORAGE_FAILED"


def test_try_wechat_quick_login_custom_state_file_passed_to_attempt(chromium, tmp_path):
    """_try_wechat_quick_login 超时时，将失败尝试记录在调用方传入的 state_file，绝不触碰生产 state。"""
    import json
    from scripts.wechat_uploader import _try_wechat_quick_login
    from video_processing.core.wechat_auth_state import read_wechat_auth_state
    from config.settings import settings

    custom_state = tmp_path / "custom_wechat_state.json"
    custom_state.write_text(json.dumps({"cookies": []}))

    # 准备生产目录的 marker 和 flag 路径作为对照
    prod_output = settings.project_root / "output"
    prod_marker = prod_output / "wechat_login_at.txt"
    prod_marker_content_before = prod_marker.read_text() if prod_marker.is_file() else None

    page = chromium.new_page()
    try:
        # 页面包含微信快捷登录按钮，点击后进入轮询循环，但直到超时未完成授权
        frame_html = """<!DOCTYPE html><html><body><button>微信快捷登录</button></body></html>"""
        def route(r):
            if "/connect/login" in r.request.url:
                r.fulfill(content_type="text/html; charset=utf-8", body=frame_html)
            else:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body="""<!DOCTYPE html><html><body>
                    <iframe src="https://open.weixin.qq.com/connect/login"></iframe>
                    </body></html>""",
                )

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/login")
        page.frame_locator("iframe").get_by_role("button", name="微信快捷登录", exact=True).wait_for()

        # 执行 _try_wechat_quick_login，设置短超时 500ms
        res = _try_wechat_quick_login(page, timeout_ms=500, state_file=custom_state)
        assert res is False

        # 验证 1：custom_state 记录了本次超时失败尝试
        auth_state = read_wechat_auth_state(custom_state)
        assert auth_state.get("last_auth_attempt_status") == "FAILED"
        assert auth_state.get("last_auth_attempt_reason") == "PAGE_UNREADY"
        assert auth_state.get("last_auth_attempt_method") == "desktop_quick"

        # 验证 2：生产目标隔离，未生成/修改生产 marker
        if prod_marker_content_before is not None:
            assert prod_marker.read_text() == prod_marker_content_before
        else:
            assert not prod_marker.exists()
    finally:
        page.close()

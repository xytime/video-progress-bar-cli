"""真实 Chromium 隔离浏览器环境下正向视频发布控件与安全边界回归测试。

# Modification History
| Version | Date       | Author      | Description                                                                  |
|---------|------------|-------------|------------------------------------------------------------------------------|
| 1.1.0   | 2026-09-28 | Antigravity | 新增 upload-area 否定文案（不可选择视频/选择视频失败）、重复可见控件浏览器负例 |
| 1.0.0   | 2026-09-28 | Antigravity | 真实 Chromium 验证官方子 iframe 视频 input、上传容器选择视频与全套负例边界     |
"""

from tests.browser_fixtures import chromium
from video_processing.core.wechat_page_contract import (
    check_strong_video_publish_controls,
    wait_for_publish_ready_with_spa_guard,
)


def test_browser_positive_official_channels_iframe_with_video_input(chromium):
    """真实浏览器正例 1：官方 CREATE 路由下，官方同源子 iframe 内部包含视频文件输入。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/inner_uploader" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='<html><body><input type="file" accept="video/mp4,video/*" /></body></html>',
                )
            elif "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>视频发布创建页</h1>
                    <iframe src="https://channels.weixin.qq.com/platform/inner_uploader"></iframe>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is True
        assert err is None

        spa_ready, spa_err = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=1.0)
        assert spa_ready is True
        assert spa_err is None
    finally:
        page.close()


def test_browser_positive_upload_container_choose_video(chromium):
    """真实浏览器正例 2：官方 CREATE 路由下，可见上传容器内包含明确精准的'选择视频'控件。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>视频发布创建页</h1>
                    <div class="upload-area">
                        <button class="upload-btn">选择视频</button>
                    </div>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is True
        assert err is None

        spa_ready, spa_err = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=1.0)
        assert spa_ready is True
        assert spa_err is None
    finally:
        page.close()


def test_browser_positive_legacy_upload_video_button(chromium):
    """真实浏览器正例 3：官方 CREATE 路由下，旧版精确'上传视频'按钮兼容识别。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>视频发布创建页</h1>
                    <div class="main-content">
                        <button class="primary-btn">上传视频</button>
                    </div>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is True
        assert err is None
    finally:
        page.close()


def test_browser_negative_upload_area_with_negative_text_rejected(chromium):
    """真实浏览器负例 1：上传容器内存在包含'不可选择视频'、'选择视频失败'等否定文案时，绝不误报就绪。"""
    page = chromium.new_page()
    try:
        negative_snippets = [
            '<div class="upload-area"><button class="upload-btn">不可选择视频</button></div>',
            '<div class="upload-area"><button class="upload-btn">选择视频失败</button></div>',
            '<div class="upload-area"><button class="upload-btn">不可上传视频</button></div>',
            '<div class="upload-area"><button class="upload-btn">上传视频失败</button></div>',
        ]
        for snippet in negative_snippets:
            def make_route(body_content):
                def route(r):
                    if "/platform/post/create" in r.request.url:
                        r.fulfill(
                            content_type="text/html; charset=utf-8",
                            body=f'<html><body><h1>创建页</h1>{body_content}</body></html>',
                        )
                    else:
                        r.fulfill(status=404, body="Not Found")
                return route

            page.unroute("**/*")
            page.route("**/*", make_route(snippet))
            page.goto("https://channels.weixin.qq.com/platform/post/create")
            page.wait_for_load_state("networkidle")

            ready, err = check_strong_video_publish_controls(page)
            assert ready is False, f"Negative snippet should have failed: {snippet}"
            assert err == "PAGE_UNREADY"
    finally:
        page.close()


def test_browser_negative_duplicate_visible_choose_video_buttons_rejected(chromium):
    """真实浏览器负例 2：上传容器内存在多个重复可见的'选择视频'控件时，视为冲突状态拒绝。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>视频发布创建页</h1>
                    <div class="upload-area">
                        <button class="upload-btn">选择视频</button>
                        <button class="upload-btn">选择视频</button>
                    </div>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is False
        assert err == "PAGE_UNREADY"
    finally:
        page.close()


def test_browser_negative_duplicate_visible_legacy_upload_video_buttons_rejected(chromium):
    """真实浏览器负例 3：页面存在多个重复可见的旧版'上传视频'按钮时，拒绝。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>视频发布创建页</h1>
                    <div class="main-content">
                        <button>上传视频</button>
                        <button>上传视频</button>
                    </div>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is False
        assert err == "PAGE_UNREADY"
    finally:
        page.close()


def test_browser_negative_isolated_bare_choose_video_button_rejected(chromium):
    """真实浏览器负例 4：脱离上传容器的孤立裸按钮 绝不单独采信。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>视频发布创建页</h1>
                    <div class="nav-bar">
                        <button>选择视频</button>
                    </div>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is False
        assert err == "PAGE_UNREADY"
    finally:
        page.close()


def test_browser_negative_hidden_upload_container_rejected(chromium):
    """真实浏览器负例 5：上传容器处于 display:none 隐藏状态时 绝不误报就绪。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>视频发布创建页</h1>
                    <div class="upload-area" style="display:none;">
                        <button class="upload-btn">选择视频</button>
                    </div>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is False
        assert err == "PAGE_UNREADY"
    finally:
        page.close()


def test_browser_negative_image_only_input_rejected(chromium):
    """真实浏览器负例 6：仅含纯图片 input[type='file'] 绝不能当作视频发布控件。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>个人资料页</h1>
                    <input type="file" accept="image/jpeg,image/png" />
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is False
        assert err == "PAGE_UNREADY"
    finally:
        page.close()


def test_browser_negative_untrusted_third_party_iframe_rejected(chromium):
    """真实浏览器负例 7：第三方非官方域名的 iframe 内部 input 必须严格阻断。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/external_upload" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='<html><body><input type="file" accept="video/mp4" /></body></html>',
                )
            elif "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <h1>测试第三方入侵</h1>
                    <iframe src="https://evil.example.com/external_upload"></iframe>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        ready, err = check_strong_video_publish_controls(page)
        assert ready is False
        assert err == "PAGE_UNREADY"
    finally:
        page.close()


def test_browser_negative_login_box_overlay_blocks_controls(chromium):
    """真实浏览器负例 8：即便存在上传容器，但若处于未登录遮罩状态（可见 .login-box），必须阻断。"""
    page = chromium.new_page()
    try:
        def route(r):
            if "/platform/post/create" in r.request.url:
                r.fulfill(
                    content_type="text/html; charset=utf-8",
                    body='''<html><body>
                    <div class="login-box">使用微信扫码登录</div>
                    <div class="upload-area"><button class="upload-btn">选择视频</button></div>
                    </body></html>''',
                )
            else:
                r.fulfill(status=404, body="Not Found")

        page.route("**/*", route)
        page.goto("https://channels.weixin.qq.com/platform/post/create")
        page.wait_for_load_state("networkidle")

        spa_ready, spa_err = wait_for_publish_ready_with_spa_guard(page, timeout_seconds=0.5)
        assert spa_ready is False
        assert spa_err == "LOGIN_REQUIRED"
    finally:
        page.close()

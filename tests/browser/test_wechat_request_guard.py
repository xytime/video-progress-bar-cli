"""真实 Chromium 首次管理页 -360 识别，页面就绪检查前即共享退避。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-10-30 | Codex | 等待真实宿主响应监听完成读取，浏览器 fetch 完成不等于 Python 回调已完成；不改变生产限流逻辑。 |
| 1.0.0 | 2026-10-20 | Codex | 隔离网络路由返回 HTTP 201/外层成功/内层 -360，验证首屏响应事件与零重试。 |
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from tests.browser_fixtures import chromium
from video_processing.core.wechat_browser_context import create_wechat_context
from video_processing.core.wechat_request_guard import WeChatRequestGuard
from video_processing.core.wechat_session_lock import WeChatSessionLock, WeChatSessionLockBusy


@pytest.mark.parametrize("manual", [False, True])
def test_initial_page_business_limit_is_seen_without_ready_controls(chromium, tmp_path, monkeypatch, manual):
    from config.settings import settings
    monkeypatch.setattr(settings, "wechat_account_scheduler_enabled", manual)
    monkeypatch.setattr(type(settings), "default_output_dir", property(lambda _: tmp_path))
    state = tmp_path / "state.json"
    api = "https://channels.weixin.qq.com/micro/interaction/cgi-bin/mmfinderassistant-bin/post/post_list"
    calls = []
    token = ""
    if manual:
        guard = WeChatRequestGuard(state)
        guard.record_limited(endpoint="/prior-limit")
        token = guard.issue_manual_login()
    with WeChatSessionLock(state, purpose="登录" if manual else "发布", manual_login_token=token):
        context = create_wechat_context(chromium)

        def respond(route):
            calls.append(route.request.url)
            if route.request.url == api:
                route.fulfill(status=201, content_type="application/json", body=json.dumps({
                    "errCode": 0, "data": {"baseResp": {"errcode": -360, "errmsg": "操作过于频繁"}, "list": []},
                }))
            else:
                route.fulfill(status=200, content_type="text/html", body=f"<body>loading<script>fetch('{api}').then(r=>r.json()).then(()=>window.done=true)</script></body>")

        context.route("**/*", respond)
        page = context.new_page()
        page.goto("https://channels.weixin.qq.com/platform/post/list")
        page.wait_for_function("window.done === true")
        # response.json() 会向驱动读取正文并让出控制；JS fetch 完成可能先于宿主
        # 监听返回。泵送已有事件直至真实护栏完成，不增加平台请求或放宽业务断言。
        deadline = time.monotonic() + 5
        while not context._wechat_rate_limit_seen and time.monotonic() < deadline:
            page.wait_for_timeout(10)
        assert context._wechat_rate_limit_seen is True
        assert page.locator("body").inner_text() == "loading"
        page.screenshot(path=str(tmp_path / "initial-business-limit.png"))
        context.close()
    assert calls == ["https://channels.weixin.qq.com/platform/post/list", api]
    with pytest.raises(WeChatSessionLockBusy):
        WeChatSessionLock(state, purpose="保活").acquire()
    assert WeChatRequestGuard(state).snapshot()["business_code"] == -360


def test_real_uploader_stops_on_initial_business_limit_before_ready_check(tmp_path, monkeypatch):
    from scripts import wechat_uploader as uploader
    monkeypatch.setattr(uploader.settings, "wechat_account_scheduler_enabled", False)
    original_factory = uploader.create_wechat_context
    calls = []

    def local_context(browser, **kwargs):
        context = original_factory(browser, **kwargs)

        def respond(route):
            calls.append(route.request.url)
            if "/cgi-bin/" in route.request.url:
                route.fulfill(status=201, content_type="application/json", body=json.dumps({
                    "errCode": 0, "data": {"baseResp": {"errcode": -360}, "list": []},
                }))
            else:
                api = "/micro/interaction/cgi-bin/mmfinderassistant-bin/post/post_list"
                route.fulfill(status=200, content_type="text/html", body=f"<body>loading<script>fetch('{api}')</script></body>")

        context.route("**/*", respond)
        return context

    monkeypatch.setattr(uploader, "create_wechat_context", local_context)
    evidence = tmp_path / "evidence"
    # 模块级 Chromium 夹具的同步事件循环仍存活；投稿器在独立线程拥有自己的运行时。
    with ThreadPoolExecutor(max_workers=1) as worker:
        code = worker.submit(uploader.run_uploader, state_path=str(tmp_path / "state.json"), verify_only=True,
                             platform_post_id="known-protected-id", evidence_dir=str(evidence)).result()
    assert code == 1
    receipt = json.loads((evidence / "management_rate_limit.json").read_text())
    assert receipt["business_code"] == -360 and receipt["phase"] == "INITIAL_READBACK"
    assert len(calls) == 2
    assert not (evidence / "submission_receipt.json").exists()

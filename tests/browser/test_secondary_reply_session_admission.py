"""真实会话入口回归：具名只读扫描、写请求拦截、同条回复共享账户准入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 使用隔离 Chromium 和真实锁/账户调度验证恢复边界。 |
"""
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from config.settings import settings
from tests.browser_fixtures import chromium  # noqa: F401
from tests.browser.test_secondary_reply_orchestrated_browser import stack, _task, POST, AUTHOR  # noqa: F401
from tests.browser.test_secondary_reply_browser import secondary_reply_harness  # noqa: F401
from video_processing.core.wechat_request_guard import WeChatRequestGuard
from video_processing.core.wechat_session_lock import WeChatSessionLockBusy, current_wechat_session
from video_processing.interaction import secondary_reply_browser_adapter as module
from video_processing.interaction.secondary_reply_browser_platform import BrowserSecondaryReplyPlatform

URL = "http://wechat-fixture.invalid/platform/interaction/comment"
HTML = Path(__file__).parents[1] / "fixtures/wechat_secondary_reply.html"
SUBMIT = "/cgi-bin/mmfinderassistant-bin/comment/create_comment"


@pytest.fixture
def live_entry(chromium, monkeypatch, tmp_path):
    monkeypatch.setattr(type(settings), "default_output_dir", property(lambda self: tmp_path))
    if hasattr(settings, "wechat_scheduler_policy_path"):
        monkeypatch.setattr(settings, "wechat_scheduler_policy_path", tmp_path / "missing-policy.json")
    monkeypatch.setattr(settings, "wechat_account_scheduler_enabled", True)
    monkeypatch.setattr(settings, "wechat_scheduler_priority_video", "")
    state = tmp_path / "wechat_state.json"
    state.write_text('{"cookies": [], "origins": []}')
    contexts, writes, replies = [], [], []

    def route_handler(route):
        req = route.request
        if req.is_navigation_request():
            injected = '<script>window.__serverReplies = ' + json.dumps(replies) + ';</script>'
            route.fulfill(content_type="text/html", body=injected + HTML.read_text())
        elif req.url.endswith(SUBMIT):
            data = req.post_data_json
            writes.append(data)
            replies.append({"commentId": "synth_new_reply_999", "content": data["content"], "authorId": AUTHOR})
            route.fulfill(json={"errCode": 0, "data": {"commentId": "synth_new_reply_999", "clientId": data.get("clientId"),
                "comment": {"commentId": "synth_new_reply_999", "commentContent": data["content"],
                            "replyCommentId": data.get("replyCommentId"), "username": AUTHOR}}})
        else:
            route.fulfill(json={})

    class Browser:
        def new_context(self, **kwargs):
            ctx = chromium.new_context(**kwargs)
            contexts.append(ctx)
            ctx.on("page", lambda page: page.route("**/*", route_handler))
            return ctx

        def close(self):
            pass  # Chromium 生命周期由隔离夹具管理。

    @contextmanager
    def runtime():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: Browser()))

    monkeypatch.setattr(module, "sync_playwright", runtime)
    adapter = module.SecondaryReplyBrowserAdapter(state_path=state, comment_url=URL)
    platform = BrowserSecondaryReplyPlatform(adapter, account_finder_id=AUTHOR,
        trusted_origins=("http://wechat-fixture.invalid",), evidence_dir=tmp_path / "evidence")
    return SimpleNamespace(adapter=adapter, platform=platform, contexts=contexts, writes=writes,
                           state=state, guard=WeChatRequestGuard(state))


def test_bound_readonly_entry_blocks_writes_and_accounts_scan(live_entry):
    s = live_entry
    with s.adapter.open_session(readonly_post_id=POST) as page:
        assert current_wechat_session().video == POST
        assert page.locator('[data-object-id]').count() == 2
        assert page.evaluate("async p => {try {await fetch(p, {method:'POST', body:'{}'}); return 'sent';} catch {return 'blocked';}}", SUBMIT) == "blocked"
    assert s.writes == []
    assert len(s.guard.snapshot()["schedule"]["sessions"]) == 1
    with pytest.raises(WeChatSessionLockBusy):
        with s.adapter.open_session(readonly_post_id=POST):
            pytest.fail("账户冷却不得被只读模式绕过")
    assert len(s.contexts) == 1


def test_unbound_scan_stays_closed(live_entry):
    with pytest.raises(WeChatSessionLockBusy, match="缺少具体作品"):
        with live_entry.adapter.open_session():
            pytest.fail("未绑定作品不得打开后台")
    assert live_entry.contexts == []


@pytest.mark.parametrize("operation", ["discovery", "calibration"])
def test_readonly_operations_pass_post_identity_to_actual_session(live_entry, monkeypatch, operation):
    seen = []
    def discover(page, **kwargs):
        seen.append(current_wechat_session().video)
        return {"ok": True, "payload": {"comments": []}}
    if operation == "discovery":
        monkeypatch.setattr(live_entry.adapter, "discover_comments_on_page", discover)
        result = live_entry.platform.discover_comments(post_id=POST)
    else:
        monkeypatch.setattr(live_entry.adapter, "calibrate_page_controls", discover)
        result = live_entry.adapter.verify_and_calibrate_controls(
            platform_post_id=POST, root_comment_id="synth_cmt_101", evidence_dir=live_entry.state.parent / "evidence",
        )
    assert result["ok"]
    assert seen == [POST]
    assert len(live_entry.contexts) == 1
    assert live_entry.writes == []


def test_reply_full_workflow_uses_one_admission_and_fresh_contexts(stack, live_entry):
    stack.orch.platform = live_entry.platform
    tid = _task(stack)
    outcome = stack.orch.submit(tid)
    assert outcome.status == "VERIFIED", outcome
    assert len(live_entry.writes) == 1
    assert len(live_entry.contexts) == 3
    assert len(live_entry.guard.snapshot()["schedule"]["sessions"]) == 1
    assert stack.orch.submit(tid).status == "NOT_CLAIMABLE"
    assert len(live_entry.writes) == 1
    # 下一条回复仍受共用间隔限制，不把额度按平台阶段重置。
    tid2 = _task(stack, "synth_cmt_105")
    result = stack.orch.submit(tid2)
    assert result.status == "DEFERRED_SESSION_BUSY", result
    assert stack.db.get_secondary_reply_task(tid2)["status"] == "APPROVED"
    assert len(live_entry.contexts) == 3


def test_workflow_rejects_other_post_and_cleans_scope(live_entry):
    with live_entry.adapter.reply_workflow(POST):
        with pytest.raises(WeChatSessionLockBusy, match="身份不匹配"):
            with live_entry.adapter.open_session(readonly_post_id="export/other"):
                pytest.fail("另一作品不得借用当前许可")
    assert current_wechat_session() is None
    assert live_entry.adapter._workflow_session is None
    assert live_entry.contexts == []


def test_manual_reply_retry_is_single_use_and_bound_to_post(live_entry):
    s = live_entry
    with s.adapter.open_session(readonly_post_id=POST):
        pass
    s.adapter._manual_retry_post_id = POST
    with pytest.raises(WeChatSessionLockBusy, match='作品不匹配'):
        with s.adapter.open_session(readonly_post_id='another-post'):
            pytest.fail('不得跨作品使用许可')
    with s.adapter.open_session(readonly_post_id=POST):
        pass
    assert len(s.contexts) == 2
    with pytest.raises(WeChatSessionLockBusy):
        with s.adapter.open_session(readonly_post_id=POST):
            pytest.fail('单次补发不得永久跳过账户间隔')
    assert len(s.contexts) == 2
    assert not s.guard.snapshot().get('manual_overrides')


def test_manual_reply_retry_never_overrides_native_rate_limit(live_entry):
    s = live_entry
    s.guard.record_limited(endpoint='/test', code=-360)
    s.adapter._manual_retry_post_id = POST
    with pytest.raises(WeChatSessionLockBusy, match='平台限流仍有效'):
        with s.adapter.open_session(readonly_post_id=POST):
            pytest.fail('平台限流必须停止')
    assert s.contexts == []

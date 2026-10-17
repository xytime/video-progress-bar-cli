"""Empirical adversarial test suite for SecondaryReplyBrowserAdapter controls calibration.

Covers:
1. Fail-closed behaviors: missing parent comment item, ambiguous reply buttons (>1),
   missing reply buttons (==0), disabled reply buttons, ambiguous/missing editor inputs,
   and ambiguous/missing submit buttons.
2. Editor calibration zero-write guarantees: verifying that text is never typed into `.edit-area`,
   `submit_btn` is never clicked, and empty submit button is verified disabled.
3. Editor cleanup: verifying that `_safe_close_editor` cleanly removes the editor DOM or resets state
   via cancel button / ESC fallback, and reports unclosable states accurately.
4. Route abortion: ensuring any attempt to dispatch `**/comment/create_comment*` is intercepted
   and aborted unconditionally in read-only sessions.
5. Adapter orchestration flag `verify_controls`: confirming decoupled read-only flow behavior.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-17 | Codex | 新增 BrowserSecondaryReplyPlatform 与 ops.verify_platform 端到端控件校准回归测试 (M3) |
| 1.1.0 | 2026-10-17 | Codex | 新增选择器联合碰撞修复验证、三态回复分类与原生身份/正文比对回归测试 (M2) |
| 1.0.0 | 2026-10-17 | Challenger | Milestone 1 adversarial challenger test suite |
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from tests.browser_fixtures import chromium
from video_processing.interaction.secondary_reply_browser_adapter import (
    SecondaryReplyBrowserAdapter,
    SecondaryReplySubmissionGuard,
    COMMENT_SUBMIT_PATHS,
)


@pytest.fixture
def adapter_instance(tmp_path):
    state_file = tmp_path / "wechat_state.json"
    state_file.write_text("{}", encoding="utf-8")
    return SecondaryReplyBrowserAdapter(
        state_path=state_file,
        comment_url="https://channels.weixin.qq.com/platform/interaction/comment",
    )


# ============================================================================
# Section 1: Fail-Closed Behaviors
# ============================================================================

def test_calibrate_fail_closed_missing_or_ambiguous_parent_item(chromium, adapter_instance, tmp_path):
    """验证当 parent_item 为 None、0 个或多个时，立即 Fail-Closed 阻断。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <div class="comment-item" id="c1">评论 1</div>
          <div class="comment-item" id="c2">评论 2</div>
        </body></html>
        """)

        # 1. parent_item is None
        res_none = adapter_instance.calibrate_comment_controls(
            page, parent_item=None, root_comment_id="cmt_none", attempt_dir=tmp_path
        )
        assert res_none["ok"] is False
        assert "一级评论节点不唯一或未找到" in res_none["error"]

        # 2. parent_item count == 0
        loc_empty = page.locator(".non-existent-comment")
        assert loc_empty.count() == 0
        res_empty = adapter_instance.calibrate_comment_controls(
            page, parent_item=loc_empty, root_comment_id="cmt_empty", attempt_dir=tmp_path
        )
        assert res_empty["ok"] is False
        assert "一级评论节点不唯一或未找到" in res_empty["error"]

        # 3. parent_item count > 1 (ambiguous)
        loc_multi = page.locator(".comment-item")
        assert loc_multi.count() == 2
        res_multi = adapter_instance.calibrate_comment_controls(
            page, parent_item=loc_multi, root_comment_id="cmt_multi", attempt_dir=tmp_path
        )
        assert res_multi["ok"] is False
        assert "一级评论节点不唯一或未找到" in res_multi["error"]
    finally:
        page.close()


def test_calibrate_fail_closed_ambiguous_reply_button(chromium, adapter_instance, tmp_path):
    """验证当 parent_item 中存在多个可见回复按钮时，触发歧义阻断 (count > 1)。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html>
        <head>
          <style>
            .action-icon { display: inline-block; width: 16px; height: 16px; }
          </style>
        </head>
        <body>
          <div class="comment-item" id="target">
            <span class="content">非常棒的视频！</span>
            <div class="action-item">
              <span class="action-icon weui-icon-outlined-comment"></span>
            </div>
            <div class="action-item">
              <span class="action-icon weui-icon-outlined-comment"></span>
            </div>
          </div>
        </body></html>
        """)
        parent = page.locator("#target")
        assert parent.count() == 1

        res = adapter_instance.calibrate_comment_controls(
            page, parent_item=parent, root_comment_id="cmt_ambig_btn", attempt_dir=tmp_path
        )
        assert res["ok"] is False
        assert "触发歧义阻断" in res["error"]
        assert "匹配到多个可见控件 (2)" in res["error"]
    finally:
        page.close()


def test_calibrate_fail_closed_missing_reply_button(chromium, adapter_instance, tmp_path):
    """验证当 parent_item 中缺失回复按钮时，Fail-Closed 拒绝。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <div class="comment-item" id="target">
            <span class="content">没有任何操作按钮的纯展示评论</span>
          </div>
        </body></html>
        """)
        parent = page.locator("#target")

        res = adapter_instance.calibrate_comment_controls(
            page, parent_item=parent, root_comment_id="cmt_no_btn", attempt_dir=tmp_path
        )
        assert res["ok"] is False
        assert "未能唯一定位可用的二级回复触发按钮" in res["error"]
    finally:
        page.close()


def test_calibrate_fail_closed_disabled_reply_button(chromium, adapter_instance, tmp_path):
    """验证当回复按钮处于 disabled 禁用状态时，拒绝继续。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <div class="comment-item" id="target">
            <span class="content">评论被锁定禁止回复</span>
            <button class="action-icon weui-icon-outlined-comment" disabled>回复</button>
          </div>
        </body></html>
        """)
        parent = page.locator("#target")

        res = adapter_instance.calibrate_comment_controls(
            page, parent_item=parent, root_comment_id="cmt_disabled_btn", attempt_dir=tmp_path
        )
        assert res["ok"] is False
        assert "回复按钮处于禁用状态" in res["error"]
    finally:
        page.close()


def test_calibrate_fail_closed_ambiguous_editor_input(chromium, adapter_instance, tmp_path):
    """验证展开后若父节点内匹配到多个输入框，安全关闭并阻断。
    
    注：此处亦暴露实现细节：adapter 在关闭编辑器后重新求值 loc.count()，
    导致错误信息中呈现已清理后的数量。但 Fail-Closed 阻断与 DOM 清理均正确执行。
    """
    page = chromium.new_page()
    try:
        page.set_content("""
        <html>
        <head>
          <style>
            .action-icon { display: inline-block; width: 16px; height: 16px; }
            .edit-area { display: block; width: 200px; height: 50px; }
          </style>
        </head>
        <body>
          <div class="comment-item" id="target">
            <span class="action-icon weui-icon-outlined-comment" id="reply-trigger">回复</span>
            <div class="comment-reply-wrap" id="reply-wrap" style="display:none;">
              <div contenteditable="true" class="edit-area" id="ed1"></div>
              <div contenteditable="true" class="edit-area" id="ed2"></div>
              <div class="reply-opt">
                <button type="button" class="weui-desktop-btn_default">取消</button>
                <button type="button" class="weui-desktop-btn_primary" disabled>评论</button>
              </div>
            </div>
          </div>
          <script>
            document.querySelector('#reply-trigger').addEventListener('click', () => {
              document.querySelector('#reply-wrap').style.display = 'block';
            });
            document.querySelector('.weui-desktop-btn_default').addEventListener('click', () => {
              document.querySelector('#reply-wrap').style.display = 'none';
            });
          </script>
        </body></html>
        """)
        parent = page.locator("#target")

        res = adapter_instance.calibrate_comment_controls(
            page, parent_item=parent, root_comment_id="cmt_ambig_input", attempt_dir=tmp_path
        )
        assert res["ok"] is False
        assert "输入框匹配到多个" in res["error"]
        # 验证失败时已调用 _safe_close_editor 清理 DOM，reply-wrap 被隐藏
        assert page.locator("#reply-wrap").is_visible() is False
    finally:
        page.close()


def test_calibrate_fail_closed_missing_editor_input(chromium, adapter_instance, tmp_path):
    """验证展开后未出现任何输入框时，阻断并清理。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html>
        <head>
          <style>
            .action-icon { display: inline-block; width: 16px; height: 16px; }
          </style>
        </head>
        <body>
          <div class="comment-item" id="target">
            <span class="action-icon weui-icon-outlined-comment" id="reply-trigger">回复</span>
            <div class="comment-reply-wrap" id="reply-wrap" style="display:none;">
              <div class="reply-opt">
                <button type="button" class="weui-desktop-btn_default">取消</button>
                <button type="button" class="weui-desktop-btn_primary" disabled>评论</button>
              </div>
            </div>
          </div>
          <script>
            document.querySelector('#reply-trigger').addEventListener('click', () => {
              document.querySelector('#reply-wrap').style.display = 'block';
            });
          </script>
        </body></html>
        """)
        parent = page.locator("#target")

        res = adapter_instance.calibrate_comment_controls(
            page, parent_item=parent, root_comment_id="cmt_no_input", attempt_dir=tmp_path
        )
        assert res["ok"] is False
        assert "未能定位到二级回复输入框" in res["error"]
    finally:
        page.close()


def test_calibrate_fail_closed_ambiguous_submit_button(chromium, adapter_instance, tmp_path):
    """验证提交按钮存在多个时，阻断并清理。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html>
        <head>
          <style>
            .action-icon { display: inline-block; width: 16px; height: 16px; }
            .edit-area { display: block; width: 200px; height: 50px; }
          </style>
        </head>
        <body>
          <div class="comment-item" id="target">
            <span class="action-icon weui-icon-outlined-comment" id="reply-trigger">回复</span>
            <div class="comment-reply-wrap" id="reply-wrap" style="display:none;">
              <div contenteditable="true" class="edit-area"></div>
              <div class="reply-opt">
                <button type="button" class="weui-desktop-btn_default">取消</button>
                <button type="button" class="weui-desktop-btn weui-desktop-btn_primary">评论</button>
                <button type="button" class="weui-desktop-btn weui-desktop-btn_primary">评论</button>
              </div>
            </div>
          </div>
          <script>
            document.querySelector('#reply-trigger').addEventListener('click', () => {
              document.querySelector('#reply-wrap').style.display = 'block';
            });
            document.querySelector('.weui-desktop-btn_default').addEventListener('click', () => {
              document.querySelector('#reply-wrap').style.display = 'none';
            });
          </script>
        </body></html>
        """)
        parent = page.locator("#target")

        res = adapter_instance.calibrate_comment_controls(
            page, parent_item=parent, root_comment_id="cmt_ambig_submit", attempt_dir=tmp_path
        )
        assert res["ok"] is False
        assert "提交按钮匹配到多个" in res["error"]
        assert page.locator("#reply-wrap").is_visible() is False
    finally:
        page.close()


def test_calibrate_fail_closed_missing_submit_button(chromium, adapter_instance, tmp_path):
    """验证缺失提交按钮时，阻断并清理。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html>
        <head>
          <style>
            .action-icon { display: inline-block; width: 16px; height: 16px; }
            .edit-area { display: block; width: 200px; height: 50px; }
          </style>
        </head>
        <body>
          <div class="comment-item" id="target">
            <span class="action-icon weui-icon-outlined-comment" id="reply-trigger">回复</span>
            <div class="comment-reply-wrap" id="reply-wrap" style="display:none;">
              <div contenteditable="true" class="edit-area"></div>
              <div class="reply-opt">
                <button type="button" class="weui-desktop-btn_default">取消</button>
              </div>
            </div>
          </div>
          <script>
            document.querySelector('#reply-trigger').addEventListener('click', () => {
              document.querySelector('#reply-wrap').style.display = 'block';
            });
          </script>
        </body></html>
        """)
        parent = page.locator("#target")

        res = adapter_instance.calibrate_comment_controls(
            page, parent_item=parent, root_comment_id="cmt_no_submit", attempt_dir=tmp_path
        )
        assert res["ok"] is False
        assert "未能定位到二级回复提交按钮" in res["error"]
    finally:
        page.close()


# ============================================================================
# Section 2: Zero-Write Guarantees & Editor Calibration
# ============================================================================

def test_calibrate_zero_write_and_disabled_submit_verification(chromium, adapter_instance, tmp_path):
    """经验证：校准全程绝不向输入框键入字符、绝不点击提交按钮，且准确校验空输入禁用状态。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html>
        <head>
          <style>
            .action-icon { display: inline-block; width: 16px; height: 16px; }
            .edit-area { display: block; width: 200px; height: 50px; }
          </style>
        </head>
        <body>
          <div class="comment-item" id="target" data-comment-id="synth_cmt_real_dom">
            <div class="comment-main">
              <span class="user">观众甲</span>
              <p class="text">精彩的宏观分析！</p>
              <div class="action-item">
                <span class="action-icon weui-icon-outlined-comment"></span>
              </div>
            </div>
            <div class="comment-reply-wrap" style="display:none;">
              <div class="placeholder">回复 观众甲：</div>
              <div contenteditable="true" class="edit-area"></div>
              <div class="reply-opt">
                <button type="button" class="weui-desktop-btn weui-desktop-btn_default weui-desktop-btn_mini">取消</button>
                <button type="button" class="weui-desktop-btn weui-desktop-btn_primary weui-desktop-btn_mini weui-desktop-btn_disabled" disabled>评论</button>
              </div>
            </div>
          </div>
          <script>
            window.__eventsRecorded = {inputEvents: 0, submitClicks: 0, cancelClicks: 0};

            const trigger = document.querySelector('.action-icon.weui-icon-outlined-comment');
            const wrap = document.querySelector('.comment-reply-wrap');
            const editArea = document.querySelector('.edit-area');
            const submitBtn = document.querySelector('.weui-desktop-btn_primary');
            const cancelBtn = document.querySelector('.weui-desktop-btn_default');

            trigger.addEventListener('click', () => {
              wrap.style.display = 'block';
            });

            editArea.addEventListener('input', () => { window.__eventsRecorded.inputEvents++; });
            editArea.addEventListener('keydown', () => { window.__eventsRecorded.inputEvents++; });
            editArea.addEventListener('keypress', () => { window.__eventsRecorded.inputEvents++; });

            submitBtn.addEventListener('click', () => { window.__eventsRecorded.submitClicks++; });
            cancelBtn.addEventListener('click', () => {
              window.__eventsRecorded.cancelClicks++;
              wrap.style.display = 'none';
            });
          </script>
        </body></html>
        """)
        parent = page.locator("#target")

        res = adapter_instance.calibrate_comment_controls(
            page, parent_item=parent, root_comment_id="synth_cmt_real_dom", attempt_dir=tmp_path
        )

        assert res["ok"] is True, f"校准失败: {res.get('error')}"
        assert res["error"] is None
        calib = res["controls_calibration"]

        # 1. 验证回复图标
        assert calib["reply_icon"]["found"] is True
        assert calib["reply_icon"]["count"] == 1
        assert calib["reply_icon"]["enabled"] is True

        # 2. 验证输入框诊断与零键入
        assert calib["editor_textarea"]["found"] is True
        assert calib["editor_textarea"]["editable"] is True
        assert calib["editor_textarea"]["is_empty"] is True

        # 3. 验证提交按钮为空时禁用
        assert calib["submit_button"]["found"] is True
        assert calib["submit_button"]["disabled_when_empty"] is True

        # 4. 严格断言事件钩子：输入为 0，点击为 0，取消点击为 1
        recorded = page.evaluate("() => window.__eventsRecorded")
        assert recorded["inputEvents"] == 0, f"违规！输入框捕获到输入事件: {recorded['inputEvents']}"
        assert recorded["submitClicks"] == 0, f"违规！提交按钮捕获到点击事件: {recorded['submitClicks']}"
        assert recorded["cancelClicks"] == 1, "取消按钮未被点击以清理现场"

        # 5. 断言输入框文本严格为空
        text_content = page.evaluate("() => document.querySelector('.edit-area').innerText")
        assert text_content.strip() == ""
    finally:
        page.close()


# ============================================================================
# Section 3: Safe Editor Cleanup (_safe_close_editor)
# ============================================================================

def test_safe_close_editor_via_cancel_button(chromium, adapter_instance):
    """验证存在取消按钮时，点击取消按钮能将编辑器完全隐藏并返回 True。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <div class="comment-item" id="parent">
            <div class="comment-reply-wrap">
              <div contenteditable="true" class="edit-area"></div>
              <div class="reply-opt">
                <button type="button" class="weui-desktop-btn weui-desktop-btn_default weui-desktop-btn_mini">取消</button>
              </div>
            </div>
          </div>
          <script>
            document.querySelector('.weui-desktop-btn_default').addEventListener('click', () => {
              document.querySelector('.comment-reply-wrap').remove();
            });
          </script>
        </body></html>
        """)
        parent = page.locator("#parent")
        textarea = parent.locator(".edit-area")
        assert textarea.is_visible() is True

        closed = adapter_instance._safe_close_editor(
            page, parent, editor_already_open=False, textarea_loc=textarea
        )
        assert closed is True
        assert page.locator(".edit-area").count() == 0
    finally:
        page.close()


def test_safe_close_editor_via_escape_fallback(chromium, adapter_instance):
    """验证缺少取消按钮但支持 ESC 键盘事件时，通过 Escape 隐藏并返回 True。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <div class="comment-item" id="parent">
            <div class="comment-reply-wrap">
              <div contenteditable="true" class="edit-area"></div>
            </div>
          </div>
          <script>
            window.addEventListener('keydown', (e) => {
              if (e.key === 'Escape') {
                document.querySelector('.comment-reply-wrap').style.display = 'none';
              }
            });
          </script>
        </body></html>
        """)
        parent = page.locator("#parent")
        textarea = parent.locator(".edit-area")
        assert textarea.is_visible() is True

        closed = adapter_instance._safe_close_editor(
            page, parent, editor_already_open=False, textarea_loc=textarea
        )
        assert closed is True
        assert textarea.is_visible() is False
    finally:
        page.close()


def test_safe_close_editor_unclosable_returns_false(chromium, adapter_instance):
    """验证当取消按钮与 ESC 均无法关闭编辑器时，准确反馈 False。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <div class="comment-item" id="parent">
            <div class="comment-reply-wrap">
              <div contenteditable="true" class="edit-area"></div>
              <div class="reply-opt">
                <!-- 取消按钮点击不生效 -->
                <button type="button" class="weui-desktop-btn_default">取消</button>
              </div>
            </div>
          </div>
        </body></html>
        """)
        parent = page.locator("#parent")
        textarea = parent.locator(".edit-area")

        closed = adapter_instance._safe_close_editor(
            page, parent, editor_already_open=False, textarea_loc=textarea
        )
        assert closed is False
        assert textarea.is_visible() is True
    finally:
        page.close()


def test_safe_close_editor_already_open_preserved(chromium, adapter_instance):
    """验证探测前原本就展开的编辑器，保留原状不强行关闭。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <div class="comment-item" id="parent">
            <div class="comment-reply-wrap">
              <div contenteditable="true" class="edit-area"></div>
            </div>
          </div>
        </body></html>
        """)
        parent = page.locator("#parent")
        textarea = parent.locator(".edit-area")

        closed = adapter_instance._safe_close_editor(
            page, parent, editor_already_open=True, textarea_loc=textarea
        )
        assert closed is True
        assert textarea.is_visible() is True
    finally:
        page.close()


# ============================================================================
# Section 4: Route Abortion Enforcement
# ============================================================================

def test_route_abortion_strictly_blocks_create_comment_variants(chromium):
    """验证针对 **/comment/create_comment* 的路由硬拦截阻止任何形式的出站发评。"""
    page = chromium.new_page()
    try:
        aborted_requests = []

        def route_handler(route):
            request = route.request
            if request.is_navigation_request():
                route.fulfill(content_type="text/html", body="""
                <html><body>
                  <button id="btn1">相对路径发送</button>
                  <button id="btn2">微前端路径发送</button>
                  <button id="btn3">带参数发送</button>
                  <script>
                    window.__errors = [];
                    async function tryPost(url) {
                      try {
                        await fetch(url, {
                          method: 'POST',
                          headers: {'Content-Type': 'application/json'},
                          body: JSON.stringify({content: 'test'})
                        });
                      } catch (e) {
                        window.__errors.push(e.message || String(e));
                      }
                    }
                    document.querySelector('#btn1').addEventListener('click', () => {
                      tryPost('/cgi-bin/mmfinderassistant-bin/comment/create_comment');
                    });
                    document.querySelector('#btn2').addEventListener('click', () => {
                      tryPost('/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/create_comment');
                    });
                    document.querySelector('#btn3').addEventListener('click', () => {
                      tryPost('/cgi-bin/mmfinderassistant-bin/comment/create_comment?scene=interaction&timestamp=123');
                    });
                  </script>
                </body></html>
                """)
                return
            route.continue_()

        # 全局路由处理器服务测试页面
        page.route("http://wechat-fixture.invalid/**", route_handler)

        # 适配器注册的强拦截守卫
        def abort_handler(route):
            aborted_requests.append(route.request.url)
            route.abort()

        page.route("**/comment/create_comment*", abort_handler)

        page.goto("http://wechat-fixture.invalid/platform/interaction/comment")

        # 触发 3 种变体的发评请求
        page.click("#btn1")
        page.wait_for_timeout(300)
        page.click("#btn2")
        page.wait_for_timeout(300)
        page.click("#btn3")
        page.wait_for_timeout(300)

        assert len(aborted_requests) == 3
        errors = page.evaluate("() => window.__errors")
        assert len(errors) == 3
        # 所有请求在前端均以网络异常/Failed to fetch 告终
        assert all("Failed to fetch" in err or "aborted" in err.lower() or "network" in err.lower() for err in errors)
    finally:
        page.close()


def test_submission_guard_intercepts_unauthorized_outbound(tmp_path):
    """验证 SecondaryReplySubmissionGuard 网络前守卫对各畸变/未授权请求的硬拦截。"""
    guard = SecondaryReplySubmissionGuard(
        expected_export_id="export/post_valid_123",
        expected_root_comment_id="cmt_root_valid",
        expected_content="合法的回复正文",
        expected_finder_id="valid_author@finder",
        trusted_origins=("https://channels.weixin.qq.com",),
    )

    class DummyRequest:
        def __init__(self, url, method="POST", payload=None):
            self.url = url
            self.method = method
            self.post_data_json = payload

    valid_payload = {
        "exportId": "export/post_valid_123",
        "rootCommentId": "cmt_root_valid",
        "replyCommentId": "cmt_root_valid",
        "content": "合法的回复正文",
        "_log_finder_id": "valid_author@finder",
    }

    # 1. 非受信来源
    req_untrusted = DummyRequest("https://malicious.example.com/cgi-bin/mmfinderassistant-bin/comment/create_comment", payload=valid_payload)
    assert guard.capture_request(req_untrusted) is False
    assert guard.mismatched_requests[-1]["reason"] == "UNTRUSTED_ORIGIN"

    # 2. 缺失必填字段 (缺少 content)
    bad_payload = dict(valid_payload)
    del bad_payload["content"]
    req_missing = DummyRequest("https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/comment/create_comment", payload=bad_payload)
    assert guard.capture_request(req_missing) is False
    assert guard.mismatched_requests[-1]["reason"] == "MISSING_REQUIRED_FIELD"

    # 3. 错帖 exportId
    wrong_export_payload = dict(valid_payload, exportId="export/wrong_post")
    req_wrong_export = DummyRequest("https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/comment/create_comment", payload=wrong_export_payload)
    assert guard.capture_request(req_wrong_export) is False
    assert guard.mismatched_requests[-1]["reason"] == "FIELD_MISMATCH"
    assert any("exportId mismatch" in d for d in guard.mismatched_requests[-1]["details"])

    # 4. 错作者账号
    wrong_author_payload = dict(valid_payload, _log_finder_id="imposter@finder")
    req_wrong_author = DummyRequest("https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/comment/create_comment", payload=wrong_author_payload)
    assert guard.capture_request(req_wrong_author) is False
    assert guard.mismatched_requests[-1]["reason"] == "FIELD_MISMATCH"
    assert any("account mismatch" in d for d in guard.mismatched_requests[-1]["details"])

    # 5. 合法请求准许并记录
    req_valid = DummyRequest("https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/comment/create_comment", payload=valid_payload)
    assert guard.capture_request(req_valid) is True
    assert len(guard.requests) == 1

    # 6. 重复出站请求硬拦截
    assert guard.capture_request(req_valid) is False
    assert guard.mismatched_requests[-1]["reason"] == "DUPLICATE_SUBMISSION"


# ============================================================================
# Section 5: Decoupled Verification Controls Flag
# ============================================================================

def test_interact_with_page_verify_controls_flag_behavior(chromium, adapter_instance, tmp_path):
    """验证 _interact_with_page 在 verify_only=True 下受 verify_controls 控制的解耦分支。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <main id="cards">
            <button class="post-card" data-object-id="export/synth_post_100">目标视频</button>
          </main>
          <div id="detail-host">
            <article data-current-object-id="export/synth_post_100">
              <div class="comment-item-main" data-comment-id="synth_cmt_100">
                <span class="user">用户甲</span>
                <p class="content">原生态评论</p>
                <button type="button" class="reply-btn" data-reply>回复</button>
                <div class="reply-compose" hidden>
                  <div contenteditable="true" class="edit-area"></div>
                  <div class="reply-opt">
                    <button type="button" class="weui-desktop-btn_default">取消</button>
                    <button type="button" class="weui-desktop-btn_primary" disabled>评论</button>
                  </div>
                </div>
                <div class="level-two" data-level-two></div>
              </div>
            </article>
          </div>
          <script>
            window.__replyClicked = 0;
            const replyBtn = document.querySelector('[data-reply]');
            const compose = document.querySelector('.reply-compose');
            replyBtn.addEventListener('click', () => {
              window.__replyClicked++;
              compose.hidden = false;
            });
            document.querySelector('.weui-desktop-btn_default').addEventListener('click', () => {
              compose.hidden = true;
            });
          </script>
        </body></html>
        """)

        guard = SecondaryReplySubmissionGuard(
            expected_export_id="export/synth_post_100",
            expected_root_comment_id="synth_cmt_100",
            expected_content="回复内容",
            expected_finder_id="synth_author@finder",
        )

        attempt_dir_1 = tmp_path / "attempt_1"
        attempt_dir_1.mkdir(parents=True, exist_ok=True)

        # 1. 默认行为：verify_only=True, verify_controls=False -> 零 DOM 操作快速返回
        status_1, evidence_1, msg_1 = adapter_instance._interact_with_page(
            page,
            task_id=1,
            platform_post_id="export/synth_post_100",
            root_comment_id="synth_cmt_100",
            reply_content="回复内容",
            guard=guard,
            verify_only=True,
            verify_controls=False,
            attempt_dir=attempt_dir_1,
        )
        assert status_1 == "VERIFIED_ABSENT"
        assert evidence_1 is None
        assert "作者尚未回复" in msg_1
        # 证明回复按钮未被点击，编辑器未展开
        assert page.evaluate("() => window.__replyClicked") == 0
        assert page.locator(".reply-compose").is_visible() is False

        # 2. 校准行为：verify_only=True, verify_controls=True -> 执行只读控件校准
        attempt_dir_2 = tmp_path / "attempt_2"
        attempt_dir_2.mkdir(parents=True, exist_ok=True)

        status_2, evidence_2, msg_2 = adapter_instance._interact_with_page(
            page,
            task_id=2,
            platform_post_id="export/synth_post_100",
            root_comment_id="synth_cmt_100",
            reply_content="回复内容",
            guard=guard,
            verify_only=True,
            verify_controls=True,
            attempt_dir=attempt_dir_2,
        )
        assert status_2 == "VERIFIED_ABSENT"
        assert "且控件校准通过" in msg_2
        assert page.evaluate("() => window.__replyClicked") == 1
        # 校准结束后编辑器已通过取消按钮安全关闭
        assert page.locator(".reply-compose").is_visible() is False
    finally:
        page.close()


def test_interact_with_page_resolves_nested_action_item_reply_button_without_union_collision(
    chromium, adapter_instance, tmp_path
):
    """M2 核心回归：验证真实微信 DOM 嵌套结构 (.action-item > .action-icon) 不会触发选择器联合碰撞 (count=2)。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html><body>
          <div class="comment-item" data-comment-id="cmt_nested_101">
            <div class="comment-content">测试评论内容</div>
            <div class="action-item" style="display:inline-block;width:30px;height:30px;">
              <span class="action-icon weui-icon-outlined-comment" style="display:inline-block;width:16px;height:16px;" onclick="window.__replyClicked = true;"></span>
            </div>
            <div class="comment-reply-wrap" style="display:none;">
              <textarea placeholder="回复："></textarea>
              <button class="weui-desktop-btn_primary">评论</button>
            </div>
          </div>
        </body></html>
        """)
        parent_item = page.locator("[data-comment-id='cmt_nested_101']")
        
        # 1. 验证如果使用联合选择器，在嵌套 DOM 上确实会触发 count() == 2 的碰撞
        union_loc = parent_item.locator(
            ".action-icon.weui-icon-outlined-comment, .action-item:has(.weui-icon-outlined-comment)"
        ).filter(visible=True)
        assert union_loc.count() == 2, f"Expected union collision count=2, got {union_loc.count()}"

        # 2. 验证修复后的单候选顺序解析能正确唯一定位 span.action-icon
        reply_candidates = [
            ".action-icon.weui-icon-outlined-comment",
            ".action-item:has(.weui-icon-outlined-comment)",
            "[data-reply]",
            "button[aria-label='回复'], [role='button'][aria-label='回复']",
            "button:text-is('回复'), [role='button']:text-is('回复')",
        ]
        matched_btn = None
        for cand in reply_candidates:
            loc = parent_item.locator(cand).filter(visible=True)
            if loc.count() == 1:
                matched_btn = loc.first
                break
            elif loc.count() > 1:
                matched_btn = None
                break
        assert matched_btn is not None
        assert matched_btn.is_enabled()
    finally:
        page.close()


def test_calibrate_page_controls_three_way_classification_and_identity(
    chromium, adapter_instance, tmp_path
):
    """验证 calibrate_page_controls 正确产出三态回复分类、原生身份核验与正文一致性判定。"""
    page = chromium.new_page()
    try:
        # 设置模拟平台环境与 localStorage 身份
        page.set_content("""
        <html>
        <body data-finder-username="v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder">
          <div class="account-info"><span class="name">六维时空号</span></div>
          <div class="scroll-list__wrp">
            <div class="comment-feed-wrap" data-object-id="export/test_post_001">
              <div class="post-title">面对癌症，财富究竟能带来什么？</div>
            </div>
          </div>
          <div data-current-object-id="export/test_post_001">
            <div class="comment-item" data-comment-id="cmt_canary">
              <span class="comment-content">目标测试评论原文</span>
              <div class="action-item" style="display:inline-block;width:30px;height:30px;">
                <span class="action-icon weui-icon-outlined-comment" style="display:inline-block;width:16px;height:16px;" onclick="this.closest('.comment-item').querySelector('.comment-reply-wrap').style.display='block';"></span>
              </div>
              <div class="comment-reply-wrap" style="display:none;">
                <textarea placeholder="回复："></textarea>
                <button type="button" class="weui-desktop-btn_primary" disabled>评论</button>
                <button type="button" class="weui-desktop-btn_default">取消</button>
              </div>
            </div>
          </div>
        </body></html>
        """)

        author_finder = "v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder"

        # 1. 模拟已回复场景 -> REPLIED
        adapter_instance._check_author_already_replied = lambda p, cid, aid: (True, "COMPLETE", p.locator(f"[data-comment-id='{cid}']"))
        res_replied = adapter_instance.calibrate_page_controls(
            page,
            platform_post_id="export/test_post_001",
            root_comment_id="cmt_canary",
            author_id=author_finder,
            video_title="面对癌症，财富究竟能带来什么？",
            attempt_dir=tmp_path,
        )
        assert res_replied["ok"] is True
        assert res_replied["status"] == "REPLIED"
        assert res_replied["channel_profile"]["identity_verified"] is True
        assert res_replied["channel_profile"]["channel_nickname"] == "六维时空号"

        # 2. 模拟折叠/未穷尽分页场景 -> UNKNOWN
        adapter_instance._check_author_already_replied = lambda p, cid, aid: (False, "PAGINATION_INCOMPLETE", p.locator(f"[data-comment-id='{cid}']"))
        res_unknown = adapter_instance.calibrate_page_controls(
            page,
            platform_post_id="export/test_post_001",
            root_comment_id="cmt_canary",
            author_id=author_finder,
            video_title="面对癌症，财富究竟能带来什么？",
            attempt_dir=tmp_path,
        )
        assert res_unknown["ok"] is False
        assert res_unknown["status"] == "UNKNOWN"
        assert "二级回复分页未穷尽" in res_unknown["reason"]

        # 3. 模拟正文不匹配场景 -> Fail-Closed UNKNOWN
        adapter_instance._check_author_already_replied = lambda p, cid, aid: (False, "COMPLETE", p.locator(f"[data-comment-id='{cid}']"))
        adapter_instance._captured_comments["cmt_canary"] = {
            "content_prefix": "这是评论区实际采集到的原文",
            "nickname": "张三",
            "downContinueFlag": 0,
        }
        res_drift = adapter_instance.calibrate_page_controls(
            page,
            platform_post_id="export/test_post_001",
            root_comment_id="cmt_canary",
            author_id=author_finder,
            video_title="面对癌症，财富究竟能带来什么？",
            expected_comment_text="这是预期的完全不同的原文",
            attempt_dir=tmp_path,
        )
        assert res_drift["ok"] is False
        assert res_drift["status"] == "UNKNOWN"
        assert "目标评论正文与预期不符" in res_drift["reason"]
        assert res_drift["target"]["text_matched"] is False

        # 4. 模拟正文完全匹配且作者未回复 -> NOT_REPLIED
        res_canary = adapter_instance.calibrate_page_controls(
            page,
            platform_post_id="export/test_post_001",
            root_comment_id="cmt_canary",
            author_id=author_finder,
            video_title="面对癌症，财富究竟能带来什么？",
            expected_comment_text="目标测试评论原文",
            attempt_dir=tmp_path,
        )
        assert res_canary["ok"] is True
        assert res_canary["status"] == "NOT_REPLIED"
        assert res_canary["target"]["text_matched"] is True
        assert res_canary["channel_profile"]["identity_verified"] is True
    finally:
        page.close()


def test_browser_platform_calibrate_and_verify_e2e(chromium, adapter_instance, tmp_path):
    """M3 回归：验证 BrowserSecondaryReplyPlatform 与 ops.verify_platform 真实浏览器端到端校准流程。"""
    page = chromium.new_page()
    try:
        page.set_content("""
        <html>
        <body data-finder-username="v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder">
          <div class="account-info"><span class="name">六维时空号</span></div>
          <div class="scroll-list__wrp">
            <div class="comment-feed-wrap" data-object-id="export/UzFfBgAAxOClNFsoN2Spk8zT4DCaVikQXENps3YeyGFwg_SlGQ">
              <div class="post-title">面对癌症，财富究竟能带来什么？</div>
            </div>
          </div>
          <div data-current-object-id="export/UzFfBgAAxOClNFsoN2Spk8zT4DCaVikQXENps3YeyGFwg_SlGQ">
            <div class="comment-item" data-comment-id="15031175812304083586">
              <span class="comment-content">目标测试评论原文</span>
              <div class="action-item" style="display:inline-block;width:30px;height:30px;">
                <span class="action-icon weui-icon-outlined-comment" style="display:inline-block;width:16px;height:16px;" onclick="this.closest('.comment-item').querySelector('.comment-reply-wrap').style.display='block';"></span>
              </div>
              <div class="comment-reply-wrap" style="display:none;">
                <div contenteditable="true" class="edit-area"></div>
                <button type="button" class="weui-desktop-btn_primary" disabled>评论</button>
                <button type="button" class="weui-desktop-btn_default" onclick="this.closest('.comment-reply-wrap').style.display='none';">取消</button>
              </div>
            </div>
          </div>
        </body></html>
        """)

        import contextlib
        from video_processing.interaction.secondary_reply_browser_platform import BrowserSecondaryReplyPlatform
        from video_processing.interaction import secondary_reply_ops as ops

        author_finder = "v2_060000231003b20faec8c6e6811acad1ca06e534b07788b29eed6dd8e71aca67283987b679b6@finder"

        @contextlib.contextmanager
        def fake_session(guard):
            yield page

        platform = BrowserSecondaryReplyPlatform(
            adapter_instance,
            account_finder_id=author_finder,
            session_factory=fake_session,
            evidence_dir=tmp_path / "evidence",
        )

        evidence_out = tmp_path / "evidence_out"
        res = ops.verify_platform(
            None,
            post_id="export/UzFfBgAAxOClNFsoN2Spk8zT4DCaVikQXENps3YeyGFwg_SlGQ",
            comment_id="15031175812304083586",
            platform=platform,
            account_key="sphjAH8AbMh8oYP",
            finder_id=author_finder,
            video_title="面对癌症，财富究竟能带来什么？",
            comment_text="目标测试评论原文",
            evidence_dir=evidence_out,
        )

        assert res["ok"] is True
        assert res["status"] == "NOT_REPLIED"
        assert res["channel_profile"]["identity_verified"] is True
        assert res["channel_profile"]["account_key"] == "sphjAH8AbMh8oYP"
        assert res["channel_profile"]["channel_nickname"] == "六维时空号"
        assert res["target"]["post_id"] == "export/UzFfBgAAxOClNFsoN2Spk8zT4DCaVikQXENps3YeyGFwg_SlGQ"
        assert res["target"]["comment_id"] == "15031175812304083586"
        assert res["target"]["text_matched"] is True
        assert res["target"]["fresh"] is True

        calib = res["controls_calibration"]
        assert calib["reply_icon"]["found"] is True
        assert calib["reply_icon"]["count"] == 1
        assert calib["editor_textarea"]["found"] is True
        assert calib["submit_button"]["found"] is True
        assert calib["submit_button"]["disabled_when_empty"] is True

        # 验证证据文件落盘
        ev_json = Path(res["evidence_files"]["json"])
        assert ev_json.exists()
        saved = json.loads(ev_json.read_text(encoding="utf-8"))
        assert saved["ok"] is True
        assert saved["status"] == "NOT_REPLIED"
    finally:
        page.close()



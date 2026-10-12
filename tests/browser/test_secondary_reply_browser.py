"""视频号二级回复真实 Chromium 隔离浏览器端到端闭环测试。

验证：
- 完整成功路径：卡片绑定 -> 原生 commentId 绑定 -> 意图持久化 -> 提交回执 -> 独立回读 -> VERIFIED (T16)
- 防重闭环：第二次运行被独立防重账本拦截，零重复出站请求 (T05, T16)
- 锁内复审：作者已在手机端回复时安全跳过 (SKIPPED_ALREADY_REPLIED) (T04)
- 网络前守卫拦截：错作品 exportId 或错 rootCommentId 在网络前熔断 (T06)
- 异常对账：提交后网络丢包/假死转入 UNCERTAIN 只读对账 (T08, T10)
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import uuid
import pytest

from tests.browser_fixtures import chromium
from video_processing.db.database import PipelineDB
from video_processing.interaction.secondary_reply_browser_adapter import (
    SecondaryReplyBrowserAdapter,
    SecondaryReplySubmissionGuard,
    COMMENT_SUBMIT_PATHS,
)

FIXTURE_HTML = Path(__file__).resolve().parents[1] / "fixtures" / "wechat_secondary_reply.html"
COMMENT_SUBMIT_PATH = "/cgi-bin/mmfinderassistant-bin/comment/create_comment"
UTC = datetime.timezone.utc


@pytest.fixture
def secondary_reply_harness(chromium, tmp_path):
    """构建受控 Chromium 页面与路由桩。"""
    page = chromium.new_page(viewport={"width": 1280, "height": 800})
    writes = []
    current_guard = [None]
    server_replies = []  # 模拟服务器持久化数据：仅它能在刷新后被读回

    def route_handler(route):
        request = route.request
        path = request.url.split("?", 1)[0].replace("http://wechat-fixture.invalid", "")
        if request.is_navigation_request():
            inject = "<script>window.__serverReplies = %s;</script>" % json.dumps(server_replies, ensure_ascii=False)
            route.fulfill(content_type="text/html", body=inject + FIXTURE_HTML.read_text(encoding="utf-8"))
            return
        if request.method == "POST":
            payload = request.post_data_json
            writes.append({"path": path, "payload": payload})
            mode = page.evaluate("window.fixtureState.mode")

            if path == COMMENT_SUBMIT_PATH:
                if current_guard[0] is not None:
                    safe = current_guard[0].capture_request(request)
                    if not safe:
                        route.abort()
                        return

                if mode == "drop-response":
                    route.abort()
                    return
                elif mode == "rejected":
                    route.fulfill(json={"errCode": -1, "errMsg": "platform rejected"})
                    return
                else:
                    if mode != "success-not-persisted":
                        server_replies.append({"commentId": "synth_new_reply_999", "content": payload.get("content")})
                    route.fulfill(json={
                        "errCode": 0,
                        "errMsg": "request successful",
                        "data": {
                            "commentId": "synth_new_reply_999",
                            "clientId": payload.get("clientId"),
                            "comment": {
                                "commentId": "synth_new_reply_999",
                                "commentContent": payload.get("content"),
                                "replyCommentId": payload.get("replyCommentId"),
                                "username": "v2_synthetic_author_finder_id@finder"
                            }
                        }
                    })
                    return
        route.continue_()

    page.route("**/*", route_handler)
    page.on("response", lambda resp: current_guard[0].capture_response(resp) if current_guard[0] else None)

    state_file = tmp_path / "wechat_state.json"
    state_file.write_text("{}", encoding="utf-8")
    db_file = tmp_path / "test.db"
    db = PipelineDB(db_path=str(db_file))

    try:
        yield {
            "page": page,
            "writes": writes,
            "server_replies": server_replies,
            "current_guard": current_guard,
            "state_file": state_file,
            "db": db,
            "tmp_path": tmp_path,
        }
    finally:
        page.close()


def _run_secondary(
    harness,
    *,
    task_id: int,
    platform_post_id: str,
    root_comment_id: str,
    reply_content: str,
    video_title: str = "深度解读视频",
    mode: str = "success",
    before_submit=None,
    verify_only: bool = False,
):
    page = harness["page"]
    page.goto("http://wechat-fixture.invalid/platform/interaction/comment")
    page.evaluate(f"window.fixtureState.mode = '{mode}';")
    adapter = SecondaryReplyBrowserAdapter(
        state_path=harness["state_file"],
        comment_url="http://wechat-fixture.invalid/platform/interaction/comment",
    )
    attempt_dir = harness["tmp_path"] / f"attempt_{task_id}_{uuid.uuid4().hex[:6]}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    guard = SecondaryReplySubmissionGuard(
        expected_export_id=platform_post_id,
        expected_root_comment_id=root_comment_id,
        expected_content=reply_content,
        expected_finder_id="v2_synthetic_author_finder_id@finder",
        trusted_origins=("http://wechat-fixture.invalid",),
    )
    harness["current_guard"][0] = guard

    return adapter._interact_with_page(
        page,
        task_id=task_id,
        platform_post_id=platform_post_id,
        root_comment_id=root_comment_id,
        reply_content=reply_content,
        video_title=video_title,
        attempt_dir=attempt_dir,
        guard=guard,
        before_submit=before_submit,
        verify_only=verify_only,
        db=harness["db"],
    )


def test_browser_flow_success_and_second_run_idempotency(secondary_reply_harness):
    """验证 T16 路径一：成功全链路与二次运行防重。"""
    harness = secondary_reply_harness
    db = harness["db"]
    post_id = "export/synth_video_888"
    root_id = "synth_cmt_101"
    content = "这是针对宏观观点的作者二级回复正文。"

    # 1. 准备任务
    task_id = db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=root_id,
        intent="REPLY",
        style="MACRO",
        chinese_reply=content,
        english_reply="Author macro reply.",
        formatted_reply=content,
        provider="rule_mock",
        status="APPROVED",
    )
    claimed = db.claim_approved_reply_task(task_id=task_id, lease_seconds=7200)
    assert claimed is not None
    lease_token = claimed["lease_token"]

    def before_submit():
        ok, _ = db.record_secondary_reply_submit_intent(task_id, lease_token)
        return ok

    # 执行第一次提交
    status, evidence, err = _run_secondary(
        harness,
        task_id=task_id,
        platform_post_id=post_id,
        root_comment_id=root_id,
        reply_content=content,
        video_title="深度解读视频",
        before_submit=before_submit,
    )
    assert status == "VERIFIED"
    assert err is None
    assert evidence is not None

    # 验证 DB 终态
    task = db.get_secondary_reply_task(task_id)
    assert task["status"] == "VERIFIED"
    assert task["platform_reply_comment_id"] == "synth_new_reply_999"

    # 验证独立防重账本已升级为 VERIFIED
    ledger = db.check_secondary_reply_idempotency(post_id, root_id)
    assert ledger is not None
    assert ledger["status"] == "VERIFIED"

    # 第二次尝试运行：必须在 before_submit 时被独立防重账本直接拦截！
    task_id_second = db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=root_id,
        intent="REPLY",
        style="MACRO",
        chinese_reply=content,
        english_reply="Author macro reply.",
        formatted_reply=content,
        provider="rule_mock",
        status="APPROVED",
    )
    claimed_sec = db.claim_approved_reply_task(task_id=task_id_second, lease_seconds=7200)

    # 推进时间 30 秒以绕过 15 秒限制，专注于验证防重账本
    now_later = (datetime.datetime.now(UTC) + datetime.timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")

    def before_submit_second():
        ok, reason = db.record_secondary_reply_submit_intent(task_id_second, claimed_sec["lease_token"], now_utc=now_later)
        return ok

    # 模拟页面读取不到已发回复（折叠/延迟）：此时只能靠独立防重账本拦截，不能重发
    harness["server_replies"].clear()
    writes_before = len(harness["writes"])
    status2, _, err2 = _run_secondary(
        harness,
        task_id=task_id_second,
        platform_post_id=post_id,
        root_comment_id=root_id,
        reply_content=content,
        video_title="深度解读视频",
        before_submit=before_submit_second,
    )
    # 意图落盘被阻断，未发出出站请求
    assert status2 == "FAILED"
    assert "持久化提交意图失败" in (err2 or "")
    assert len(harness["writes"]) == writes_before  # 第二次没有任何出站写请求


def test_browser_flow_skips_when_author_already_replied(secondary_reply_harness):
    """验证 T04: 锁内复审发现作者已在手机端回复时安全跳过。"""
    harness = secondary_reply_harness
    db = harness["db"]
    post_id = "export/synth_video_888"
    root_id = "synth_cmt_104"  # 该评论在 HTML 夹具中已有作者二级回复
    content = "试图再次回复的内容"

    task_id = db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=root_id,
        intent="REPLY",
        style="MACRO",
        chinese_reply=content,
        provider="rule_mock",
        status="APPROVED",
    )
    claimed = db.claim_approved_reply_task(task_id=task_id)

    status, evidence, err = _run_secondary(
        harness,
        task_id=task_id,
        platform_post_id=post_id,
        root_comment_id=root_id,
        reply_content=content,
        video_title="深度解读视频",
        before_submit=lambda: True,
    )
    assert status == "SKIPPED_ALREADY_REPLIED"
    assert "作者已在手机端或先前回复" in (err or "")


def test_submission_guard_blocks_mismatched_target():
    """验证 T06: 网络前路由守卫拦截错作品或错 rootCommentId。"""
    guard = SecondaryReplySubmissionGuard(
        expected_export_id="export/expected_123",
        expected_root_comment_id="cmt_root_123",
        expected_content="正确回复正文",
    )

    class FakeRequest:
        method = "POST"
        url = "https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/comment/create_comment"
        post_data_json = {
            "exportId": "export/WRONG_POST",  # 错帖子
            "rootCommentId": "cmt_root_123",
            "replyCommentId": "cmt_root_123",
            "content": "正确回复正文",
        }

    # 守卫必须返回 False 硬熔断
    safe = guard.capture_request(FakeRequest())
    assert safe is False
    assert len(guard.requests) == 0
    assert len(guard.mismatched_requests) == 1
    assert "exportId mismatch" in str(guard.mismatched_requests[0])


def test_browser_flow_dropped_response_reconciles_uncertain(secondary_reply_harness):
    """验证 T08, T10: 提交后丢包/崩溃，转入 UNCERTAIN 只读对账。"""
    harness = secondary_reply_harness
    db = harness["db"]
    post_id = "export/synth_video_888"
    root_id = "synth_cmt_101"
    content = "测试丢包场景"

    task_id = db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=root_id,
        intent="REPLY",
        style="PRAGMATIC",
        chinese_reply=content,
        provider="rule_mock",
        status="APPROVED",
    )
    claimed = db.claim_approved_reply_task(task_id=task_id, lease_seconds=7200)

    status, evidence, err = _run_secondary(
        harness,
        task_id=task_id,
        platform_post_id=post_id,
        root_comment_id=root_id,
        reply_content=content,
        video_title="深度解读视频",
        mode="drop-response",
        before_submit=lambda: db.record_secondary_reply_submit_intent(task_id, claimed["lease_token"])[0],
    )

    assert status == "UNCERTAIN"
    assert "UNCERTAIN" in (err or "")

    # 验证 DB 记录也处于 UNCERTAIN 状态
    task = db.get_secondary_reply_task(task_id)
    assert task["status"] == "UNCERTAIN"

    # 验证独立防重账本中也保持 UNCERTAIN，防止二次盲发
    ledger = db.check_secondary_reply_idempotency(post_id, root_id)
    assert ledger["status"] == "UNCERTAIN"


def test_browser_flow_guard_intercepts_wrong_export_id(secondary_reply_harness):
    """验证 T06 端到端闭环：DOM 或逻辑构造出错误 exportId 时，网络前守卫硬拦截阻断。"""
    harness = secondary_reply_harness
    db = harness["db"]
    post_id = "export/synth_video_888"
    root_id = "synth_cmt_101"
    content = "测试守卫拦截"

    task_id = db.create_or_update_secondary_reply_task(
        platform_post_id=post_id,
        comment_id=root_id,
        intent="REPLY",
        style="PRAGMATIC",
        chinese_reply=content,
        provider="rule_mock",
        status="APPROVED",
    )
    claimed = db.claim_approved_reply_task(task_id=task_id, lease_seconds=7200)

    status, evidence, err = _run_secondary(
        harness,
        task_id=task_id,
        platform_post_id=post_id,
        root_comment_id=root_id,
        reply_content=content,
        video_title="深度解读视频",
        mode="wrong-export-id",
        before_submit=lambda: db.record_secondary_reply_submit_intent(task_id, claimed["lease_token"])[0],
    )

    assert status == "FAILED"
    assert "发送前路由守卫拦截" in (err or "")


def test_browser_flow_optimistic_dom_not_persisted_is_uncertain(secondary_reply_harness):
    """平台返回成功、页面有乐观节点，但刷新后服务器数据没有该回复 -> 不得 VERIFIED。"""
    harness = secondary_reply_harness
    db = harness["db"]
    post_id, root_id, content = "export/synth_video_888", "synth_cmt_101", "乐观节点测试回复"
    task_id = db.create_or_update_secondary_reply_task(
        platform_post_id=post_id, comment_id=root_id, intent="REPLY", style="MACRO",
        chinese_reply=content, english_reply="Optimistic.", formatted_reply=content,
        provider="rule_mock", status="APPROVED",
    )
    claimed = db.claim_approved_reply_task(task_id=task_id, lease_seconds=7200)
    status, _evidence, _err = _run_secondary(
        harness, task_id=task_id, platform_post_id=post_id, root_comment_id=root_id,
        reply_content=content, mode="success-not-persisted",
        before_submit=lambda: db.record_secondary_reply_submit_intent(task_id, claimed["lease_token"])[0],
    )
    assert status == "UNCERTAIN"
    assert db.get_secondary_reply_task(task_id)["status"] != "VERIFIED"

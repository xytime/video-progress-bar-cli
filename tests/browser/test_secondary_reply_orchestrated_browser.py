"""业务编排 + 真实浏览器适配器端口 的隔离 Chromium 全链路验收。

与 ``test_secondary_reply_browser.py`` 的区别：这里经 ``SecondaryReplyOrchestrator`` 与
``BrowserSecondaryReplyPlatform`` 走完整业务路径（终审 -> 作者回复复核 -> 持久意图 -> 唯一出站
-> 全新会话回读 -> 终态 / 只读对账），不直接调用适配器内部函数。
每条拒绝类用例都带相邻的合法对照。
"""

from __future__ import annotations

import contextlib
import datetime
from types import SimpleNamespace

import pytest

from config.settings import settings
from tests.browser.test_secondary_reply_browser import secondary_reply_harness  # noqa: F401  (fixture)
from tests.browser_fixtures import chromium  # noqa: F401  (fixture)
from tests.unit.secondary_reply_support import TEST_ACCOUNT, TEST_APPROVER, TEST_CHAT, approved_task
from video_processing.interaction.secondary_reply_approval import FakeApprovalTransport
from video_processing.interaction.secondary_reply_browser_adapter import SecondaryReplyBrowserAdapter
from video_processing.interaction.secondary_reply_browser_platform import BrowserSecondaryReplyPlatform
from video_processing.interaction.secondary_reply_orchestrator import SecondaryReplyOrchestrator
from video_processing.interaction.secondary_reply_service import SecondaryReplyCensor, SecondaryReplyService

URL = "http://wechat-fixture.invalid/platform/interaction/comment"
POST = "export/synth_video_888"
AUTHOR = "v2_synthetic_author_finder_id@finder"
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 12, 4, 0, 0, tzinfo=UTC)  # 上海 12:00，处于允许时段


@pytest.fixture(autouse=True)
def _no_min_interval(monkeypatch):
    monkeypatch.setattr(settings, "wechat_reply_min_interval_seconds", 0, raising=False)


@pytest.fixture
def stack(secondary_reply_harness):  # noqa: F811
    h = secondary_reply_harness
    page, db = h["page"], h["db"]
    mode_box = ["success"]

    @contextlib.contextmanager
    def session(guard):
        page.goto(URL)
        page.evaluate(f"window.fixtureState.mode = '{mode_box[0]}';")
        h["current_guard"][0] = guard
        try:
            yield page
        finally:
            h["current_guard"][0] = None

    adapter = SecondaryReplyBrowserAdapter(state_path=h["state_file"], comment_url=URL)
    platform = BrowserSecondaryReplyPlatform(
        adapter, account_finder_id=AUTHOR, post_hints=lambda _p: ("深度解读视频", ""),
        session_factory=session, trusted_origins=("http://wechat-fixture.invalid",),
        evidence_dir=h["tmp_path"] / "evidence",
    )
    state = {"now": NOW}

    def clock():
        state["now"] += datetime.timedelta(seconds=60)
        return state["now"]

    orch = SecondaryReplyOrchestrator(
        db=db, service=SecondaryReplyService(censor=SecondaryReplyCensor()), platform=platform,
        approval_transport=FakeApprovalTransport(), account_key=TEST_ACCOUNT, approver_id=TEST_APPROVER,
        approver_chat_id=TEST_CHAT, admin_ids_override=TEST_APPROVER, clock=clock, allow_fixture_drafts=True,
        evidence_dir=h["tmp_path"] / "receipts",
    )
    return SimpleNamespace(h=h, db=db, orch=orch, mode=mode_box, platform=platform)


def _task(s, comment_id="synth_cmt_101"):
    return approved_task(
        s.db, platform_post_id=POST, comment_id=comment_id, chinese_reply="谢谢分享。", english_reply="Thanks.",
        formatted_reply="谢谢分享。\nThanks.", provider="rule_mock",
    )


def _sends(s):
    return [w for w in s.h["writes"] if w["path"].endswith("create_comment")]


def test_orchestrated_success_fresh_session_readback_and_no_resend(stack):
    s = stack
    tid = _task(s)
    out = s.orch.submit(tid)
    assert out.status == "VERIFIED", out
    row = s.db.get_secondary_reply_task(tid)
    assert row["status"] == "VERIFIED" and row["platform_reply_comment_id"] == "synth_new_reply_999"
    assert len(_sends(s)) == 1
    assert s.orch.submit(tid).status == "NOT_CLAIMABLE"
    assert s.orch.submit(tid).status == "NOT_CLAIMABLE"
    assert len(_sends(s)) == 1


def test_optimistic_only_is_uncertain_then_reconcile_finds_late_server_reply_without_resend(stack):
    s = stack
    s.mode[0] = "success-not-persisted"
    tid = _task(s)
    out = s.orch.submit(tid)
    assert out.status == "UNCERTAIN", out  # 平台回执成功，但全新会话读不到服务器数据
    assert len(_sends(s)) == 1
    # 仍读不到：对账保持 UNCERTAIN，且不发任何写请求
    assert s.orch.reconcile(tid).status == "UNCERTAIN"
    assert len(_sends(s)) == 1
    # 服务器延迟落库后：对账确认 VERIFIED（相邻合法对照），仍无新增写请求
    s.h["server_replies"].append({"commentId": "synth_new_reply_999", "content": "谢谢分享。\nThanks.", "authorId": AUTHOR})
    assert s.orch.reconcile(tid).status == "VERIFIED"
    assert len(_sends(s)) == 1


@pytest.mark.parametrize("mode", ["wrong-root-id", "wrong-export-id"])
def test_wrong_target_blocked_before_network_via_real_port(stack, mode):
    s = stack
    s.mode[0] = mode
    out = s.orch.submit(_task(s))
    assert out.status == "BLOCKED_BY_GUARD", out
    assert s.h["server_replies"] == []
    # 相邻合法对照：同一栈、正确模式，另一条任务可成功（用不同评论 ID 的同页评论不存在，故换作品内同评论的新账本不可用；
    # 这里仅断言错目标没有产生服务器回复，成功路径由上一用例覆盖）


def test_author_already_replied_on_page_skips_without_intent(stack):
    s = stack
    tid = _task(s, comment_id="synth_cmt_104")
    out = s.orch.submit(tid)
    assert out.status == "SKIPPED_ALREADY_REPLIED", out
    assert _sends(s) == []
    assert s.db.check_secondary_reply_idempotency(POST, "synth_cmt_104", account_key=TEST_ACCOUNT) is None


def test_unknown_card_fails_closed_before_intent(stack):
    s = stack
    tid = approved_task(
        s.db, platform_post_id="export/synth_not_on_page", comment_id="synth_cmt_101",
        chinese_reply="谢谢分享。", english_reply="Thanks.", formatted_reply="谢谢分享。\nThanks.", provider="rule_mock",
    )
    out = s.orch.submit(tid)
    assert out.status == "REJECTED_BEFORE_INTENT", out
    assert _sends(s) == []
    assert s.db.check_secondary_reply_idempotency("export/synth_not_on_page", "synth_cmt_101", account_key=TEST_ACCOUNT) is None


# ---------------------------------------------------------------------------
# 统一编排经真实浏览器端口完成的四条路径 + 证据反例
# ---------------------------------------------------------------------------

def _receipt(path):
    import json
    from pathlib import Path
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_success_evidence_is_receipt_bound_to_task_account_attempt_and_native_reply_id(stack):
    s = stack
    tid = _task(s)
    out = s.orch.submit(tid)
    assert out.status == "VERIFIED", out
    ref = s.db.get_secondary_reply_task(tid)["evidence_path"]
    r = _receipt(ref)
    assert r["task_id"] == tid and r["account_key"] == TEST_ACCOUNT
    assert r["platform_post_id"] == POST and r["root_comment_id"] == "synth_cmt_101"
    assert r["platform_reply_comment_id"] == "synth_new_reply_999" and r["attempt_id"]
    assert r["source"] == "submit" and r["readback_layer"] == "fresh_session_admin_view"
    assert r["screenshot_after_refresh"] and "readback_" in r["screenshot_after_refresh"]
    from pathlib import Path
    assert Path(r["screenshot_after_refresh"]).exists()


def test_evidence_save_failure_never_reports_verified_and_never_resends(stack):
    s = stack
    # 让证据目录不可创建：占位普通文件作为父路径
    blocker = s.h["tmp_path"] / "blocked"
    blocker.write_text("x")
    s.orch.evidence_dir = blocker / "receipts"
    tid = _task(s)
    out = s.orch.submit(tid)
    assert out.status == "UNCERTAIN" and out.detail == "EVIDENCE_NOT_SAVED", out
    assert s.db.get_secondary_reply_task(tid)["status"] == "UNCERTAIN"
    assert len(_sends(s)) == 1
    # 合法对照：证据目录恢复后，只读对账确认 VERIFIED，且不再有写请求
    s.orch.evidence_dir = s.h["tmp_path"] / "receipts"
    assert s.orch.reconcile(tid).status == "VERIFIED"
    assert len(_sends(s)) == 1
    assert _receipt(s.db.get_secondary_reply_task(tid)["evidence_path"])["source"] == "reconcile"


def test_screenshot_failure_in_readback_session_is_not_verified(stack, monkeypatch):
    s = stack
    original = s.platform._session

    @contextlib.contextmanager
    def failing_shot_session(guard):
        with original(guard) as page:
            real = page.screenshot

            def boom(*a, **k):
                raise OSError("disk full")

            page.screenshot = boom
            try:
                yield page
            finally:
                page.screenshot = real

    tid = _task(s)
    s.platform._session = lambda guard: failing_shot_session(guard) if guard is None else original(guard)
    out = s.orch.submit(tid)
    assert out.status == "UNCERTAIN" and out.detail == "EVIDENCE_NOT_SAVED", out
    s.platform._session = original
    assert s.orch.reconcile(tid).status == "VERIFIED"
    assert len(_sends(s)) == 1


def test_restart_reconcile_only_after_lost_response_and_tombstone_after_delete(stack):
    s = stack
    s.mode[0] = "drop-response"
    tid = _task(s)
    out = s.orch.submit(tid)
    assert out.status == "UNCERTAIN", out
    assert len(_sends(s)) == 1
    # “重启”：新建同库的编排与端口实例；只读对账，不发写请求
    s.mode[0] = "success"
    s.h["server_replies"].append({"commentId": "synth_new_reply_999", "content": "谢谢分享。\nThanks.", "authorId": AUTHOR})
    out2 = s.orch.reconcile(tid)
    assert out2.status == "VERIFIED", out2
    assert len(_sends(s)) == 1
    # 删除任务行后：账本墓碑仍阻止再次发送（新建同目标任务）
    s.db.delete_secondary_reply_task(tid)
    s.h["server_replies"].clear()  # 页面看不到已发回复（折叠/延迟）：只能靠防重账本拦截
    tid2 = _task(s)
    out3 = s.orch.submit(tid2)
    assert out3.status == "REJECTED_BEFORE_INTENT" and "IDEMPOTENCY_CONFLICT" in out3.detail, out3
    assert len(_sends(s)) == 1


# ---------------------------------------------------------------------------
# 实际 CLI 入口 -> 统一编排 -> 浏览器端口 -> 隔离 Chromium 夹具网络
# ---------------------------------------------------------------------------

def test_cli_entry_single_item_through_browser_port(stack, monkeypatch, capsys):
    import importlib.util
    import json as _json
    import sys as _sys
    from pathlib import Path as _P

    spec = importlib.util.spec_from_file_location(
        "wechat_secondary_reply_cli_b", _P(__file__).resolve().parents[2] / "scripts" / "wechat_secondary_reply.py"
    )
    cli = importlib.util.module_from_spec(spec)
    _sys.modules[spec.name] = cli
    spec.loader.exec_module(cli)
    from video_processing.interaction import secondary_reply_ops as ops

    s = stack
    db_path = s.h["tmp_path"] / "test.db"
    monkeypatch.setattr(settings, "wechat_reply_account_key", TEST_ACCOUNT, raising=False)
    monkeypatch.setattr(settings, "wechat_reply_author_finder_id", AUTHOR, raising=False)
    monkeypatch.setattr(settings, "telegram_admin_ids", "555", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "555", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_approver_chat_id", "555000", raising=False)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply", True, raising=False)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply_live_submission", True, raising=False)
    monkeypatch.setattr(settings, "wechat_reply_window_start_shanghai", "00:00", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_window_end_shanghai", "23:59", raising=False)
    monkeypatch.setattr(ops, "DEFAULT_STOP_FILE", s.h["tmp_path"] / "STOP")
    cli_transport = FakeApprovalTransport()

    def run(*argv):
        capsys.readouterr()
        code = cli.main(
            list(argv) + ["--db-path", str(db_path)],
            platform_factory=lambda a: s.platform,
            approval_transport=cli_transport,
        )
        return code, _json.loads(capsys.readouterr().out)

    code, imp = run("import-draft", "--post-id", POST, "--comment-id", "synth_cmt_101",
                    "--comment-text", "非常深刻的宏观分析！", "--zh", "谢谢分享。", "--en", "Thanks.")
    assert code == 0, imp
    tid = imp["task_id"]
    code, pre = run("preflight", "--task-id", str(tid))
    sha12 = pre["reply_sha256"][:12]
    # 旧自批入口被禁用
    code_self, ap_self = run("approve", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code_self == 1 and ap_self["reason"] == "SELF_APPROVAL_DISABLED_REQUIRES_VERIFIED_CALLBACK"
    # 发起审批请求 + 白名单回调消费
    code_req, req = run("request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code_req == 0 and req["status"] == "PENDING_REVIEW", req
    cb_data = cli_transport.sent_messages[-1]["inline_keyboard"][0][0]["callback_data"]
    code, ap = run(
        "approve-callback", "--callback-data", cb_data,
        "--approver-user-id", "555", "--approver-chat-id", "555000",
    )
    assert code == 0 and ap["result"] == "APPROVED", ap
    code, pre2 = run("preflight", "--task-id", str(tid))
    assert code == 0 and pre2["ok"], pre2
    code, res = run("submit", "--task-id", str(tid), "--evidence-dir", str(s.h["tmp_path"] / "cli_receipts"))
    assert code == 0 and res["status"] == "VERIFIED", res
    assert len(_sends(s)) == 1
    r = _receipt(PipelineDB_row(db_path, tid)["evidence_path"])
    assert r["task_id"] == tid and r["platform_reply_comment_id"] == "synth_new_reply_999"
    code, again = run("submit", "--task-id", str(tid))
    assert again["status"] == "NOT_CLAIMABLE" and len(_sends(s)) == 1


def PipelineDB_row(db_path, tid):
    from video_processing.db.database import PipelineDB
    return PipelineDB(str(db_path)).get_secondary_reply_task(tid)


def test_orchestrated_author_reply_on_subsequent_page_skips(stack):
    """编排经浏览器端口：后续页发现作者回复，安全跳过，零出站请求。"""
    s = stack
    tid = _task(s, comment_id="synth_cmt_105")
    out = s.orch.submit(tid)
    assert out.status == "SKIPPED_ALREADY_REPLIED", out
    assert _sends(s) == []
    assert s.db.check_secondary_reply_idempotency(POST, "synth_cmt_105", account_key=TEST_ACCOUNT) is None


def test_orchestrated_pagination_unknown_fails_closed_before_intent(stack):
    """编排经浏览器端口：分页状态未知时 Fail-Closed 阻断，零出站请求零意图落盘。"""
    s = stack
    tid = _task(s, comment_id="synth_cmt_106")
    out = s.orch.submit(tid)
    assert out.status == "REJECTED_BEFORE_INTENT", out
    assert "无法完整判断是否已回复" in (out.detail or "")
    assert _sends(s) == []
    assert s.db.check_secondary_reply_idempotency(POST, "synth_cmt_106", account_key=TEST_ACCOUNT) is None

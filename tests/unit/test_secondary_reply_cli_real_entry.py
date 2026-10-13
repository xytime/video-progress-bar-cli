"""M3 单条真实操作入口（CLI 子命令）经统一编排的集成测试。

使用 ``main(argv, platform_factory=...)`` 注入离线平台替身；入口、预检、本地审批、提交、平台对账、停用均走真实代码路径，
不手写任何成功状态。每个拒绝类断言都有相邻合法对照。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.interaction import secondary_reply_ops as ops
from video_processing.interaction.secondary_reply_fake_platform import FakeSecondaryReplyPlatform

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wechat_secondary_reply.py"
POST = "export/orch"
COMMENT = "cli_c1"
ZH, EN = "谢谢分享。", "Thanks."


@pytest.fixture(scope="module")
def cli():
    spec = importlib.util.spec_from_file_location("wechat_secondary_reply_cli", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(tmp_path, monkeypatch, cli):
    monkeypatch.setattr(settings, "wechat_reply_account_key", "acct_cli", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_author_finder_id", "fake_author_finder@finder", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "777", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_approver_chat_id", "", raising=False)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply", True, raising=False)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply_live_submission", True, raising=False)
    monkeypatch.setattr(settings, "wechat_reply_min_interval_seconds", 0, raising=False)
    monkeypatch.setattr(settings, "wechat_reply_window_start_shanghai", "00:00", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_window_end_shanghai", "23:59", raising=False)
    monkeypatch.setattr(ops, "DEFAULT_STOP_FILE", tmp_path / "STOP")
    db_path = tmp_path / "cli.db"
    platform = FakeSecondaryReplyPlatform(account_finder_id="fake_author_finder@finder")

    def run(capsys, *argv, factory=True):
        capsys.readouterr()
        code = cli.main(list(argv) + ["--db-path", str(db_path)], platform_factory=(lambda a: platform) if factory else None)
        out = capsys.readouterr().out
        return code, (json.loads(out) if out.strip().startswith("{") else out)

    return type("Env", (), {"run": staticmethod(run), "platform": platform, "db_path": db_path, "tmp": tmp_path})


def _import(env, capsys, zh=ZH, en=EN):
    return env.run(capsys, "import-draft", "--post-id", POST, "--comment-id", COMMENT,
                   "--comment-text", "为什么会出现这种情况？", "--zh", zh, "--en", en)


def _approve_flow(env, capsys):
    code, res = _import(env, capsys)
    assert code == 0 and res["ok"], res
    tid = res["task_id"]
    code, pre = env.run(capsys, "preflight", "--task-id", str(tid))
    assert code == 1 and "STATUS_PENDING_REVIEW_NOT_APPROVED" in pre["blockers"]  # 未批准不可发送
    sha12 = pre["reply_sha256"][:12]
    code, bad = env.run(capsys, "approve", "--task-id", str(tid), "--confirm-reply-sha12", "000000000000")
    assert code == 1 and "CONFIRM_HASH_MISMATCH" in bad["reason"]
    code, ok = env.run(capsys, "approve", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 0 and ok["ok"], ok
    return tid


def test_full_single_item_path_through_cli(env, capsys):
    tid = _approve_flow(env, capsys)
    code, pre = env.run(capsys, "preflight", "--task-id", str(tid))
    assert code == 0 and pre["ok"] and pre["account_key"] == "acct_cli" and pre["root_comment_id"] == COMMENT
    assert pre["approval"]["approver_id"] == "777" and pre["approval"]["bound_source_comment_hash"]
    code, res = env.run(capsys, "submit", "--task-id", str(tid))
    assert code == 0 and res["status"] == "VERIFIED", res
    assert len(env.platform.outbound_requests) == 1
    # 重复提交：不得再发
    code, again = env.run(capsys, "submit", "--task-id", str(tid))
    assert code == 1 and again["status"] == "NOT_CLAIMABLE"
    assert len(env.platform.outbound_requests) == 1


def test_submit_refused_when_flags_off_or_stopped_then_legit_after_resume(env, capsys, monkeypatch):
    tid = _approve_flow(env, capsys)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply_live_submission", False, raising=False)
    code, res = env.run(capsys, "submit", "--task-id", str(tid))
    assert code == 1 and "FLAGS_OFF" in res["reason"] and env.platform.outbound_requests == []
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply_live_submission", True, raising=False)
    assert env.run(capsys, "stop")[1]["stopped"] is True
    code, res = env.run(capsys, "submit", "--task-id", str(tid))
    assert code == 1 and res["reason"] == "STOP_FILE_PRESENT" and env.platform.outbound_requests == []
    env.run(capsys, "resume")
    code, res = env.run(capsys, "submit", "--task-id", str(tid))
    assert code == 0 and res["status"] == "VERIFIED"


def test_approve_requires_configured_approver_and_rejects_fixture_provider(env, capsys, monkeypatch):
    code, res = _import(env, capsys)
    tid = res["task_id"]
    sha12 = env.run(capsys, "preflight", "--task-id", str(tid))[1]["reply_sha256"][:12]
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "", raising=False)
    code, res = env.run(capsys, "approve", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 1 and "APPROVER_NOT_CONFIGURED" in res["reason"]
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "777", raising=False)
    assert env.run(capsys, "approve", "--task-id", str(tid), "--confirm-reply-sha12", sha12)[0] == 0

    # fixture provider 草稿不得批准
    db = PipelineDB(str(env.db_path))
    db.save_discovered_audience_comments(POST, [{"comment_id": "fx", "content": "x？"}], account_key="acct_cli")
    fx = db.create_or_update_secondary_reply_task(
        account_key="acct_cli", platform_post_id=POST, comment_id="fx", intent="REPLY", style="MACRO",
        chinese_reply=ZH, english_reply=EN, formatted_reply=f"{ZH}\n{EN}", provider="rule_secondary_provider",
        status="PENDING_REVIEW",
    )
    pre = env.run(capsys, "preflight", "--task-id", str(fx))[1]
    code, res = env.run(capsys, "approve", "--task-id", str(fx), "--confirm-reply-sha12", pre["reply_sha256"][:12])
    assert code == 1 and "FIXTURE_PROVIDER" in res["reason"]


def test_import_rejects_bad_content_and_accepts_good(env, capsys):
    code, res = _import(env, capsys, zh="谢谢分享 😀", en=EN)  # Emoji 违反内容合同
    assert code == 1 and "CONTENT_REJECTED" in res["reason"]
    code, res = _import(env, capsys)
    assert code == 0 and res["ok"]


def test_reconcile_platform_reads_platform_and_never_resends(env, capsys):
    tid = _approve_flow(env, capsys)
    env.platform.mode = "drop-not-persisted"
    code, res = env.run(capsys, "submit", "--task-id", str(tid))
    assert res["status"] == "UNCERTAIN"
    sent = len(env.platform.outbound_requests)
    # 需要显式确认只读访问平台
    code, res = env.run(capsys, "reconcile-platform", "--task-id", str(tid))
    assert code == 1 and "confirm-readonly-platform-access" in res["reason"]
    # 平台上没有：保持 UNCERTAIN
    env.platform.mode = "success"
    code, res = env.run(capsys, "reconcile-platform", "--task-id", str(tid), "--confirm-readonly-platform-access")
    assert res["status"] == "UNCERTAIN" and len(env.platform.outbound_requests) == sent
    # “重启”后 submit 仍不得重发
    assert env.run(capsys, "submit", "--task-id", str(tid))[1]["status"] == "NOT_CLAIMABLE"
    # 平台延迟出现 -> 对账 VERIFIED（读取的是平台状态，不是本地列表）
    row = PipelineDB(str(env.db_path)).get_secondary_reply_task(tid)
    env.platform.seed_author_reply(POST, COMMENT, row["formatted_reply"])
    code, res = env.run(capsys, "reconcile-platform", "--task-id", str(tid), "--confirm-readonly-platform-access")
    assert code == 0 and res["status"] == "VERIFIED" and len(env.platform.outbound_requests) == sent
    status = env.run(capsys, "status")[1]
    assert status["needs_platform_reconcile"] == []


def test_legacy_invocation_without_subcommand_no_longer_exits_3(cli, capsys):
    assert cli.main([]) == 2  # 打印用法，不再是“链路未接线”的 exit 3

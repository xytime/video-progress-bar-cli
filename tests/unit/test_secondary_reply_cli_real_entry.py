"""M3 单条真实操作入口（CLI 子命令）经统一编排的集成测试。

使用 ``main(argv, platform_factory=...)`` 注入离线平台替身；入口、预检、本地审批、提交、平台对账、停用均走真实代码路径，
不手写任何成功状态。每个拒绝类断言都有相邻合法对照。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-17 | Codex | 新增 verify-platform 与 calibrate-dom CLI 子命令参数校验、契约结构与零写验证 (M3) |
| 1.0.0 | 2026-10-13 | Antigravity | 新增：M3 单条真实操作入口 CLI 集成测试 |
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


def test_verify_platform_cli_missing_args_and_config(env, capsys, monkeypatch):
    # 1. 缺失 post-id / comment-id
    code, res = env.run(capsys, "verify-platform")
    assert code == 2
    assert "MISSING_ARGS" in res.get("reason", "")
    assert "post-id" in res.get("args", [])

    # 2. 缺失 account_key
    monkeypatch.setattr(settings, "wechat_reply_account_key", "", raising=False)
    code, res = env.run(capsys, "verify-platform", "--post-id", POST, "--comment-id", COMMENT)
    assert code == 2
    assert res.get("reason") == "ACCOUNT_KEY_NOT_CONFIGURED"

    # 3. 缺失 author_finder_id
    monkeypatch.setattr(settings, "wechat_reply_account_key", "acct_cli", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_author_finder_id", "", raising=False)
    code, res = env.run(capsys, "verify-platform", "--post-id", POST, "--comment-id", COMMENT)
    assert code in (1, 2)
    assert "AUTHOR_FINDER_ID_NOT_CONFIGURED" in res.get("reason", "")


def test_verify_platform_cli_unsupported_platform(env, capsys):
    # env.platform 为 FakeSecondaryReplyPlatform，未实现 calibrate_and_verify
    code, res = env.run(capsys, "verify-platform", "--post-id", POST, "--comment-id", COMMENT)
    assert code == 1
    assert res["ok"] is False
    assert res["reason"] == "PLATFORM_DOES_NOT_SUPPORT_CALIBRATION"


def test_verify_platform_and_calibrate_dom_success_contract(env, capsys, cli):
    captured_calls = []

    class MockCalibratingPlatform:
        def __init__(self, account_finder_id):
            self.account_finder_id = account_finder_id

        def calibrate_and_verify(self, *, post_id, root_id, video_title=None, comment_text=None, evidence_dir=None):
            captured_calls.append({
                "post_id": post_id,
                "root_id": root_id,
                "video_title": video_title,
                "comment_text": comment_text,
                "evidence_dir": evidence_dir,
            })
            return {
                "ok": True,
                "status": "NOT_REPLIED",
                "channel_profile": {
                    "account_key": "acct_cli",
                    "finder_id": self.account_finder_id,
                    "native_username": self.account_finder_id,
                    "channel_nickname": "六维时空号",
                    "identity_verified": True,
                },
                "target": {
                    "post_id": post_id,
                    "comment_id": root_id,
                    "video_title": video_title or "",
                    "author_nickname": "隽永",
                    "comment_text": comment_text or "",
                    "text_matched": True,
                    "fresh": True,
                },
                "controls_calibration": {
                    "reply_icon": {
                        "selector": ".action-icon.weui-icon-outlined-comment",
                        "found": True,
                        "count": 1,
                        "visible": True,
                        "enabled": True,
                    },
                    "editor_textarea": {
                        "selector": "textarea[placeholder*='回复'], textarea[data-comment-editor], textarea.weui-desktop-form__textarea",
                        "found": True,
                        "count": 1,
                        "visible": True,
                        "editable": True,
                        "is_empty": True,
                    },
                    "submit_button": {
                        "selector": ".create-ft .tag-wrap.primary, .weui-desktop-btn_primary:text-is('评论')",
                        "found": True,
                        "count": 1,
                        "visible": True,
                        "enabled_when_filled": True,
                        "disabled_when_empty": True,
                    },
                    "expand_button": {
                        "selector": None,
                        "found": False,
                        "count": 0,
                        "visible": False,
                        "text": None,
                    },
                },
                "evidence_files": {
                    "json": str(evidence_dir / "platform_verification.json") if evidence_dir else "/tmp/v.json",
                    "screenshot": str(evidence_dir / "controls.png") if evidence_dir else "/tmp/v.png",
                },
                "mode": "PLATFORM_READ_ONLY_CALIBRATION_AND_VERIFICATION",
            }

    mock_platform = MockCalibratingPlatform("fake_author_finder@finder")

    # 1. 直接传参调用 verify-platform
    capsys.readouterr()
    code = cli.main(
        [
            "verify-platform",
            "--db-path", str(env.db_path),
            "--post-id", POST,
            "--comment-id", COMMENT,
            "--video-title", "面对癌症，财富究竟能带来什么？",
            "--comment-text", "测试评论原文",
        ],
        platform_factory=lambda a: mock_platform,
    )
    out = capsys.readouterr().out
    res = json.loads(out)
    assert code == 0
    assert res["ok"] is True
    assert res["status"] == "NOT_REPLIED"
    assert res["channel_profile"]["identity_verified"] is True
    assert res["channel_profile"]["account_key"] == "acct_cli"
    assert res["channel_profile"]["finder_id"] == "fake_author_finder@finder"
    assert res["target"]["post_id"] == POST
    assert res["target"]["comment_id"] == COMMENT
    assert res["target"]["text_matched"] is True
    assert res["target"]["fresh"] is True
    calib = res["controls_calibration"]
    assert calib["reply_icon"]["selector"] == ".action-icon.weui-icon-outlined-comment"
    assert calib["reply_icon"]["found"] is True
    assert calib["editor_textarea"]["found"] is True
    assert calib["submit_button"]["found"] is True
    assert calib["submit_button"]["enabled_when_filled"] is True
    assert res["mode"] == "PLATFORM_READ_ONLY_CALIBRATION_AND_VERIFICATION"

    # 2. calibrate-dom 别名行为一致
    capsys.readouterr()
    code_alias = cli.main(
        [
            "calibrate-dom",
            "--db-path", str(env.db_path),
            "--post-id", POST,
            "--comment-id", COMMENT,
        ],
        platform_factory=lambda a: mock_platform,
    )
    out_alias = capsys.readouterr().out
    res_alias = json.loads(out_alias)
    assert code_alias == 0
    assert res_alias["ok"] is True
    assert res_alias["status"] == "NOT_REPLIED"

    # 3. 通过 task-id 解析目标作品与评论
    tid = _approve_flow(env, capsys)
    capsys.readouterr()
    code_task = cli.main(
        [
            "verify-platform",
            "--db-path", str(env.db_path),
            "--task-id", str(tid),
        ],
        platform_factory=lambda a: mock_platform,
    )
    out_task = capsys.readouterr().out
    res_task = json.loads(out_task)
    assert code_task == 0
    assert res_task["ok"] is True
    assert res_task["target"]["post_id"] == POST
    assert res_task["target"]["comment_id"] == COMMENT


def test_verify_platform_zero_write_guarantee_even_with_flags_on(env, capsys, cli, monkeypatch):
    # 即使开启所有实时发评开关，verify-platform 绝不出站发评
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply", True, raising=False)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply_live_submission", True, raising=False)

    outbound = []
    class SafePlatform:
        def calibrate_and_verify(self, **kwargs):
            return {
                "ok": True,
                "status": "NOT_REPLIED",
                "channel_profile": {"account_key": "acct_cli", "finder_id": "fake_author_finder@finder"},
                "target": {"post_id": POST, "comment_id": COMMENT, "fresh": True},
                "controls_calibration": {},
            }
        def send_reply(self, **kwargs):
            outbound.append(kwargs)
            raise RuntimeError("CRITICAL: verify-platform invoked send_reply!")

    capsys.readouterr()
    code = cli.main(
        [
            "verify-platform",
            "--db-path", str(env.db_path),
            "--post-id", POST,
            "--comment-id", COMMENT,
        ],
        platform_factory=lambda a: SafePlatform(),
    )
    out = capsys.readouterr().out
    res = json.loads(out)
    assert code == 0
    assert res["ok"] is True
    assert len(outbound) == 0


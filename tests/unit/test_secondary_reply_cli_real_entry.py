"""M3 单条真实操作入口（CLI 子命令）经统一编排的集成测试。

使用 ``main(argv, platform_factory=..., approval_transport=...)`` 注入离线平台替身与受控审批通道；
入口、预检、正文哈希确认与发起审批（request-approval）、可验证回调批准（approve-callback）、
旧自批拒绝（approve）、提交、平台对账、停用及平台只读核验均走真实代码路径，不手写任何成功状态。
每个拒绝类断言都有相邻合法对照。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-17 | Antigravity | 覆盖 request-approval/approve-callback 审批边界、自批禁用及 verify_platform 强类型缺失证据降级回归 |
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
from video_processing.interaction.secondary_reply_approval import FakeApprovalTransport
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
    monkeypatch.setattr(settings, "telegram_admin_ids", "777", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "777", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_approver_chat_id", "777000", raising=False)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply", True, raising=False)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply_live_submission", True, raising=False)
    monkeypatch.setattr(settings, "wechat_reply_min_interval_seconds", 0, raising=False)
    monkeypatch.setattr(settings, "wechat_reply_window_start_shanghai", "00:00", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_window_end_shanghai", "23:59", raising=False)
    monkeypatch.setattr(ops, "DEFAULT_STOP_FILE", tmp_path / "STOP")
    db_path = tmp_path / "cli.db"
    platform = FakeSecondaryReplyPlatform(account_finder_id="fake_author_finder@finder")
    transport = FakeApprovalTransport()

    def run(capsys, *argv, factory=True, with_transport=True):
        capsys.readouterr()
        code = cli.main(
            list(argv) + ["--db-path", str(db_path)],
            platform_factory=(lambda a: platform) if factory else None,
            approval_transport=transport if with_transport else None,
        )
        out = capsys.readouterr().out
        return code, (json.loads(out) if out.strip().startswith("{") else out)

    return type(
        "Env",
        (),
        {
            "run": staticmethod(run),
            "platform": platform,
            "transport": transport,
            "db_path": db_path,
            "tmp": tmp_path,
        },
    )


def _import(env, capsys, zh=ZH, en=EN):
    return env.run(
        capsys,
        "import-draft",
        "--post-id",
        POST,
        "--comment-id",
        COMMENT,
        "--comment-text",
        "为什么会出现这种情况？",
        "--zh",
        zh,
        "--en",
        en,
    )


def _approve_flow(env, capsys):
    code, res = _import(env, capsys)
    assert code == 0 and res["ok"], res
    tid = res["task_id"]
    code, pre = env.run(capsys, "preflight", "--task-id", str(tid))
    assert code == 1 and "STATUS_PENDING_REVIEW_NOT_APPROVED" in pre["blockers"]  # 未批准不可发送
    sha12 = pre["reply_sha256"][:12]

    # 1. 旧式本地自批入口已被硬禁用并给出迁移说明，任务保持 PENDING_REVIEW
    code, self_app = env.run(capsys, "approve", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 1 and self_app["reason"] == "SELF_APPROVAL_DISABLED_REQUIRES_VERIFIED_CALLBACK"
    assert "request-approval" in self_app["migration"] and "approve-callback" in self_app["migration"]

    # 2. 正文哈希错误时拒绝发起审批请求
    code, bad = env.run(capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", "000000000000")
    assert code == 1 and "CONFIRM_HASH_MISMATCH" in bad["reason"]

    # 3. 未接通外部可验证审批传输通道时，保持 PENDING_REVIEW 且发送不可用
    code, no_trans = env.run(
        capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12, with_transport=False
    )
    assert code == 1 and no_trans["reason"] == "APPROVAL_TRANSPORT_UNAVAILABLE"
    assert no_trans["status"] == "PENDING_REVIEW" and no_trans["hash_confirmed"] is True

    # 4. 接通审批传输通道后发起审批请求：仅绑定 token 并发送卡片，任务仍为 PENDING_REVIEW（尚未获批）
    code, req_ok = env.run(capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 0 and req_ok["ok"] is True and req_ok["status"] == "PENDING_REVIEW"
    assert env.run(capsys, "preflight", "--task-id", str(tid))[0] == 1

    # 5. 白名单审批人通过可验证回调入口消费一次性 token，任务正式转为 APPROVED
    callback_data = env.transport.sent_messages[-1]["inline_keyboard"][0][0]["callback_data"]
    code, cb_ok = env.run(
        capsys,
        "approve-callback",
        "--callback-data",
        callback_data,
        "--approver-user-id",
        "777",
        "--approver-chat-id",
        "777000",
    )
    assert code == 0 and cb_ok["ok"] is True and cb_ok["result"] == "APPROVED", cb_ok
    return tid


def test_full_single_item_path_through_cli(env, capsys):
    tid = _approve_flow(env, capsys)
    code, pre = env.run(capsys, "preflight", "--task-id", str(tid))
    assert code == 0 and pre["ok"] and pre["account_key"] == "acct_cli" and pre["root_comment_id"] == COMMENT
    assert pre["approval"]["approver_id"] == "777" and pre["approval"]["approver_chat_id"] == "777000"
    assert pre["approval"]["bound_source_comment_hash"]
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

    # 1. 未配置审批人 ID -> 拒绝
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "", raising=False)
    code, res = env.run(capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 1 and "APPROVER_NOT_CONFIGURED" in res["reason"]

    # 2. 使用 local_operator 占位符 -> 拒绝
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "local_operator", raising=False)
    code, res = env.run(capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 1 and "LOCAL_OPERATOR_SELF_APPROVAL_FORBIDDEN" in res["reason"]

    # 3. 审批人不在 telegram_admin_ids 白名单内 -> 拒绝
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "999", raising=False)
    code, res = env.run(capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 1 and "APPROVER_NOT_IN_ADMIN_WHITELIST" in res["reason"]

    # 4. 未配置真实 chat_id 或使用 local-cli: 前缀 -> 拒绝
    monkeypatch.setattr(settings, "wechat_reply_approver_telegram_id", "777", raising=False)
    monkeypatch.setattr(settings, "wechat_reply_approver_chat_id", "", raising=False)
    code, res = env.run(capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 1 and "APPROVER_CHAT_ID_NOT_CONFIGURED" in res["reason"]

    monkeypatch.setattr(settings, "wechat_reply_approver_chat_id", "local-cli:777", raising=False)
    code, res = env.run(capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12)
    assert code == 1 and "LOCAL_CLI_CHAT_ID_FORBIDDEN" in res["reason"]

    # 5. 恢复合法白名单配置后可正常发起审批请求
    monkeypatch.setattr(settings, "wechat_reply_approver_chat_id", "777000", raising=False)
    assert env.run(capsys, "request-approval", "--task-id", str(tid), "--confirm-reply-sha12", sha12)[0] == 0

    # 6. fixture provider 草稿不得发起审批或自批
    db = PipelineDB(str(env.db_path))
    db.save_discovered_audience_comments(POST, [{"comment_id": "fx", "content": "x？"}], account_key="acct_cli")
    fx = db.create_or_update_secondary_reply_task(
        account_key="acct_cli",
        platform_post_id=POST,
        comment_id="fx",
        intent="REPLY",
        style="MACRO",
        chinese_reply=ZH,
        english_reply=EN,
        formatted_reply=f"{ZH}\n{EN}",
        provider="rule_secondary_provider",
        status="PENDING_REVIEW",
    )
    pre = env.run(capsys, "preflight", "--task-id", str(fx))[1]
    code, res = env.run(
        capsys, "request-approval", "--task-id", str(fx), "--confirm-reply-sha12", pre["reply_sha256"][:12]
    )
    assert code == 1 and "FIXTURE_PROVIDER" in res["reason"]


def test_approval_callback_rejects_replay_expiry_tamper_and_wrong_sender(env, capsys):
    tid = _approve_flow(env, capsys)
    callback_data = env.transport.sent_messages[-1]["inline_keyboard"][0][0]["callback_data"]

    # 1. 同一审批回调重复消费 -> 被拒绝
    code, replay = env.run(
        capsys,
        "approve-callback",
        "--callback-data",
        callback_data,
        "--approver-user-id",
        "777",
        "--approver-chat-id",
        "777000",
    )
    assert code == 1 and replay["ok"] is False

    # 2. 非绑定审批人或错误 chat_id 回调 -> 拒绝
    code, wrong_sender = env.run(
        capsys,
        "approve-callback",
        "--callback-data",
        callback_data,
        "--approver-user-id",
        "888",
        "--approver-chat-id",
        "777000",
    )
    assert code == 1 and "CALLBACK_SENDER_MISMATCH" in wrong_sender["reason"]

    # 3. 获批后若草稿正文被重新导入修改 -> 旧批准立即失效，回归 PENDING_REVIEW 且无法提交
    code, updated = _import(env, capsys, zh="修改后的回复。", en="Updated reply.")
    assert code == 0 and updated["task_id"] == tid
    code, pre_after_edit = env.run(capsys, "preflight", "--task-id", str(tid))
    assert code == 1 and "STATUS_PENDING_REVIEW_NOT_APPROVED" in pre_after_edit["blockers"]
    code, sub_after_edit = env.run(capsys, "submit", "--task-id", str(tid))
    assert code == 1 and sub_after_edit["status"] == "NOT_CLAIMABLE"


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
                "completeness": "COMPLETE",
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
                    "comment_text": comment_text or "观测到的真实评论原文",
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
    assert res["completeness"] == "COMPLETE"
    assert res["channel_profile"]["identity_verified"] is True
    assert res["channel_profile"]["account_key"] == "acct_cli"
    assert res["channel_profile"]["finder_id"] == "fake_author_finder@finder"
    assert res["channel_profile"]["observed_native_username"] == "fake_author_finder@finder"
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


def test_verify_platform_rejects_missing_or_conflicting_evidence_and_preserves_replied_rules(env, capsys):
    """验证缺失身份/原文/分页证据绝不默认通过，且保留 REPLIED 与 NOT_REPLIED 的不同证据条件。"""
    payload_box = [{}]

    class CustomPlatform:
        def calibrate_and_verify(self, **kwargs):
            return payload_box[0]

    def verify_with(raw_payload, comment_text="预期原文"):
        payload_box[0] = raw_payload
        return ops.verify_platform(
            None,
            post_id=POST,
            comment_id=COMMENT,
            platform=CustomPlatform(),
            account_key="acct_cli",
            finder_id="fake_author_finder@finder",
            comment_text=comment_text,
            evidence_dir=env.tmp / "verify_ev",
        )

    # 1. REPLIED 合法样本：有实测身份、正文匹配与非错误 completeness，不强求未回复的控件展开校准 -> ok=True
    replied_ok = verify_with({
        "ok": True,
        "status": "REPLIED",
        "completeness": "OBSERVED_IN_PREVIEW",
        "channel_profile": {
            "native_username": "fake_author_finder@finder",
            "identity_verified": True,
        },
        "target": {
            "post_id": POST,
            "comment_id": COMMENT,
            "comment_text": "预期原文",
            "text_matched": True,
            "fresh": True,
        },
        "controls_calibration": {},
    })
    assert replied_ok["ok"] is True and replied_ok["status"] == "REPLIED"

    # 2. 缺失 native_username（企图靠配置 finder_id 冒充）且缺省 identity_verified -> 必须降级为 UNKNOWN (ok=False)
    missing_identity = verify_with({
        "ok": True,
        "status": "REPLIED",
        "completeness": "COMPLETE",
        "channel_profile": {"finder_id": "fake_author_finder@finder"},
        "target": {
            "post_id": POST,
            "comment_id": COMMENT,
            "comment_text": "预期原文",
            "text_matched": True,
            "fresh": True,
        },
    })
    assert missing_identity["ok"] is False
    assert missing_identity["status"] == "UNKNOWN"
    assert missing_identity["channel_profile"]["native_username"] == ""
    assert missing_identity["channel_profile"]["identity_verified"] is False

    # 3. 缺失 text_matched（不能默认 True）或原文不一致 -> 必须降级为 UNKNOWN (ok=False)
    missing_text = verify_with({
        "ok": True,
        "status": "REPLIED",
        "completeness": "COMPLETE",
        "channel_profile": {
            "native_username": "fake_author_finder@finder",
            "identity_verified": True,
        },
        "target": {
            "post_id": POST,
            "comment_id": COMMENT,
            "comment_text": "预期原文",
            "fresh": True,
        },
    })
    assert missing_text["ok"] is False
    assert missing_text["status"] == "UNKNOWN"
    assert missing_text["target"]["text_matched"] is False

    # 4. NOT_REPLIED 样本缺少 COMPLETE 分页或缺少三大控件唯一就绪证据 -> 必须降级为 UNKNOWN (ok=False)
    incomplete_unreplied = verify_with({
        "ok": True,
        "status": "NOT_REPLIED",
        "completeness": "PAGINATION_INCOMPLETE",
        "channel_profile": {
            "native_username": "fake_author_finder@finder",
            "identity_verified": True,
        },
        "target": {
            "post_id": POST,
            "comment_id": COMMENT,
            "comment_text": "预期原文",
            "text_matched": True,
            "fresh": True,
        },
        "controls_calibration": {},
    })
    assert incomplete_unreplied["ok"] is False
    assert incomplete_unreplied["status"] == "UNKNOWN"


def test_verify_platform_zero_write_guarantee_even_with_flags_on(env, capsys, cli, monkeypatch):
    # 即使开启所有实时发评开关，verify-platform 绝不出站发评；且缺证据时必须 Fail-Closed
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply", True, raising=False)
    monkeypatch.setattr(settings, "enable_wechat_secondary_reply_live_submission", True, raising=False)

    outbound = []

    class SafePlatform:
        def calibrate_and_verify(self, **kwargs):
            return {
                "ok": True,
                "status": "NOT_REPLIED",
                "completeness": "COMPLETE",
                "channel_profile": {
                    "account_key": "acct_cli",
                    "finder_id": "fake_author_finder@finder",
                    "native_username": "fake_author_finder@finder",
                    "identity_verified": True,
                },
                "target": {
                    "post_id": POST,
                    "comment_id": COMMENT,
                    "comment_text": "观测到的原始评论",
                    "text_matched": True,
                    "fresh": True,
                },
                "controls_calibration": {
                    "reply_icon": {"selector": ".action-icon.weui-icon-outlined-comment", "found": True, "count": 1, "visible": True, "enabled": True},
                    "editor_textarea": {"selector": ".edit-area[contenteditable='true']", "found": True, "count": 1, "visible": True, "editable": True, "is_empty": True},
                    "submit_button": {"selector": ".weui-desktop-btn_primary:text-is('评论')", "found": True, "count": 1, "visible": True, "disabled_when_empty": True, "enabled_when_filled": True},
                },
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



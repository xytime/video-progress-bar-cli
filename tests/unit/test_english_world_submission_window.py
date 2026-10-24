"""英语世界专用投稿的公共窗口与两小时人工 capability 测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| operations-v1 | 2026-10-24 | Codex | 测试独立账户状态，防止旧测试间预算/损坏状态串扰；生产准入不豁免。 |
| 1.6.0 | 2026-10-24 | Codex | 验证完整账户身份在领取前准入，旧窗口让出健康就绪执行者并保留故障兜底。 |
| 1.5.0 | 2026-09-18 | Antigravity | 自动授权延后窗口改用 is_english_world_publish_window 判定。 |
| 1.0.0 | 2026-08-29 | Codex | 固化自动授权窗口外延后，人工两小时授权可单项绕过。 |
| 1.1.0 | 2026-08-30 | Codex | 固化延后必须返回独立状态码，避免退出码 0 伪装成投稿成功。 |
| 1.2.0 | 2026-08-30 | Codex | 固化具名操作员补发 capability 与人工授权使用相同的两小时边界。 |
| 1.3.0 | 2026-08-30 | Codex | 固化仅接受同次唯一原生 ID 差分回执，拒绝模糊或未绑定身份。 |
| 1.4.0 | 2026-08-31 | Codex | 固化全局微信锁忙时不得领取审核项，保持批准态等待下一轮调度。 |
"""

from datetime import datetime, timedelta, timezone
import json

from scripts import submit_english_world_review as submitter

import pytest

@pytest.fixture(autouse=True)
def isolated_account_output(tmp_path, monkeypatch):
    # 两个旧假 DB 测试同样必须拥有独立账号账本，不能受其他测试的准入记录影响。
    monkeypatch.setattr(type(submitter.settings), "default_output_dir", property(lambda _self: tmp_path / "output"))



def test_automatic_submit_supplies_exact_frozen_mp4_to_full_account_admission(tmp_path, monkeypatch):
    from video_processing.core.wechat_request_guard import WeChatRequestGuard
    calls=[]
    class DB:
        def get_english_world_review_item(self, review_id):
            return {'id':review_id,'state':'SUBMISSION_APPROVED','approval_source':'AUTO_POLICY','mp4_path':'/package/one/english_world.mp4'}
        def claim_english_world_submission(self,*a,**k):
            raise AssertionError('quota denial must precede any claim')
    def denied(self,**kwargs):
        calls.append(kwargs)
        return {'allowed':False,'blockers':[{'code':'QUOTA_24H'}]}
    monkeypatch.setattr(submitter,'PipelineDB',DB)
    monkeypatch.setattr(WeChatRequestGuard,'evaluate',denied)
    monkeypatch.setattr(type(submitter.settings),'is_english_world_publish_window',lambda _:True)
    assert submitter.submit('a'*32)==submitter.EXIT_DEFERRED
    assert calls==[{'task':'/package/one/english_world.mp4'}]


def test_legacy_window_quota_denial_never_opens_database_or_launches_worker(monkeypatch):
    from scripts import run_publication_window as window
    from video_processing.core.wechat_request_guard import WeChatRequestGuard
    monkeypatch.setattr(window.settings,'enable_english_world_auto_publish',True)
    monkeypatch.setattr(window.settings,'wechat_publishing_paused',False)
    monkeypatch.setattr(type(window.settings),'is_english_world_publish_window',lambda _:True)
    monkeypatch.setattr(WeChatRequestGuard,'evaluate',lambda *a,**k:{'allowed':False})
    monkeypatch.setattr(window,'PipelineDB',lambda:(_ for _ in ()).throw(AssertionError('must not touch DB while quota-blocked')))
    assert window.dispatch_one_deferred_english_world_submission() is None


def test_legacy_window_fallback_requires_missing_or_unhealthy_real_worker(tmp_path):
    import os
    from scripts.run_publication_window import _ready_worker_available
    from video_processing.core.task_lease import TaskLease
    status=tmp_path/'ready_publications_status.json'
    status.write_text(json.dumps({'pid':os.getpid(),'heartbeat_at':100,'stage':'IDLE'}))
    assert not _ready_worker_available(tmp_path,now=110)
    with TaskLease(tmp_path/'ready_publications.lock'):
        assert _ready_worker_available(tmp_path,now=110)
        assert not _ready_worker_available(tmp_path,now=161)
        status.write_text(json.dumps({'pid':os.getpid(),'heartbeat_at':100,'stage':'ERROR'}))
        assert not _ready_worker_available(tmp_path,now=110)


def test_manual_capability_is_active_only_before_utc_expiry():
    active = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    assert submitter._manual_authorization_active({
        "approval_source": "TELEGRAM_REVIEW", "authorization_expires_at": active,
    })
    assert not submitter._manual_authorization_active({
        "approval_source": "TELEGRAM_REVIEW", "authorization_expires_at": expired,
    })
    assert not submitter._manual_authorization_active({
        "approval_source": "AUTO_POLICY", "authorization_expires_at": active,
    })
    assert submitter._manual_authorization_active({
        "approval_source": "OPERATOR_RECOVERY", "authorization_expires_at": active,
    })


def test_auto_policy_submission_is_deferred_outside_public_window(monkeypatch):
    calls: list[object] = []

    class FakeDB:
        def get_english_world_review_item(self, review_id):
            calls.append(("get", review_id))
            return {"id": review_id, "approval_source": "AUTO_POLICY", "state": "SUBMISSION_APPROVED"}

        def expire_english_world_submission_authorization(self, review_id):
            calls.append(("expire", review_id))
            return None

        def claim_english_world_submission(self, _review_id):
            raise AssertionError("window outside must not claim or upload")

    monkeypatch.setattr(submitter, "PipelineDB", FakeDB)
    monkeypatch.setattr(submitter.settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(type(submitter.settings), "is_english_world_publish_window", lambda _self: False)

    assert submitter.submit("a" * 32) == submitter.EXIT_DEFERRED
    assert calls == [("get", "a" * 32), ("expire", "a" * 32)]


def test_submission_defers_without_claiming_when_pipeline_lock_is_busy(monkeypatch, tmp_path):
    calls: list[object] = []

    class FakeDB:
        def get_english_world_review_item(self, review_id):
            calls.append(("get", review_id))
            return {
                "id": review_id,
                "approval_source": "AUTO_POLICY",
                "state": "SUBMISSION_APPROVED",
                "mp4_path": str(tmp_path / "study-card.mp4"),
            }

        def claim_english_world_submission(self, *_args, **_kwargs):
            raise AssertionError("busy pipeline lock must not claim or upload")

    monkeypatch.setattr(submitter, "PipelineDB", FakeDB)
    monkeypatch.setattr(submitter, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter.settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(type(submitter.settings), "is_english_world_publish_window", lambda _self: True)
    lock_path = tmp_path / "output" / "wechat_publish_priority.lock"
    lock_path.parent.mkdir(parents=True)
    with lock_path.open("a+") as held:
        submitter.fcntl.flock(held, submitter.fcntl.LOCK_EX | submitter.fcntl.LOCK_NB)
        assert submitter.submit("b" * 32) == submitter.EXIT_DEFERRED
    assert calls == [("get", "b" * 32)]


def test_submission_identity_requires_same_session_unique_native_id_delta(tmp_path):
    receipt = tmp_path / "submission_receipt.json"
    receipt.write_text(json.dumps({
        "matched_by": "same_session_before_after_unique_post_list_object_id_delta",
        "platform_post_id": "export/native-id",
        "platform_url": "https://channels.weixin.qq.com/platform/post/list",
    }), encoding="utf-8")

    assert submitter._read_submission_identity(tmp_path) == (
        "export/native-id", "https://channels.weixin.qq.com/platform/post/list",
    )

    receipt.write_text(json.dumps({
        "matched_by": "same_session_before_after_unique_post_list_object_id_delta_and_exact_description",
        "platform_post_id": "export/native-id",
    }), encoding="utf-8")
    assert submitter._read_submission_identity(tmp_path) == ("export/native-id", None)

    receipt.write_text(json.dumps({
        "matched_by": "title_guess", "platform_post_id": "export/wrong",
    }), encoding="utf-8")
    assert submitter._read_submission_identity(tmp_path) == (None, None)


def test_submission_registers_wechat_publication_on_under_review(monkeypatch, tmp_path):
    recorded_calls = []

    class FakeDB:
        def get_english_world_review_item(self, review_id):
            return {
                "id": review_id,
                "approval_source": "TELEGRAM_REVIEW",
                "state": "SUBMISSION_APPROVED",
                "mp4_path": str(tmp_path / "study.mp4"),
            }

        def claim_english_world_submission(self, review_id, **_kwargs):
            return {
                "id": review_id,
                "_attempt_id": "att_1",
                "mp4_path": str(tmp_path / "study.mp4"),
            }

        def complete_english_world_submission(self, *args, **kwargs):
            recorded_calls.append(("complete", kwargs))

        def ensure_english_world_wechat_publication(self, review_id, **kwargs):
            recorded_calls.append(("ensure_pub", review_id, kwargs))

    monkeypatch.setattr(submitter, "PipelineDB", FakeDB)
    monkeypatch.setattr(submitter, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter, "_manual_authorization_active", lambda _p: True)
    monkeypatch.setattr(submitter, "_require_publish_package", lambda _p: True)
    # 本用例隔离中心账本回写；商品实际 DAL/清单联调由 product_production 测试覆盖。
    monkeypatch.setattr(submitter, "_product_task_decision", lambda _db, _p: None)
    monkeypatch.setattr(submitter, "_english_world_uploader_command", lambda _i, _e, **_kw: ["true"])
    monkeypatch.setattr(submitter, "_original_declaration_receipt_is_confirmed", lambda _d, **_kw: True)
    monkeypatch.setattr(
        submitter, "_read_submission_identity", lambda _d: ("export/native_123", "https://channels.weixin.qq.com")
    )
    monkeypatch.setattr(submitter.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stderr": ""})())
    monkeypatch.setattr(submitter.fcntl, "flock", lambda *_args: None)

    exit_code = submitter.submit("rev_contract_1")
    assert exit_code == 0

    ensure_pub_calls = [c for c in recorded_calls if c[0] == "ensure_pub"]
    assert len(ensure_pub_calls) == 1
    assert ensure_pub_calls[0][1] == "rev_contract_1"
    assert ensure_pub_calls[0][2]["platform_post_id"] == "export/native_123"
    assert ensure_pub_calls[0][2]["state"] == "SUBMITTED_BOUND"


def test_submission_wechat_publication_error_does_not_corrupt_submission_attempt(monkeypatch, tmp_path):
    recorded_calls = []

    class FakeDB:
        def get_english_world_review_item(self, review_id):
            return {
                "id": review_id,
                "approval_source": "TELEGRAM_REVIEW",
                "state": "SUBMISSION_APPROVED",
                "mp4_path": str(tmp_path / "study.mp4"),
            }

        def claim_english_world_submission(self, review_id, **_kwargs):
            return {
                "id": review_id,
                "_attempt_id": "att_2",
                "mp4_path": str(tmp_path / "study.mp4"),
            }

        def complete_english_world_submission(self, *args, **kwargs):
            recorded_calls.append(("complete", kwargs["state"]))

        def ensure_english_world_wechat_publication(self, _review_id, **_kwargs):
            raise RuntimeError("Database locked during publication registration")

    monkeypatch.setattr(submitter, "PipelineDB", FakeDB)
    monkeypatch.setattr(submitter, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter, "_manual_authorization_active", lambda _p: True)
    monkeypatch.setattr(submitter, "_require_publish_package", lambda _p: True)
    monkeypatch.setattr(submitter, "_product_task_decision", lambda _db, _p: None)
    monkeypatch.setattr(submitter, "_english_world_uploader_command", lambda _i, _e, **_kw: ["true"])
    monkeypatch.setattr(submitter, "_original_declaration_receipt_is_confirmed", lambda _d, **_kw: True)
    monkeypatch.setattr(
        submitter, "_read_submission_identity", lambda _d: ("export/native_456", "https://channels.weixin.qq.com")
    )
    monkeypatch.setattr(submitter.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stderr": ""})())
    monkeypatch.setattr(submitter.fcntl, "flock", lambda *_args: None)

    exit_code = submitter.submit("rev_contract_2")
    assert exit_code == 0
    # complete_english_world_submission 只允许调用一次且状态必须为 UNDER_REVIEW，绝不可再调用 FAILED
    assert recorded_calls == [("complete", "UNDER_REVIEW")]

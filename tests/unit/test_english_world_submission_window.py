"""英语世界专用投稿的公共窗口与两小时人工 capability 测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-29 | Codex | 固化自动授权窗口外延后，人工两小时授权可单项绕过。 |
| 1.1.0 | 2026-08-30 | Codex | 固化延后必须返回独立状态码，避免退出码 0 伪装成投稿成功。 |
"""

from datetime import datetime, timedelta, timezone

from scripts import submit_english_world_review as submitter


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
    monkeypatch.setattr(type(submitter.settings), "is_public_publish_window", lambda _self: False)

    assert submitter.submit("a" * 32) == submitter.EXIT_DEFERRED
    assert calls == [("get", "a" * 32), ("expire", "a" * 32)]

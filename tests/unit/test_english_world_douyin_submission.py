"""英语世界独立抖音同步执行器测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 覆盖保守退出码映射与 UI 失败熔断必须在建账/开浏览器前停止。 |
"""

from scripts import submit_english_world_douyin as submitter


def test_douyin_exit_codes_never_call_acceptance_published():
    assert submitter._completion_for_exit_code(6)[0] == "UNDER_REVIEW"
    assert submitter._completion_for_exit_code(7)[0] == "UNCERTAIN"
    assert submitter._completion_for_exit_code(3)[0] == "CANCELED"
    assert submitter._completion_for_exit_code(4)[0] == "CANCELED"
    assert submitter._completion_for_exit_code(2)[0] == "LOGIN_REQUIRED"


def test_active_ui_fuse_stops_before_douyin_ledger_or_browser(monkeypatch):
    class FakeDB:
        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return [{"stage": "publish_pre_submit", "active": 1, "consecutive_failures": 2}]

        def ensure_english_world_douyin_publication(self, _review_id):
            raise AssertionError("active UI fuse must stop before creating or reading a publication")

    monkeypatch.setattr(submitter, "PipelineDB", FakeDB)
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)

    assert submitter.submit("a" * 32) == 4

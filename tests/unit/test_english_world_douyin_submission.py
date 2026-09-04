"""英语世界独立抖音同步执行器测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 覆盖保守退出码映射与 UI 失败熔断必须在建账/开浏览器前停止。 |
| 1.1.0 | 2026-09-02 | Codex | 覆盖未知 UI 阶段 fail-closed，且管理页熔断不阻断独立新片投稿。 |
| 1.2.0 | 2026-09-02 | Codex | 覆盖英语世界独立投稿携带一次性浏览器启动凭据，拒绝再以 source_kind 文本授权。 |
| 1.3.0 | 2026-09-02 | Codex | 覆盖包校验、子进程退出或超时在浏览器启动前以未启动票据收口为可显式恢复的取消账本。 |
| 1.4.1 | 2026-09-04 | Codex | 覆盖双封面、原创声明和快速检测均通过的非最终预检证据摘要。 |
| 1.4.0 | 2026-09-04 | Codex | 隔离抖音专属封面生成，验证横竖封面均绑定到最终浏览器启动凭据。 |
"""

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from scripts import submit_english_world_douyin as submitter


@pytest.fixture(autouse=True)
def _replace_douyin_cover_generator(monkeypatch):
    """投稿器控制流测试不重复渲染封面，专属封面另由独立单测覆盖。"""
    monkeypatch.setattr(
        submitter,
        "prepare_douyin_cover_package",
        lambda item: {
            "vertical_cover_path": str(item["cover_path"]),
            "horizontal_cover_path": str(item["cover_path"]),
            "provenance_path": "",
        },
    )


def test_douyin_exit_codes_never_call_acceptance_published():
    assert submitter._completion_for_exit_code(6)[0] == "UNDER_REVIEW"
    assert submitter._completion_for_exit_code(7)[0] == "UNCERTAIN"
    assert submitter._completion_for_exit_code(3)[0] == "CANCELED"
    assert submitter._completion_for_exit_code(4)[0] == "CANCELED"
    assert submitter._completion_for_exit_code(2)[0] == "LOGIN_REQUIRED"


def test_verified_douyin_preflight_evidence_requires_all_platform_pass_markers(tmp_path):
    controls = tmp_path / "douyin_preflight_ready_controls.json"
    text = "竖封面3:4 横封面4:3 内容为个人观点或见解 封面效果检测通过 封面检测通过 作品未见异常"
    controls.write_text(json.dumps({"page": {"bodyTextPreview": text}}), encoding="utf-8")

    digest = submitter.verified_douyin_preflight_evidence_sha256(tmp_path)

    assert len(digest) == 64
    controls.write_text(json.dumps({"page": {"bodyTextPreview": f"{text} 竖封面缺失"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="cover failure"):
        submitter.verified_douyin_preflight_evidence_sha256(tmp_path)


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


def test_unknown_ui_fuse_stops_before_english_world_douyin_ledger(monkeypatch):
    class FakeDB:
        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return [{"stage": "future_ui_stage", "active": 1, "consecutive_failures": 2}]

        def ensure_english_world_douyin_publication(self, _review_id):
            raise AssertionError("unknown active UI stage must stop before publication ledger access")

    monkeypatch.setattr(submitter, "PipelineDB", FakeDB)
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)

    assert submitter.submit("b" * 32) == 4


def test_management_verify_fuse_keeps_english_world_new_submission_eligible(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.ensured = []

        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return [{"stage": "management_verify", "active": 1, "consecutive_failures": 2}]

        def ensure_english_world_douyin_publication(self, review_id):
            self.ensured.append(review_id)
            return {"state": "UNDER_REVIEW"}

    db = FakeDB()
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)

    assert submitter.submit("c" * 32) == 0
    assert db.ensured == ["c" * 32]


def test_management_verify_fuse_allows_claim_and_publish_worker(monkeypatch, tmp_path):
    """仅管理页熔断不能阻断新片的独立投稿前闸门。"""
    review_id = "d" * 32

    class FakeDB:
        def __init__(self):
            self.claimed = []
            self.completed = []

        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return [{"stage": "management_verify", "active": 1, "consecutive_failures": 2}]

        def ensure_english_world_douyin_publication(self, received_review_id):
            assert received_review_id == review_id
            return {"state": "QUEUED", "mp4_path": str(tmp_path / "video.mp4")}

        def claim_english_world_douyin_publication(self, received_review_id, **_kwargs):
            assert received_review_id == review_id
            self.claimed.append(received_review_id)
            return {
                "_attempt_id": "attempt-1",
                "_douyin_launch_ticket_id": "ew-ticket-1",
                "_douyin_launch_token": "ew-token-1",
                "mp4_path": str(tmp_path / "video.mp4"),
                "copy_path": str(tmp_path / "copy.txt"),
                "title_path": str(tmp_path / "title.txt"),
                "cover_path": str(tmp_path / "cover.jpg"),
            }

        def bind_douyin_browser_launch_ticket_payload(self, ticket_id, token, **_kwargs):
            assert (ticket_id, token) == ("ew-ticket-1", "ew-token-1")
            return True

        def clear_platform_ui_failure_streak(self, *args):
            assert args[:2] == ("douyin", "publish_pre_submit")

        def complete_english_world_douyin_publication(self, received_review_id, **kwargs):
            self.completed.append((received_review_id, kwargs))

    db = FakeDB()
    worker = MagicMock(return_value=subprocess.CompletedProcess([], 6, "", ""))
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter, "verify_package_hashes", lambda _claimed: None)
    monkeypatch.setattr(submitter.subprocess, "run", worker)
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)
    for filename in ("video.mp4", "copy.txt", "title.txt", "cover.jpg"):
        (tmp_path / filename).write_bytes(filename.encode("utf-8"))

    assert submitter.submit(review_id) == 0

    assert db.claimed == [review_id]
    command = worker.call_args.args[0]
    assert "--publish" in command
    assert command[command.index("--horizontal-cover") + 1] == str(tmp_path / "cover.jpg")
    assert command[command.index("--douyin-launch-ticket") + 1] == "ew-ticket-1"
    assert command[command.index("--douyin-launch-token") + 1] == "ew-token-1"
    assert db.completed[0][0] == review_id
    assert db.completed[0][1]["state"] == "UNDER_REVIEW"


def test_package_validation_failure_before_browser_cancels_unstarted_english_world_ticket(monkeypatch, tmp_path):
    """包校验失败时不得把未打开浏览器的领取误记为 FAILED 而堵死显式恢复。"""
    review_id = "e" * 32

    class FakeDB:
        def __init__(self):
            self.canceled = []
            self.completed = []

        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return []

        def ensure_english_world_douyin_publication(self, received_review_id):
            assert received_review_id == review_id
            return {"state": "QUEUED", "mp4_path": str(tmp_path / "video.mp4")}

        def claim_english_world_douyin_publication(self, received_review_id, **_kwargs):
            assert received_review_id == review_id
            return {
                "_attempt_id": "attempt-prelaunch",
                "_douyin_launch_ticket_id": "ew-ticket-prelaunch",
                "_douyin_launch_token": "ew-token-prelaunch",
                "mp4_path": str(tmp_path / "video.mp4"),
                "copy_path": str(tmp_path / "copy.txt"),
                "title_path": str(tmp_path / "title.txt"),
                "cover_path": str(tmp_path / "cover.jpg"),
            }

        def cancel_english_world_douyin_pre_launch_failure(self, received_review_id, **kwargs):
            self.canceled.append((received_review_id, kwargs))
            return {"state": "CANCELED"}

        def complete_english_world_douyin_publication(self, received_review_id, **kwargs):
            self.completed.append((received_review_id, kwargs))

    db = FakeDB()
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        submitter,
        "verify_package_hashes",
        lambda _claimed: (_ for _ in ()).throw(ValueError("审核后投稿包发生变化")),
    )
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)

    assert submitter.submit(review_id) == 1

    assert len(db.canceled) == 1
    assert db.canceled[0][0] == review_id
    assert db.canceled[0][1]["attempt_id"] == "attempt-prelaunch"
    assert db.canceled[0][1]["ticket_id"] == "ew-ticket-prelaunch"
    assert db.completed == []


def test_stale_unstarted_english_world_ticket_is_canceled_before_submit_returns(monkeypatch, tmp_path):
    """进程崩溃遗留的 SUBMITTING 只可在 TTL 后收口，绝不能由调度器直接重投。"""
    review_id = "f" * 32

    class FakeDB:
        def __init__(self):
            self.stale_cancellations = []

        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return []

        def ensure_english_world_douyin_publication(self, received_review_id):
            assert received_review_id == review_id
            return {
                "state": "SUBMITTING",
                "mp4_path": str(tmp_path / "video.mp4"),
                "evidence_dir": "/douyin/original-claim",
            }

        def cancel_stale_english_world_douyin_pre_launch_failure(self, received_review_id, **kwargs):
            self.stale_cancellations.append((received_review_id, kwargs))
            return {"state": "CANCELED"}

        def claim_english_world_douyin_publication(self, *_args, **_kwargs):
            raise AssertionError("stale prelaunch cancellation must not automatically claim a new attempt")

    db = FakeDB()
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)
    monkeypatch.setattr(submitter.settings, "douyin_prelaunch_ticket_recovery_ttl_seconds", 900)

    assert submitter.submit(review_id) == 1

    assert db.stale_cancellations == [
        (review_id, {
            "stale_after_seconds": 900,
            "evidence_dir": "/douyin/original-claim",
        }),
    ]


def test_uploader_exit_before_ticket_launch_cancels_english_world_attempt(monkeypatch, tmp_path):
    """子进程虽已创建但未消费 ticket 时，exit=1 仍是可证明的发布前失败。"""
    review_id = "g" * 32

    class FakeDB:
        def __init__(self):
            self.canceled = []
            self.completed = []

        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return []

        def ensure_english_world_douyin_publication(self, received_review_id):
            assert received_review_id == review_id
            return {"state": "QUEUED", "mp4_path": str(tmp_path / "video.mp4")}

        def claim_english_world_douyin_publication(self, received_review_id, **_kwargs):
            assert received_review_id == review_id
            return {
                "_attempt_id": "attempt-child-exit",
                "_douyin_launch_ticket_id": "ew-ticket-child-exit",
                "_douyin_launch_token": "ew-token-child-exit",
                "mp4_path": str(tmp_path / "video.mp4"),
                "copy_path": str(tmp_path / "copy.txt"),
                "title_path": str(tmp_path / "title.txt"),
                "cover_path": str(tmp_path / "cover.jpg"),
            }

        def bind_douyin_browser_launch_ticket_payload(self, *_args, **_kwargs):
            return True

        def cancel_english_world_douyin_pre_launch_failure(self, received_review_id, **kwargs):
            self.canceled.append((received_review_id, kwargs))
            return {"state": "CANCELED"}

        def complete_english_world_douyin_publication(self, received_review_id, **kwargs):
            self.completed.append((received_review_id, kwargs))

    db = FakeDB()
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter, "verify_package_hashes", lambda _claimed: None)
    monkeypatch.setattr(
        submitter.subprocess,
        "run",
        MagicMock(return_value=subprocess.CompletedProcess([], 1, "", "worker died before browser")),
    )
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)
    for filename in ("video.mp4", "copy.txt", "title.txt", "cover.jpg"):
        (tmp_path / filename).write_bytes(filename.encode("utf-8"))

    assert submitter.submit(review_id) == 1

    assert len(db.canceled) == 1
    assert db.canceled[0][1]["attempt_id"] == "attempt-child-exit"
    assert db.completed == []


def test_timeout_before_ticket_launch_cancels_english_world_attempt(monkeypatch, tmp_path):
    """超时本身不证明已提交；ticket 未消费时必须按可恢复发布前失败收口。"""
    review_id = "h" * 32

    class FakeDB:
        def __init__(self):
            self.canceled = []
            self.completed = []

        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return []

        def ensure_english_world_douyin_publication(self, received_review_id):
            assert received_review_id == review_id
            return {"state": "QUEUED", "mp4_path": str(tmp_path / "video.mp4")}

        def claim_english_world_douyin_publication(self, received_review_id, **_kwargs):
            assert received_review_id == review_id
            return {
                "_attempt_id": "attempt-timeout",
                "_douyin_launch_ticket_id": "ew-ticket-timeout",
                "_douyin_launch_token": "ew-token-timeout",
                "mp4_path": str(tmp_path / "video.mp4"),
                "copy_path": str(tmp_path / "copy.txt"),
                "title_path": str(tmp_path / "title.txt"),
                "cover_path": str(tmp_path / "cover.jpg"),
            }

        def bind_douyin_browser_launch_ticket_payload(self, *_args, **_kwargs):
            return True

        def cancel_english_world_douyin_pre_launch_failure(self, received_review_id, **kwargs):
            self.canceled.append((received_review_id, kwargs))
            return {"state": "CANCELED"}

        def complete_english_world_douyin_publication(self, received_review_id, **kwargs):
            self.completed.append((received_review_id, kwargs))

    db = FakeDB()
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter, "verify_package_hashes", lambda _claimed: None)
    monkeypatch.setattr(
        submitter.subprocess,
        "run",
        MagicMock(side_effect=subprocess.TimeoutExpired(["douyin_uploader.py"], 1500)),
    )
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)
    for filename in ("video.mp4", "copy.txt", "title.txt", "cover.jpg"):
        (tmp_path / filename).write_bytes(filename.encode("utf-8"))

    assert submitter.submit(review_id) == 124

    assert len(db.canceled) == 1
    assert db.canceled[0][1]["attempt_id"] == "attempt-timeout"
    assert db.completed == []


def test_timeout_after_ticket_launch_stays_uncertain(monkeypatch, tmp_path):
    """ticket 已启动时不能借超时转为 CANCELED；必须保留提交不确定性。"""
    review_id = "i" * 32

    class FakeDB:
        def __init__(self):
            self.canceled = []
            self.completed = []

        def get_platform_ui_failure_streaks(self, platform):
            assert platform == "douyin"
            return []

        def ensure_english_world_douyin_publication(self, received_review_id):
            assert received_review_id == review_id
            return {"state": "QUEUED", "mp4_path": str(tmp_path / "video.mp4")}

        def claim_english_world_douyin_publication(self, received_review_id, **_kwargs):
            assert received_review_id == review_id
            return {
                "_attempt_id": "attempt-started-timeout",
                "_douyin_launch_ticket_id": "ew-ticket-started-timeout",
                "_douyin_launch_token": "ew-token-started-timeout",
                "mp4_path": str(tmp_path / "video.mp4"),
                "copy_path": str(tmp_path / "copy.txt"),
                "title_path": str(tmp_path / "title.txt"),
                "cover_path": str(tmp_path / "cover.jpg"),
            }

        def bind_douyin_browser_launch_ticket_payload(self, *_args, **_kwargs):
            return True

        def cancel_english_world_douyin_pre_launch_failure(self, received_review_id, **kwargs):
            self.canceled.append((received_review_id, kwargs))
            return None

        def complete_english_world_douyin_publication(self, received_review_id, **kwargs):
            self.completed.append((received_review_id, kwargs))

    db = FakeDB()
    monkeypatch.setattr(submitter, "PipelineDB", lambda: db)
    monkeypatch.setattr(submitter, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(submitter, "verify_package_hashes", lambda _claimed: None)
    monkeypatch.setattr(
        submitter.subprocess,
        "run",
        MagicMock(side_effect=subprocess.TimeoutExpired(["douyin_uploader.py"], 1500)),
    )
    monkeypatch.setattr(submitter.settings, "enable_douyin_browser_publishing", True)
    monkeypatch.setattr(submitter.settings, "douyin_ui_failure_recording_threshold", 2)
    for filename in ("video.mp4", "copy.txt", "title.txt", "cover.jpg"):
        (tmp_path / filename).write_bytes(filename.encode("utf-8"))

    assert submitter.submit(review_id) == 124

    assert len(db.canceled) == 1
    assert len(db.completed) == 1
    assert db.completed[0][1]["state"] == "UNCERTAIN"

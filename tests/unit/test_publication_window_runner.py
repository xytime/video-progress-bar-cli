"""自动发布巡航入口测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 覆盖窗口外跳过与窗口内单次完整流水线调用 |
| 1.0.1 | 2026-07-31 | Codex | 按 Pydantic Settings 的类方法替身方式隔离窗口判定 |
| 1.0.2 | 2026-07-31 | Codex | 覆盖已有巡航任务持锁时跳过重叠完整流水线 |
| 1.1.0 | 2026-08-02 | Codex | 覆盖关闭发布时段等待后的任意时刻巡航 |
| 1.2.0 | 2026-08-04 | Codex | 覆盖运行版本和完成状态记录，避免 Git revision 与活动实例混淆 |
| 1.3.0 | 2026-08-04 | Codex | 覆盖管线阶段回调写入巡航状态 |
| 1.4.0 | 2026-08-29 | Codex | 覆盖公共窗口巡航只续投一条 AUTO_POLICY 英语世界延后项。 |
| 1.5.0 | 2026-08-30 | Codex | 覆盖窗口调度前先回收过期未领取的具名补发授权。 |
| 1.6.0 | 2026-08-30 | Codex | 覆盖英语世界按原生 ID 只读回查并写回独立平台状态。 |
| 1.7.0 | 2026-08-30 | Codex | 覆盖回查超时熔断通知和英语世界到抖音的单条隔离调度。 |
"""

import fcntl
import json
import subprocess
from pathlib import Path
from unittest.mock import ANY, MagicMock

import scripts.run_publication_window as runner


def _configure_runner_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "LOCK_PATH", tmp_path / "runner.lock")
    monkeypatch.setattr(runner, "RUN_STATUS_PATH", tmp_path / "runner-status.json")


def test_runner_executes_pipeline_without_consulting_publication_window(monkeypatch, tmp_path: Path):
    _configure_runner_paths(monkeypatch, tmp_path)
    manager = MagicMock()
    pipeline_manager = MagicMock(return_value=manager)
    monkeypatch.setattr(runner, "PipelineManager", pipeline_manager)

    assert runner.run_publication_window() == 0
    pipeline_manager.assert_called_once_with(status_reporter=ANY)
    manager.run_daily_job.assert_called_once_with()


def test_runner_executes_pipeline_inside_publication_window(monkeypatch, tmp_path: Path):
    _configure_runner_paths(monkeypatch, tmp_path)
    manager = MagicMock()
    pipeline_manager = MagicMock(return_value=manager)
    monkeypatch.setattr(runner, "PipelineManager", pipeline_manager)

    assert runner.run_publication_window() == 0
    pipeline_manager.assert_called_once_with(status_reporter=ANY)
    manager.run_daily_job.assert_called_once_with()


def test_runner_skips_when_previous_window_run_holds_lock(monkeypatch, tmp_path: Path):
    lock_path = tmp_path / "runner.lock"
    lock_path.touch()
    _configure_runner_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "LOCK_PATH", lock_path)
    pipeline_manager = MagicMock()
    monkeypatch.setattr(runner, "PipelineManager", pipeline_manager)

    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        assert runner.run_publication_window() == 0

    pipeline_manager.assert_not_called()


def test_runner_records_running_instance_revision_and_completion(monkeypatch, tmp_path: Path):
    _configure_runner_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "_git_revision", lambda: "test-revision")
    manager = MagicMock()
    monkeypatch.setattr(runner, "PipelineManager", MagicMock(return_value=manager))

    assert runner.run_publication_window() == 0

    status = json.loads(runner.RUN_STATUS_PATH.read_text(encoding="utf-8"))
    assert status["state"] == "COMPLETED"
    assert status["git_revision"] == "test-revision"
    assert status["pid"] > 0
    assert status["started_at"] <= status["last_heartbeat_at"] == status["ended_at"]


def test_runner_records_pipeline_stage_context(monkeypatch, tmp_path: Path):
    _configure_runner_paths(monkeypatch, tmp_path)
    manager = MagicMock()

    def pipeline_factory(*, status_reporter):
        status_reporter({
            "current_video": "video-id",
            "current_slice_index": 0,
            "stage": "RENDERING",
            "preparation_only": False,
        })
        return manager

    monkeypatch.setattr(runner, "PipelineManager", pipeline_factory)

    assert runner.run_publication_window() == 0

    status = json.loads(runner.RUN_STATUS_PATH.read_text(encoding="utf-8"))
    assert status["current_video"] == "video-id"
    assert status["stage"] == "RENDERING"
    assert status["stage_started_at"] <= status["ended_at"]


def test_window_dispatches_one_deferred_english_world_auto_item(monkeypatch):
    class FakeDB:
        def restore_expired_english_world_operator_recoveries(self):
            return 0

        def get_next_auto_approved_english_world_submission(self):
            return {"id": "b" * 32}

    completed = MagicMock(returncode=0, stderr="")
    monkeypatch.setattr(runner, "PipelineDB", FakeDB)
    monkeypatch.setattr(runner.settings, "enable_english_world_auto_publish", True)
    monkeypatch.setattr(runner.settings, "wechat_publishing_paused", False)
    monkeypatch.setattr(type(runner.settings), "is_public_publish_window", lambda _self: True)
    run = MagicMock(return_value=completed)
    monkeypatch.setattr(runner.subprocess, "run", run)

    runner.dispatch_one_deferred_english_world_submission()

    assert run.call_args.args[0][-2:] == ["--review-id", "b" * 32]


def test_window_dispatches_one_accepted_english_world_item_to_douyin(monkeypatch):
    class FakeDB:
        def get_next_english_world_douyin_sync_candidate(self):
            return {"id": "e" * 32}

    completed = MagicMock(returncode=0, stderr="")
    monkeypatch.setattr(runner, "PipelineDB", FakeDB)
    monkeypatch.setattr(runner.settings, "enable_english_world_douyin_sync", True)
    monkeypatch.setattr(runner.settings, "enable_douyin_browser_publishing", True)
    run = MagicMock(return_value=completed)
    monkeypatch.setattr(runner.subprocess, "run", run)

    runner.dispatch_one_english_world_douyin_submission()

    assert run.call_args.args[0][-2:] == ["--review-id", "e" * 32]
    assert "submit_english_world_douyin.py" in str(run.call_args.args[0][1])


def test_runner_reconciles_one_bound_english_world_item_without_upload(monkeypatch, tmp_path):
    recorded = {}

    class FakeDB:
        def claim_next_english_world_reconciliation(self, **_kwargs):
            return {
                "id": "c" * 32,
                "platform_post_id": "export/native-id",
                "platform_url": None,
                "evidence_dir": str(tmp_path / "submission"),
            }

        def record_english_world_reconciliation(self, review_id, **kwargs):
            recorded.update({"review_id": review_id, **kwargs})

    def fake_run(command, **_kwargs):
        recorded["command"] = command
        evidence_dir = Path(command[command.index("--evidence-dir") + 1])
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "management_under_review.png").write_bytes(b"png")
        return type("Result", (), {"returncode": 6})()

    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "PipelineDB", FakeDB)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner.settings, "english_world_reconcile_interval_minutes", 30)
    monkeypatch.setattr(runner.settings, "english_world_reconcile_max_age_hours", 72)
    monkeypatch.setattr(runner.settings, "english_world_reconcile_failure_limit", 2)
    monkeypatch.setattr(runner.settings, "wechat_headless", True)
    monkeypatch.setattr(runner.settings, "wechat_review_timeout_seconds", 180)

    runner.reconcile_one_english_world_submission()

    assert recorded["review_id"] == "c" * 32
    assert recorded["platform_state"] == "UNDER_REVIEW"
    command_text = " ".join(str(part) for part in recorded["command"])
    assert "--video" not in command_text
    assert "--verify-only" in command_text
    assert "export/native-id" in command_text


def test_reconciliation_timeout_reaches_fuse_and_escapes_notification(monkeypatch, tmp_path):
    failures = 0
    notifications = []

    class FakeDB:
        def claim_next_english_world_reconciliation(self, **_kwargs):
            return {
                "id": "d" * 32,
                "title": "A&B <成长>",
                "platform_post_id": "export/native-id",
                "platform_url": None,
                "evidence_dir": str(tmp_path / "submission"),
            }

        def record_english_world_reconciliation(self, _review_id, **_kwargs):
            nonlocal failures
            failures += 1
            return {"reconciliation_failures": failures}

    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "PipelineDB", FakeDB)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        MagicMock(side_effect=subprocess.TimeoutExpired(["wechat_uploader"], 30)),
    )
    monkeypatch.setattr(runner, "send_text", lambda **kwargs: notifications.append(kwargs))
    monkeypatch.setattr(runner.settings, "english_world_reconcile_interval_minutes", 30)
    monkeypatch.setattr(runner.settings, "english_world_reconcile_max_age_hours", 72)
    monkeypatch.setattr(runner.settings, "english_world_reconcile_failure_limit", 2)
    monkeypatch.setattr(runner.settings, "wechat_headless", True)
    monkeypatch.setattr(runner.settings, "wechat_review_timeout_seconds", 30)

    runner.reconcile_one_english_world_submission()
    runner.reconcile_one_english_world_submission()

    assert failures == 2
    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "english_world.reconciliation_recording_required"
    assert "A&amp;B &lt;成长&gt;" in notifications[0]["text"]
    assert "A&B <成长>" not in notifications[0]["text"]

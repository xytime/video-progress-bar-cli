"""视频号互动 finite worker/CLI 安全回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-09-20 | Codex | 覆盖人工三条批量评论在不确定结果后停止，避免继续提交更旧作品。 |
| 1.1.0 | 2026-09-19 | Codex | 覆盖 SUBMITTED_BOUND 原生 ID 的显式互动执行，避免历史回查延迟阻断已发布作品。 |
| 1.0.0 | 2026-09-19 | Codex | 覆盖默认关闭、只读 dry-run、提交 callback 与 UNCERTAIN 核验协议。 |
"""

from __future__ import annotations

import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from scripts import wechat_commenter
from video_processing.db.database import PipelineDB
from video_processing.interaction.contract import InteractionType
from video_processing.interaction.runner import run_interaction_tick


UTC = datetime.timezone.utc


class _FakeServices:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.calls: list[dict[str, Any]] = []
        self.generated = 0

    def generate_comment(self, target: Mapping[str, Any], *, force_rule: bool) -> Any:
        self.generated += 1
        return SimpleNamespace(
            formatted_comment="这是一条会持久保留且绝不在重试时重新生成的测试互动评论文本。",
            interaction_type=InteractionType.POLL_STAND,
            provider="test-rule",
        )

    def post_comment(self, **kwargs: Any) -> tuple[str, None, str | None]:
        self.calls.append(kwargs)
        callback = kwargs["before_submit"]
        if not kwargs["verify_only"]:
            assert callback is not None and callback() is True
        else:
            assert callback is None
        status = self.statuses.pop(0)
        return status, None, "unconfirmed" if status == "UNCERTAIN" else None

    def notify_result(self, *_args: Any) -> None:
        return None


def _seed_published(db: PipelineDB, tmp_path: Path) -> None:
    db.add_video("yt_cli", "CLI Test", "channel", score=90)
    evidence = tmp_path / "published.png"
    evidence.write_bytes(b"proof")
    db.record_wechat_publication_confirmation(
        "yt_cli", evidence_path=str(evidence), state="PUBLISHED",
        platform_post_id="export/cli_post",
    )


def _seed_submitted_bound(db: PipelineDB, tmp_path: Path) -> None:
    db.add_video("yt_bound", "Bound Test", "channel", score=90)
    evidence = tmp_path / "bound.png"
    evidence.write_bytes(b"bound proof")
    db.record_wechat_publication_confirmation(
        "yt_bound", evidence_path=str(evidence), state="SUBMITTED_BOUND",
        platform_post_id="export/bound_post",
    )


def test_runner_never_resends_uncertain_and_reuses_persisted_text(tmp_path: Path) -> None:
    db = PipelineDB(db_path=str(tmp_path / "runner.db"))
    _seed_published(db, tmp_path)
    now = datetime.datetime(2026, 9, 19, 3, 0, tzinfo=UTC)
    services = _FakeServices(["UNCERTAIN", "COMMENTED"])

    first = run_interaction_tick(db, services, clock=lambda: now, evidence_root=tmp_path)
    assert first.status == "UNCERTAIN"
    saved = db.get_wechat_interaction_by_post_id("export/cli_post")
    assert saved["status"] == "UNCERTAIN"
    saved_text = saved["comment_text"]

    due = datetime.datetime.fromisoformat(saved["next_attempt_at"])
    second = run_interaction_tick(db, services, clock=lambda: due, evidence_root=tmp_path)
    assert second.status == "COMMENTED"
    assert services.generated == 1
    assert services.calls[1]["verify_only"] is True
    assert services.calls[1]["comment_text"] == saved_text


def test_runner_dry_run_does_not_create_interaction_ledger(tmp_path: Path) -> None:
    db = PipelineDB(db_path=str(tmp_path / "dry.db"))
    _seed_published(db, tmp_path)
    services = _FakeServices([])
    result = run_interaction_tick(db, services, dry_run=True, evidence_root=tmp_path)
    assert result.status == "DRY_RUN"
    assert db.get_wechat_interaction_by_post_id("export/cli_post") is None
    assert services.calls == []


def test_runner_accepts_explicit_submitted_bound_native_post_id(tmp_path: Path) -> None:
    db = PipelineDB(db_path=str(tmp_path / "bound.db"))
    _seed_submitted_bound(db, tmp_path)
    services = _FakeServices(["COMMENTED"])

    result = run_interaction_tick(
        db,
        services,
        platform_post_id="export/bound_post",
        evidence_root=tmp_path,
    )

    assert result.status == "COMMENTED"
    assert services.calls[0]["platform_post_id"] == "export/bound_post"


def test_reconcile_only_does_not_generate_or_click_for_new_publication(tmp_path: Path) -> None:
    db = PipelineDB(db_path=str(tmp_path / "reconcile.db"))
    _seed_published(db, tmp_path)
    services = _FakeServices([])
    result = run_interaction_tick(
        db, services, reconcile_only=True, evidence_root=tmp_path
    )
    assert result.status == "NO_WORK"
    assert services.generated == 0
    assert services.calls == []
    assert db.get_wechat_interaction_by_post_id("export/cli_post") is None


def test_immutable_read_only_preview_creates_no_auxiliary_files(tmp_path: Path) -> None:
    db_path = tmp_path / "readonly.db"
    writable = PipelineDB(db_path=str(db_path))
    _seed_published(writable, tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    readonly = PipelineDB(db_path=str(db_path), read_only=True)
    services = _FakeServices([])
    result = run_interaction_tick(readonly, services, dry_run=True, evidence_root=tmp_path)
    after = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert result.status == "DRY_RUN"
    assert after == before


def test_read_only_preview_refuses_nonempty_wal_without_modifying_it(tmp_path: Path) -> None:
    db_path = tmp_path / "active.db"
    PipelineDB(db_path=str(db_path))
    wal_path = Path(f"{db_path}-wal")
    wal_path.write_bytes(b"active-uncheckpointed-state")
    before = wal_path.read_bytes()
    with pytest.raises(RuntimeError, match="non-empty WAL"):
        PipelineDB(db_path=str(db_path), read_only=True)
    assert wal_path.read_bytes() == before


def test_disabled_live_cli_stops_before_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        wechat_commenter.settings, "enable_wechat_comment_interaction", False
    )

    class _MustNotConstruct:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("disabled live path constructed a dependency")

    monkeypatch.setattr(wechat_commenter, "_LiveServices", _MustNotConstruct)
    assert wechat_commenter.run_interaction() == 0


def test_persisted_comment_rejected_by_new_policy_never_constructs_browser(monkeypatch) -> None:
    class _RejectingGenerator:
        def validate_comment_for_submission(self, _text: str) -> None:
            raise ValueError("new policy rejection")

    services = wechat_commenter._LiveServices.__new__(wechat_commenter._LiveServices)
    services.generator = _RejectingGenerator()
    status, evidence, error = services.post_comment(
        comment_text="previously persisted text",
        platform_post_id="export/rejected",
        video_title="title",
        evidence_dir=Path("/not/used"),
        before_submit=lambda: True,
        verify_only=False,
    )
    assert status == "FAILED"
    assert evidence is None
    assert "new policy rejection" in (error or "")


def test_worker_deadline_cannot_be_swallowed_by_except_exception() -> None:
    swallowed = False
    try:
        try:
            raise wechat_commenter._WorkerDeadline("deadline")
        except Exception:
            swallowed = True
    except wechat_commenter._WorkerDeadline:
        pass
    assert swallowed is False


def test_manual_batch_stops_after_uncertain_result(monkeypatch, tmp_path: Path) -> None:
    """批量入口保持候选顺序，首条结果不确定时不得继续提交更旧作品。"""
    candidates = [
        {"platform_post_id": "export/newest"},
        {"platform_post_id": "export/older"},
        {"platform_post_id": "export/oldest"},
    ]
    calls: list[str] = []

    class _BatchDB:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def get_recent_wechat_posts_without_interaction(self, *, limit: int) -> list[dict[str, str]]:
            assert limit == 3
            return candidates

    def fake_tick(_db: Any, _services: Any, **kwargs: Any) -> Any:
        post_id = str(kwargs["platform_post_id"])
        calls.append(post_id)
        return SimpleNamespace(
            status="UNCERTAIN" if post_id == "export/newest" else "COMMENTED",
            platform_post_id=post_id,
            detail=None,
        )

    monkeypatch.setattr(wechat_commenter.settings, "enable_wechat_comment_interaction", True)
    monkeypatch.setattr(wechat_commenter, "_LiveServices", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(wechat_commenter, "WORKER_LOCK", tmp_path / "worker.lock")
    monkeypatch.setattr("video_processing.db.database.PipelineDB", _BatchDB)
    monkeypatch.setattr("video_processing.interaction.runner.run_interaction_tick", fake_tick)

    assert wechat_commenter.run_interaction(count=3, notify_tg=False) == 0
    assert calls == ["export/newest"]

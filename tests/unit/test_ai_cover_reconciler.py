"""AI 封面完成物协调器事故防线测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-03 | Codex | 覆盖旧封面任务不得重新入队已发布视频、合法 AI_COVER_PENDING 回队和巡查锁 |
| 1.1.0 | 2026-08-07 | Codex | 覆盖封面完成与预加工就绪标记原子回填，供盘中轻量提交 |
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from scripts import reconcile_ai_cover_queue as reconciler
from video_processing.ai_cover_queue import AICoverQueue, AICoverTask
from video_processing.db.database import PipelineDB


def _new_task(tmp_path: Path) -> AICoverTask:
    queue = AICoverQueue(tmp_path / "queue", tmp_path / "finish")
    return queue.create_task(
        prefix="cover-guard",
        youtube_id="cover-guard",
        slice_index=0,
        cover_payload={"title": "测试标题", "audio_edition": "original_audio_subtitled"},
        visual_brief={"visual_direction": "高对比人物场景", "visual_keywords": ["markets"]},
        final_cover_path=tmp_path / "output" / "cover-guard_cover.jpg",
        provenance_path=tmp_path / "output" / "cover-guard_cover_provenance.json",
        brief_path=tmp_path / "output" / "cover-guard_cover_brief.json",
        content_aware=True,
        generation_deadline_minutes=30,
        fallback_after_minutes=32,
        now=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )


def test_render_never_requeues_published_video(monkeypatch, tmp_path: Path):
    task = _new_task(tmp_path)
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_video("cover-guard", "Title", "channel", score=88)
    db.update_video_status("cover-guard", "PUBLISHED")
    subprocess_run = MagicMock()
    monkeypatch.setattr(reconciler.subprocess, "run", subprocess_run)

    assert reconciler._render(task, None, db) is False

    subprocess_run.assert_not_called()
    assert db.get_video_by_youtube_id("cover-guard")["status"] == "PUBLISHED"
    assert not (task.finish_dir / "resolution.json").exists()


def test_render_requeues_only_active_ai_cover_pending(monkeypatch, tmp_path: Path):
    task = _new_task(tmp_path)
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_video("cover-guard", "Title", "channel", score=88)
    db.update_video_status("cover-guard", "AI_COVER_PENDING", error_msg="等待封面")
    monkeypatch.setattr(reconciler, "_is_dedicated_cover", lambda _path: True)
    monkeypatch.setattr(
        reconciler.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    assert reconciler._render(task, None, db) is True

    row = db.get_video_by_youtube_id("cover-guard")
    assert row["status"] == "PENDING"
    assert row["preparation_ready"] == 1
    assert row["error_msg"] is None
    resolution = json.loads((task.finish_dir / "resolution.json").read_text(encoding="utf-8"))
    assert resolution["source"] == "deterministic_fallback"


def test_reconcile_skips_when_previous_run_holds_lock(monkeypatch, tmp_path: Path):
    lock_path = tmp_path / "ai_cover_reconciler.lock"
    lock_path.touch()
    monkeypatch.setattr(reconciler, "LOCK_PATH", lock_path)
    monkeypatch.setattr(reconciler.settings, "enable_codex_cover_queue", True)
    queue_factory = MagicMock()
    monkeypatch.setattr(reconciler, "AICoverQueue", queue_factory)

    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        assert reconciler.reconcile() == 0

    queue_factory.assert_not_called()


def test_reconcile_does_not_reprocess_resolved_task(monkeypatch, tmp_path: Path):
    _new_task(tmp_path)
    monkeypatch.setattr(reconciler, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(reconciler, "LOCK_PATH", tmp_path / "ai_cover_reconciler.lock")
    monkeypatch.setattr(reconciler.settings, "enable_codex_cover_queue", True)
    monkeypatch.setattr(reconciler.settings, "ai_cover_queue_dir", "queue")
    monkeypatch.setattr(reconciler.settings, "ai_cover_finish_dir", "finish")
    render = MagicMock(return_value=True)
    monkeypatch.setattr(reconciler, "_render", render)
    monkeypatch.setattr(reconciler, "PipelineDB", MagicMock())

    for task in AICoverQueue(tmp_path / "queue", tmp_path / "finish").list_tasks():
        (task.finish_dir / "resolution.json").write_text("{}", encoding="utf-8")

    assert reconciler.reconcile() == 0
    render.assert_not_called()

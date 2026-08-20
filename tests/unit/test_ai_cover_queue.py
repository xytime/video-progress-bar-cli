"""AI 封面任务队列测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 覆盖任务 Markdown、完成物来源校验和超时降级时点 |
| 1.1.0 | 2026-07-31 | Codex | 覆盖巡查前可领取任务判定，避免空队列执行外部生成器 |
| 1.2.0 | 2026-08-03 | Codex | 覆盖已有底图优先复用和高消耗确认规则进入任务协议 |
| 1.3.0 | 2026-08-20 | Codex | 覆盖 Anti-gravity 完成物来源验收 |
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from src.video_processing.ai_cover_queue import AICoverQueue


def _new_task(queue: AICoverQueue, tmp_path: Path, now: datetime):
    return queue.create_task(
        prefix="abcdefghijk",
        youtube_id="abcdefghijk",
        slice_index=0,
        cover_payload={"title": "测试标题", "audio_edition": "original_audio_subtitled"},
        visual_brief={"visual_direction": "开放地平线", "visual_keywords": ["mindset"]},
        final_cover_path=tmp_path / "output" / "abcdefghijk_cover.jpg",
        provenance_path=tmp_path / "output" / "abcdefghijk_cover_provenance.json",
        brief_path=tmp_path / "output" / "abcdefghijk_cover_brief.json",
        content_aware=True,
        generation_deadline_minutes=32,
        fallback_after_minutes=34,
        now=now,
    )


def test_task_is_markdown_and_is_idempotent(tmp_path: Path):
    queue = AICoverQueue(tmp_path / "queue", tmp_path / "finish")
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)

    task = _new_task(queue, tmp_path, now)
    same_task = _new_task(queue, tmp_path, now + timedelta(minutes=1))

    assert task.task_id == same_task.task_id
    assert task.path.suffix == ".md"
    assert "AI_COVER_TASK_JSON" in task.path.read_text(encoding="utf-8")
    assert task.payload["generation_deadline_at"] == "2026-07-31T00:32:00Z"
    assert task.payload["fallback_after_at"] == "2026-07-31T00:34:00Z"
    assert task.payload["rules"]["reuse_existing_visual_before_generation"] is True
    assert task.payload["rules"]["ask_before_high_cost_regeneration"] is True
    markdown = task.path.read_text(encoding="utf-8")
    assert "已有可用 `visual.png`" in markdown
    assert "高消耗重生成必须先获人工确认" in markdown


def test_accepts_only_verified_on_time_codex_visual(tmp_path: Path):
    queue = AICoverQueue(tmp_path / "queue", tmp_path / "finish")
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    task = _new_task(queue, tmp_path, now)
    visual = task.finish_dir / "visual.png"
    Image.new("RGB", (720, 960), "white").save(visual)
    digest = hashlib.sha256(visual.read_bytes()).hexdigest()
    (task.finish_dir / "result.json").write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "generated_by": "codex_imagegen",
                "completed_at": "2026-07-31T00:31:00Z",
                "visual_filename": "visual.png",
                "sha256": digest,
                "uses_video_frame": False,
            }
        ),
        encoding="utf-8",
    )

    assert queue.accepted_visual(task) == visual

    result = json.loads((task.finish_dir / "result.json").read_text(encoding="utf-8"))
    result["completed_at"] = "2026-07-31T00:33:00Z"
    (task.finish_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    assert queue.accepted_visual(task) is None


def test_fallback_starts_before_forty_minute_sla(tmp_path: Path):
    queue = AICoverQueue(tmp_path / "queue", tmp_path / "finish")
    created = datetime(2026, 7, 31, tzinfo=timezone.utc)
    task = _new_task(queue, tmp_path, created)

    assert queue.should_fallback(task, created + timedelta(minutes=33, seconds=59)) is False
    assert queue.should_fallback(task, created + timedelta(minutes=34)) is True


def test_accepts_verified_antigravity_visual(tmp_path: Path):
    queue = AICoverQueue(tmp_path / "queue", tmp_path / "finish")
    created = datetime(2026, 7, 31, tzinfo=timezone.utc)
    task = _new_task(queue, tmp_path, created)
    visual = task.finish_dir / "visual.png"
    Image.new("RGB", (896, 1200), "#101522").save(visual)
    digest = hashlib.sha256(visual.read_bytes()).hexdigest()
    (task.finish_dir / "result.json").write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "generated_by": "antigravity_imagegen",
                "completed_at": "2026-07-31T00:31:00Z",
                "visual_filename": "visual.png",
                "sha256": digest,
                "uses_video_frame": False,
                "human_visual_review": "reviewed_no_text",
            }
        ),
        encoding="utf-8",
    )

    assert queue.accepted_visual(task) == visual
    assert queue.accepted_source(task) == "antigravity_imagegen"

    result = json.loads((task.finish_dir / "result.json").read_text(encoding="utf-8"))
    result["human_visual_review"] = "unverified"
    (task.finish_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    assert queue.accepted_visual(task) is None


def test_eligible_task_excludes_completed_expired_and_fresh_claims(tmp_path: Path):
    queue = AICoverQueue(tmp_path / "queue", tmp_path / "finish")
    created = datetime(2026, 7, 31, tzinfo=timezone.utc)
    task = _new_task(queue, tmp_path, created)
    current = created + timedelta(minutes=1)

    assert queue.has_eligible_task(current) is True

    (task.finish_dir / "claim.json").write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "claim_expires_at": "2026-07-31T00:13:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert queue.has_eligible_task(current) is False

    (task.finish_dir / "claim.json").unlink()
    (task.finish_dir / "resolution.json").write_text("{}", encoding="utf-8")
    assert queue.has_eligible_task(current) is False

    (task.finish_dir / "resolution.json").unlink()
    assert queue.has_eligible_task(created + timedelta(minutes=32)) is False

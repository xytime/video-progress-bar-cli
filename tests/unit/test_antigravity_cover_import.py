"""Anti-gravity 封面适配器测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-20 | Codex | 覆盖人工验收门、格式转换、deadline 和原子完成物 |
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from scripts.import_antigravity_cover import import_visual
from src.video_processing.ai_cover_queue import AICoverQueue


def _task(tmp_path):
    queue = AICoverQueue(tmp_path / "queue", tmp_path / "finish")
    task = queue.create_task(
        prefix="abcdefghijk",
        youtube_id="abcdefghijk",
        slice_index=0,
        cover_payload={"title": "测试"},
        visual_brief={"visual_direction": "抽象桥梁", "visual_keywords": ["bridge"]},
        final_cover_path=tmp_path / "output" / "cover.jpg",
        provenance_path=tmp_path / "output" / "cover_provenance.json",
        brief_path=tmp_path / "output" / "brief.json",
        content_aware=False,
        generation_deadline_minutes=32,
        fallback_after_minutes=34,
        now=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    return queue, task


def test_requires_human_no_text_review(tmp_path):
    queue, task = _task(tmp_path)
    source = tmp_path / "antigravity.jpg"
    Image.new("RGB", (896, 1200), "#101522").save(source)

    with pytest.raises(ValueError, match="reviewed-no-text"):
        import_visual(queue, task, source, reviewed_no_text=False)
    assert not (task.finish_dir / "result.json").exists()


def test_converts_and_writes_antigravity_result_atomically(tmp_path):
    queue, task = _task(tmp_path)
    source = tmp_path / "antigravity.jpg"
    Image.new("RGB", (896, 1200), "#101522").save(source)
    created_at = datetime(2026, 7, 31, 0, 31, tzinfo=timezone.utc)

    visual = import_visual(
        queue,
        task,
        source,
        reviewed_no_text=True,
        completed_at=created_at,
        now=created_at + timedelta(minutes=1),
    )

    assert visual.name == "visual.png"
    assert visual.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    result = json.loads((task.finish_dir / "result.json").read_text(encoding="utf-8"))
    assert result["generated_by"] == "antigravity_imagegen"
    assert queue.accepted_visual(task) == visual


def test_rejects_late_antigravity_result(tmp_path):
    queue, task = _task(tmp_path)
    source = tmp_path / "antigravity.jpg"
    Image.new("RGB", (896, 1200), "#101522").save(source)

    with pytest.raises(ValueError, match="generation_deadline"):
        import_visual(
            queue,
            task,
            source,
            reviewed_no_text=True,
            completed_at=datetime(2026, 7, 31, 0, 33, tzinfo=timezone.utc),
        )
    assert not (task.finish_dir / "result.json").exists()

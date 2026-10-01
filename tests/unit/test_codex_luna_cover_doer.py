"""Luna CLI 封面文件协议测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-01 | Codex | 验证双会话、回执门禁与失败释放 claim |
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from scripts import run_codex_luna_cover_doer as worker
from video_processing.ai_cover_queue import AICoverQueue


def _task(tmp_path: Path):
    queue = AICoverQueue(tmp_path / "queue", tmp_path / "finish")
    task = queue.create_task(
        prefix="luna-test", youtube_id="luna-test", slice_index=0,
        cover_payload={"title": "芯片工厂"}, visual_brief={"visual_direction": "晶圆制造"},
        final_cover_path=tmp_path / "cover.jpg", provenance_path=tmp_path / "provenance.json",
        brief_path=tmp_path / "brief.json", content_aware=False,
        generation_deadline_minutes=32, fallback_after_minutes=34,
        primary_provider="agy", enable_luna_fallback=True, now=datetime.now(timezone.utc),
    )
    (task.finish_dir / "antigravity_attempt.json").write_text(json.dumps({"status": "failed", "attempt_number": 3}))
    args = argparse.Namespace(codex_bin="codex", model="gpt-5.6-luna", timeout_seconds=180,
                              review_timeout_seconds=60)
    return queue, task, args


def test_luna_two_cli_sessions_write_accepted_receipt(tmp_path: Path, monkeypatch):
    queue, task, args = _task(tmp_path)
    monkeypatch.setattr(worker, "_generated_images_dir", lambda: tmp_path)
    calls = []

    def fake_cli(command, work_dir, timeout):
        calls.append(command)
        if len(calls) == 1:
            Image.new("RGB", (768, 1024), "blue").save(work_dir / "candidate.png")
        else:
            review = {key: True for key in ("image_inspected", "subject_relevant", "composition_complete",
                                           "adequate_detail", "no_severe_artifacts")}
            review.update(decision="PASS", observed_content="晶圆制造车间", reason="画面完整且相关")
            (work_dir / "quality_review.json").write_text(json.dumps(review))

    monkeypatch.setattr(worker, "_run_cli", fake_cli)
    assert worker._run_task(args, task, queue) == 0
    assert len(calls) == 2
    assert "--image" in calls[1]
    assert queue.accepted_source(task) == "codex_luna_imagegen"
    receipt = json.loads((task.finish_dir / "result.json").read_text())
    assert receipt["transport"] == "codex_cli"
    assert receipt["image_model"] == "unknown"
    assert not (task.finish_dir / "claim.json").exists()


def test_luna_rejection_falls_back_without_result(tmp_path: Path, monkeypatch):
    queue, task, args = _task(tmp_path)
    monkeypatch.setattr(worker, "_generated_images_dir", lambda: tmp_path)

    def fake_cli(command, work_dir, timeout):
        if "--image" not in command:
            Image.new("RGB", (768, 1024), "blue").save(work_dir / "candidate.png")
        else:
            (work_dir / "quality_review.json").write_text(json.dumps({"decision": "UNCERTAIN"}))

    monkeypatch.setattr(worker, "_run_cli", fake_cli)
    assert worker._run_task(args, task, queue) == 1
    assert not (task.finish_dir / "result.json").exists()
    assert json.loads((task.finish_dir / "luna_attempt.json").read_text())["status"] == "failed"
    assert not (task.finish_dir / "claim.json").exists()

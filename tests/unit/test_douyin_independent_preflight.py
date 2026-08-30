"""抖音独立 NEW 只读素材预检测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 覆盖完整候选、素材缺失、历史账本排除和前后不建账证明 |
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.douyin_independent_preflight import inspect_independent_candidates
from video_processing.core.cover_policy import compliant_cover_layout_policy
from video_processing.db.database import PipelineDB


def _accepted_video(db: PipelineDB, youtube_id: str) -> None:
    assert db.add_video(youtube_id, "测试视频", "channel", score=88)
    db.record_wechat_submission_acceptance(
        youtube_id,
        evidence_path=None,
        error_message="视频号已受理，等待公开确认",
        final_title="测试标题",
    )


def _assets(output_dir: Path, youtube_id: str, *, include_title: bool = True) -> None:
    vertical = output_dir / f"{youtube_id}_vertical.mp4"
    vertical.write_bytes(b"video")
    (output_dir / f"{youtube_id}_copy.txt").write_text("测试文案", encoding="utf-8")
    if include_title:
        (output_dir / f"{youtube_id}_title.txt").write_text("测试标题", encoding="utf-8")
    cover = output_dir / f"{youtube_id}_cover.jpg"
    cover.write_bytes(b"dedicated-cover")
    (output_dir / f"{youtube_id}_cover_provenance.json").write_text(
        json.dumps({
            "cover_kind": "dedicated_generated_image",
            "uses_video_frame": False,
            "cover_filename": cover.name,
            "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
            "layout_policy": compliant_cover_layout_policy(),
        }),
        encoding="utf-8",
    )
    (output_dir / f"{youtube_id}.ass").write_text(
        "[Script Info]\nScriptType: v4.00+\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,subtitle body\n",
        encoding="utf-8",
    )


def test_preflight_proves_complete_candidate_without_creating_ledger(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _accepted_video(db, "ready")
    _assets(tmp_path, "ready")

    result = inspect_independent_candidates(
        db,
        output_dir=tmp_path,
        lookback_hours=24,
        video_probe=lambda _path: (True, 30.0, None),
    )

    assert result["candidate_count"] == 1
    assert result["local_preflight_ready_count"] == 1
    assert result["ledger_unchanged"] is True
    assert result["browser_opened"] is False
    assert result["publication_created"] is False
    assert result["items"][0]["local_preflight_ready"] is True
    assert db.get_douyin_publication("ready") is None


def test_preflight_reports_missing_assets_and_excludes_any_historical_ledger(tmp_path: Path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    _accepted_video(db, "missing-title")
    _assets(tmp_path, "missing-title", include_title=False)
    _accepted_video(db, "historical")
    _assets(tmp_path, "historical")
    publication = db.create_douyin_publication(
        "historical", "a" * 64, str(tmp_path / "historical_vertical.mp4"), source_kind="NEW"
    )
    db.update_douyin_publication_state(publication["id"], "CANCELED", error_message="历史取消")

    result = inspect_independent_candidates(
        db,
        output_dir=tmp_path,
        lookback_hours=24,
        video_probe=lambda _path: (True, 30.0, None),
    )

    assert [item["youtube_id"] for item in result["items"]] == ["missing-title"]
    assert result["items"][0]["local_preflight_ready"] is False
    assert "抖音标题缺失或为空" in result["items"][0]["failures"]
    assert db.get_douyin_publication("missing-title") is None
    assert db.get_douyin_publication("historical")["state"] == "CANCELED"

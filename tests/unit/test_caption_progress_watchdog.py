"""字幕阶段看门狗回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-03 | Codex | 覆盖无首个心跳、心跳失联与同阶段超时的可终止边界。 |
"""

from __future__ import annotations

import json

from video_processing.pipeline_manager import _CaptionProgressWatchdog


def _write_progress(path, *, stage: str, updated_at: float, stage_started_at: float) -> None:
    path.write_text(
        json.dumps({
            "stage": stage,
            "updated_at": updated_at,
            "stage_started_at": stage_started_at,
        }),
        encoding="utf-8",
    )


def test_watchdog_stops_when_initial_caption_heartbeat_never_arrives(tmp_path):
    progress_path = tmp_path / "caption-progress.json"
    watchdog = _CaptionProgressWatchdog(
        started_at=100.0,
        startup_timeout_seconds=20,
        heartbeat_timeout_seconds=30,
        stage_timeout_seconds={"TRANSLATING": 90},
        default_stage_timeout_seconds=60,
    )

    breach = watchdog.check(progress_path, now=121.0)

    assert breach is not None
    assert breach.kind == "STARTUP_HEARTBEAT_MISSING"
    assert breach.stage == "STARTING"


def test_watchdog_stops_same_stage_despite_fresh_liveness_heartbeat(tmp_path):
    progress_path = tmp_path / "caption-progress.json"
    _write_progress(
        progress_path,
        stage="TRANSLATING",
        updated_at=160.0,
        stage_started_at=100.0,
    )
    watchdog = _CaptionProgressWatchdog(
        started_at=100.0,
        startup_timeout_seconds=20,
        heartbeat_timeout_seconds=30,
        stage_timeout_seconds={"TRANSLATING": 60},
        default_stage_timeout_seconds=90,
    )

    breach = watchdog.check(progress_path, now=161.0)

    assert breach is not None
    assert breach.kind == "STAGE_TIMEOUT"
    assert breach.stage == "TRANSLATING"
    assert breach.limit_seconds == 60


def test_watchdog_stops_when_stage_heartbeat_goes_stale(tmp_path):
    progress_path = tmp_path / "caption-progress.json"
    _write_progress(
        progress_path,
        stage="VIDEO_RENDERING",
        updated_at=180.0,
        stage_started_at=150.0,
    )
    watchdog = _CaptionProgressWatchdog(
        started_at=100.0,
        startup_timeout_seconds=20,
        heartbeat_timeout_seconds=30,
        stage_timeout_seconds={"VIDEO_RENDERING": 120},
        default_stage_timeout_seconds=90,
    )

    breach = watchdog.check(progress_path, now=211.0)

    assert breach is not None
    assert breach.kind == "HEARTBEAT_STALE"
    assert breach.stage == "VIDEO_RENDERING"
    assert breach.limit_seconds == 30

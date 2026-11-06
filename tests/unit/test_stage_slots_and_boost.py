"""阶段资源槽与插队 boost。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from video_processing.core import stage_slots as slots


@pytest.fixture
def slot_dirs(tmp_path, monkeypatch):
    cfg = tmp_path / "ffmpeg-slot"
    st = tmp_path / "stage-slots"
    cfg.mkdir()
    st.mkdir()
    monkeypatch.setattr(slots, "_CONFIG_DIRECTORY", cfg)
    monkeypatch.setattr(slots, "_SLOT_DIRECTORY", st)
    slots.save_config(slots.DEFAULTS)
    return cfg, st


def test_config_hot_reload_and_flag(slot_dirs):
    assert slots.stage_slots_enabled() is True
    slots.save_config({**slots.DEFAULTS, "enable_stage_resource_slots": False})
    assert slots.stage_slots_enabled() is False
    saved = slots.save_config({
        **slots.DEFAULTS,
        "enable_stage_resource_slots": True,
        "stage_slots": {**slots.DEFAULTS["stage_slots"], "copywriting": 3},
    })
    assert saved["stage_slots"]["copywriting"] == 3
    assert slots.load_config()["stage_slots"]["copywriting"] == 3


def test_nonblocking_acquire_and_release(slot_dirs):
    first = slots.StageSlot("download")
    assert first.try_acquire() is True
    second = slots.StageSlot("download")
    assert second.try_acquire() is False
    with pytest.raises(slots.StageSlotUnavailable):
        second.acquire(blocking=False)
    first.release()
    assert second.try_acquire() is True
    second.release()


def test_copywriting_parallel_two(slot_dirs):
    slots.save_config({
        **slots.DEFAULTS,
        "stage_slots": {**slots.DEFAULTS["stage_slots"], "copywriting": 2},
    })
    a = slots.StageSlot("copywriting")
    b = slots.StageSlot("copywriting")
    c = slots.StageSlot("copywriting")
    assert a.try_acquire() and b.try_acquire()
    assert c.try_acquire() is False
    a.release()
    assert c.try_acquire() is True
    b.release()
    c.release()


def test_asr_ffmpeg_combined_cap(slot_dirs):
    slots.save_config({
        **slots.DEFAULTS,
        "stage_slots": {
            **slots.DEFAULTS["stage_slots"],
            "asr": 2,
            "ffmpeg": 2,
            "asr_ffmpeg_combined_max": 2,
        },
    })
    asr = slots.StageSlot("asr")
    ffmpeg = slots.StageSlot("ffmpeg")
    assert asr.try_acquire()
    assert ffmpeg.try_acquire()
    extra = slots.StageSlot("asr")
    assert extra.try_acquire() is False
    asr.release()
    ffmpeg.release()


def test_hold_stages_order_and_rollback(slot_dirs):
    slots.save_config({
        **slots.DEFAULTS,
        "stage_slots": {**slots.DEFAULTS["stage_slots"], "asr": 1, "ffmpeg": 1, "asr_ffmpeg_combined_max": 2},
    })
    blocker = slots.StageSlot("ffmpeg")
    assert blocker.try_acquire()
    with pytest.raises(slots.StageSlotUnavailable):
        with slots.hold_stages(["asr", "ffmpeg"], blocking=False):
            pass
    # ffmpeg 已占用时 asr 曾被临时占用；失败回滚后应可再次取得 asr
    probe = slots.StageSlot("asr")
    assert probe.try_acquire() is True
    probe.release()
    blocker.release()


def test_boost_ordering(tmp_path):
    from video_processing.db.database import PipelineDB

    db = PipelineDB(str(tmp_path / "pipeline.db"))
    assert db.add_video("aaaaaaaaaaa", "title-a", "channel", score=90, source="MANUAL")
    assert db.add_video("bbbbbbbbbbb", "title-b", "channel", score=90, source="MANUAL")
    assert db.boost_video_queue("bbbbbbbbbbb") is True
    rows = db.get_high_score_pending_videos(min_score=75, limit=5)
    assert [r["youtube_id"] for r in rows][:2] == ["bbbbbbbbbbb", "aaaaaaaaaaa"]
    assert rows[0]["queue_boost_at"] is not None


def test_normalize_rejects_zero_and_keeps_bounds(slot_dirs):
    raw = {"ffmpeg_slots": 0, "enable_stage_resource_slots": "yes", "stage_slots": {"copywriting": 999}}
    cfg = slots.normalize_config(raw)
    assert cfg["ffmpeg_slots"] == 1
    assert cfg["enable_stage_resource_slots"] is True  # invalid type -> default True
    assert cfg["stage_slots"]["copywriting"] == 2


def test_enter_combined_asr_ffmpeg_slot_nonblocking(slot_dirs):
    """回归：asr_ffmpeg 组合槽不得因未定义变量崩溃（7195 线上 NameError）。"""
    from unittest.mock import MagicMock
    from video_processing.pipeline_manager import PipelineManager
    pm = PipelineManager.__new__(PipelineManager)
    pm._defer_for_resource_slot = MagicMock()
    active = []
    handle = pm._enter_stage_slot("asr_ffmpeg", "vid", "title", active=active)
    assert handle not in (None, "legacy") and active == [handle]
    blocked = pm._enter_stage_slot("asr_ffmpeg", "vid2", "title2", active=[])
    assert blocked is None
    pm._defer_for_resource_slot.assert_called_once()
    pm._exit_stage_slot(handle, active)
    assert active == []

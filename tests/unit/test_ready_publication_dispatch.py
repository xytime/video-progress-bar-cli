"""就绪发布独立性、跨进程互斥与缓存恢复的回归证据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-23 | Codex | 验证加工锁不阻塞发布、原子领取与失败缓存保护。 |
"""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from config.settings import settings
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy, read_lease_owner
from video_processing.core.wechat_session_lock import WeChatSessionLock, WeChatSessionLockBusy
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing.utils.file_utils import clean_partial_downloads, media_streams
from scripts.run_ready_publications import dispatch_once


def manager_at(tmp_path):
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    manager._ORIG_VIDEO_DIR = tmp_path / "original_video"
    manager._ORIG_VIDEO_DIR.mkdir(exist_ok=True)
    return manager


def test_ready_publish_runs_while_another_process_holds_pipeline_lock(tmp_path, monkeypatch):
    manager = manager_at(tmp_path)
    manager.db.add_video("ready", "Ready", "channel", score=90)
    manager.db.mark_video_ready_for_publication("ready")
    (tmp_path / "ready_title.txt").write_text("待发布标题")
    (tmp_path / "ready_copy.txt").write_text("待发布文案")
    monkeypatch.setattr(type(settings), "is_us_market_guard_window", lambda _: True)
    monkeypatch.setattr(type(settings), "is_public_publish_window", lambda _: False)
    monkeypatch.setattr(settings, "wechat_publishing_paused", False)
    # 三个边界：产物验证、审查结果、平台传输；调度、数据库及 OS 锁均真实。
    monkeypatch.setattr(manager, "_prepared_submission_checkpoint_error", lambda _: None)
    monkeypatch.setattr(manager, "_check_censorship", lambda *a, **kw: False)
    submitted = []
    monkeypatch.setattr(manager, "_publish_prepared_assets", lambda video, *args: submitted.append(video["youtube_id"]))
    child = subprocess.Popen([sys.executable, "-c", "import fcntl,sys; f=open(sys.argv[1],'w'); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.read()", str(tmp_path / "pipeline.lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        assert dispatch_once(manager) == 1
        assert submitted == ["ready"]
        assert child.poll() is None
        assert manager.db.get_video_by_youtube_id("ready")["status"] == "PUBLISH_PRECHECK"
    finally:
        child.communicate(timeout=5)


def test_two_claimants_only_one_crosses_publish_boundary(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("one", "One", "channel", score=90)
    db.mark_video_ready_for_publication("one")
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda pid: db.claim_video_for_publication("one", pid), [101, 102]))
    assert sorted(claimed) == [False, True]
    assert db.get_tab_counts()["ready"] == 1
    assert db.get_tab_counts()["queue"] == 0
    rows, count = db.get_paginated_videos("ready", 1, 20)
    assert count == 1 and rows[0]["youtube_id"] == "one"


def test_precheck_orphan_recovers_without_losing_ready_artifacts(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("one", "One", "channel", score=90)
    db.mark_video_ready_for_publication("one")
    assert db.claim_video_for_publication("one", 123)
    assert db.recover_orphaned_pre_submission_task("one", expected_process_pid=123, error_msg="worker exited") == "PENDING"
    row = db.get_video_by_youtube_id("one")
    assert row["preparation_ready"] == 1 and row["publication_ready_at"]
    assert db.claim_video_for_publication("one", 456)


def test_ready_low_score_is_visible_only_in_ready_and_cannot_be_cleared(tmp_path):
    db = PipelineDB(str(tmp_path / "pipeline.db"))
    db.add_video("ready-low", "Ready", "channel", score=70)
    db.mark_video_ready_for_publication("ready-low")
    assert db.get_tab_counts()["ready"] == 1
    assert db.get_tab_counts()["waitlist"] == 0
    assert db.get_paginated_videos("waitlist", 1, 20)[1] == 0
    assert db.get_waitlist_clearable_ids() == []


def test_session_busy_keeps_ready_state_and_does_not_redownload(tmp_path, monkeypatch):
    manager = manager_at(tmp_path)
    manager.db.add_video("one", "One", "channel", score=90)
    manager.db.mark_video_ready_for_publication("one")
    (tmp_path / "one_title.txt").write_text("标题")
    (tmp_path / "one_copy.txt").write_text("文案")
    monkeypatch.setattr(manager, "_prepared_submission_checkpoint_error", lambda _: None)
    monkeypatch.setattr(manager, "_check_censorship", lambda *a, **kw: False)
    calls = []

    def occupied(video, *args):
        calls.append(video["youtube_id"])
        manager.db.defer_ready_publication("one", "同账号浏览器会话占用")

    monkeypatch.setattr(manager, "_publish_prepared_assets", occupied)
    assert dispatch_once(manager) == 1
    first = manager.db.get_video_by_youtube_id("one")
    assert dispatch_once(manager) == 1
    second = manager.db.get_video_by_youtube_id("one")
    assert first["publication_ready_at"] == second["publication_ready_at"]
    assert second["status"] == "PENDING" and second["preparation_ready"] == 1
    assert calls == ["one", "one"]


def test_censorship_hit_blocks_ready_submission(tmp_path, monkeypatch):
    manager = manager_at(tmp_path)
    manager.db.add_video("one", "One", "channel", score=90)
    manager.db.mark_video_ready_for_publication("one")
    (tmp_path / "one_title.txt").write_text("标题")
    (tmp_path / "one_copy.txt").write_text("文案")
    monkeypatch.setattr(manager, "_prepared_submission_checkpoint_error", lambda _: None)
    monkeypatch.setattr(manager, "_check_censorship", lambda *a, **kw: True)
    monkeypatch.setattr(manager, "_publish_prepared_assets", lambda *a: pytest.fail("审查命中不得调用平台"))
    dispatch_once(manager)


def test_actual_task_lock_owner_and_publication_priority(tmp_path):
    priority = tmp_path / "wechat_publish_priority.lock"
    state = tmp_path / "wechat_state.json"
    with TaskLease(priority, video="one", stage="提交"):
        assert read_lease_owner(priority)["video"] == "one"
        with pytest.raises(TaskLeaseBusy):
            with TaskLease(priority):
                pass
        with pytest.raises(WeChatSessionLockBusy):
            with WeChatSessionLock(state, purpose="保活"):
                pass
        with WeChatSessionLock(state, purpose="发布", video="one") as session:
            assert read_lease_owner(session.lock_path)["video"] == "one"
    assert read_lease_owner(priority) == {}
    with WeChatSessionLock(state, purpose="保活"):
        pass


def test_cache_gc_protects_failed_pending_and_unknown_sources(tmp_path):
    manager = manager_at(tmp_path)
    for yid, status in [("failed", "FAILED"), ("ready", "PENDING"), ("done", "PUBLISHED")]:
        manager.db.add_video(yid, yid, "channel", score=90)
        manager.db.update_video_status(yid, status)
    with manager.db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET updated_at = datetime('now', '-5 days')")
        conn.commit()
    for yid in ("failed", "ready", "done", "unknown"):
        source = manager._ORIG_VIDEO_DIR / f"{yid}.mp4"
        source.write_bytes(b"source")
        os.utime(source, (0, 0))
    manager._evict_original_video_dir()
    assert {p.stem for p in manager._ORIG_VIDEO_DIR.iterdir()} == {"failed", "ready", "unknown"}


def test_fallback_preserves_valid_video_and_resumable_audio(tmp_path):
    video = tmp_path / "one.f136.mp4"
    subprocess.run(["/opt/homebrew/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=size=64x64:rate=10", "-t", "1", "-c:v", "libx264", str(video)], check=True)
    partial = tmp_path / "one.f140.m4a.part"
    partial.write_bytes(b"partial-audio")
    broken = tmp_path / "one.f141.m4a"
    broken.write_bytes(b"invalid-media")
    clean_partial_downloads(tmp_path, "one")
    assert media_streams(video) == {"video"}
    assert partial.read_bytes() == b"partial-audio"
    assert not broken.exists() and list(tmp_path.glob("one.f141.m4a.invalid-*"))


@pytest.mark.parametrize("stderr", ["fixture copy failure", ""])
def test_actual_original_survives_copy_failure_and_retry_without_downloader(tmp_path, monkeypatch, stderr):
    manager = manager_at(tmp_path)
    source = manager._ORIG_VIDEO_DIR / "cached.mp4"
    subprocess.run(["/opt/homebrew/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:rate=30", "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "2", "-c:v", "mpeg4", "-q:v", "2", "-c:a", "aac", str(source)], check=True)
    original = source.read_bytes()
    assert len(original) > 50_000
    manager.db.add_video("cached", "测试源视频", "channel", score=90)
    monkeypatch.setattr(manager, "_check_censorship", lambda *a, **kw: False)
    monkeypatch.setattr(manager, "send_telegram_msg", lambda *a, **kw: None)
    calls = []

    def fail_copy(cmd, *args, **kwargs):
        assert any(str(part).endswith("copywriter.py") for part in cmd), f"意外启动下载或其他阶段：{cmd}"
        calls.append(cmd)
        raise subprocess.CalledProcessError(1, cmd, stderr=stderr)

    monkeypatch.setattr(manager, "_run_tracked", fail_copy)
    for _ in range(2):
        video = manager.db.get_video_by_youtube_id("cached")
        video["disable_slicing"] = 1
        manager._process_single_video(video)
        result = manager.db.get_video_by_youtube_id("cached")
        assert result["status"] == "FAILED"
        assert result["error_msg"]
        assert source.read_bytes() == original
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [b"", b"tiny-container", b"invalid-container" * 5000])
def test_invalid_original_is_rejected_without_mutation_during_submission(tmp_path, payload):
    manager = manager_at(tmp_path)
    source = manager._ORIG_VIDEO_DIR / "broken.mp4"
    source.write_bytes(payload)
    assert manager._find_downloaded_video("broken", quarantine_invalid=False) is None
    assert source.exists()
    assert manager._find_downloaded_video("broken") is None
    assert not source.exists()
    assert list(manager._ORIG_VIDEO_DIR.glob("broken.mp4.invalid-*"))


def test_review_copy_delivery_does_not_hold_ready_dispatcher(tmp_path, monkeypatch):
    manager = manager_at(tmp_path)
    manager.db.add_video("accepted", "Accepted", "channel", score=90)
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(manager, "send_telegram_msg", lambda *a, **kw: None)

    def slow_delivery(*args):
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(manager, "_send_wechat_submission_review_material_sync", slow_delivery)
    try:
        with ThreadPoolExecutor(max_workers=1) as caller:
            result = caller.submit(manager._mark_wechat_submission_under_review, "accepted", "accepted",
                                   evidence_path=None, reason="platform accepted", submission_confirmed=True)
            result.result(timeout=2)
            assert started.wait(2)
            assert not release.is_set()
            assert manager.db.get_wechat_publication("accepted") is not None
    finally:
        release.set()
        manager.wait_for_review_notifications(timeout=5)

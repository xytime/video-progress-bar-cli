"""四支柱优化架构单测：
1. Pillar 1: 下载引擎翻转（原生 yt-dlp 首选，curl 外部下载器异常与产物验真回退）
2. Pillar 2: process_high_score_videos 单任务懒抢占（Lazy Claiming、防紧凑死循环、盘中开盘回滚）
3. Pillar 3: Web 进程生命周期与看门狗加固（Popen + PID 追踪，保护存活进程与持锁管线）
4. Pillar 4: 视频号审核物料异步通知（后台线程派发，lifecycle wait 保护）

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-23 | Antigravity | 新增四支柱优化核心契约与边缘场景隔离单测 |
| 1.2.0 | 2026-09-23 | Codex | 下载验真测试使用真实音视频；验证回退保留续传缓存。 |
| 1.1.0 | 2026-09-23 | Antigravity | 补充产物验真 (<50KB) 回退、损坏文件清理、死循环防护与盘中开盘回滚单测 |
"""

import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def valid_media(tmp_path):
    path = tmp_path / "fixture.mp4"
    subprocess.run(["/opt/homebrew/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:rate=30", "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "2", "-c:v", "mpeg4", "-q:v", "2", "-c:a", "aac", str(path)], check=True)
    return path.read_bytes()

from config.settings import settings
from video_processing.pipeline_manager import PipelineManager
from video_processing.utils.file_utils import clean_partial_downloads


# ── Pillar 1: 下载引擎翻转 ────────────────────────────────────────────────────────


def test_download_engine_inversion_native_success(tmp_path, monkeypatch, valid_media):
    """原生 yt-dlp 成功时直接完成下载，不调用 curl 外部下载器。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    class StopAfterDownload(Exception):
        pass

    manager._archive_original_video = MagicMock(side_effect=StopAfterDownload)
    manager.db.update_video_status = MagicMock()
    manager._ensure_source_subtitle_preflight = MagicMock(return_value=True)

    executed_cmds = []

    def fake_run_tracked(cmd, yid, **kwargs):
        executed_cmds.append(list(cmd))
        (tmp_path / f"{yid}.mp4").write_bytes(valid_media)

    manager._run_tracked = fake_run_tracked

    video = {
        "youtube_id": "test1234567",
        "title": "Test Title",
        "status": "PENDING",
        "score": 80,
    }

    monkeypatch.setattr(manager, "_check_censorship", lambda *args, **kwargs: False)

    try:
        manager._process_single_video(video)
    except StopAfterDownload:
        pass

    assert len(executed_cmds) == 1
    cmd = executed_cmds[0]
    assert "--downloader" not in cmd
    assert "--downloader-args" not in cmd
    assert "--force-ipv4" in cmd
    assert "-S" in cmd and "vcodec:h264" in cmd


def test_download_engine_inversion_fallback_to_curl_on_error(tmp_path, monkeypatch, valid_media):
    """原生 yt-dlp 抛出异常时保留续传分片并降级回退至 curl 下载器。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path

    class StopAfterDownload(Exception):
        pass

    manager._archive_original_video = MagicMock(side_effect=StopAfterDownload)
    manager.db.update_video_status = MagicMock()
    manager._ensure_source_subtitle_preflight = MagicMock(return_value=True)

    # 预设一个失败时的残余分片
    stale_part = tmp_path / "fail1234567.f137.mp4.part"
    stale_part.write_bytes(b"corrupt")

    executed_cmds = []
    call_count = 0

    def fake_run_tracked(cmd, yid, **kwargs):
        nonlocal call_count
        call_count += 1
        executed_cmds.append(list(cmd))
        if call_count == 1:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"SSL EOF error")
        (tmp_path / f"{yid}.mp4").write_bytes(valid_media)

    manager._run_tracked = fake_run_tracked

    video = {
        "youtube_id": "fail1234567",
        "title": "Fail Title",
        "status": "PENDING",
        "score": 80,
    }
    monkeypatch.setattr(manager, "_check_censorship", lambda *args, **kwargs: False)

    try:
        manager._process_single_video(video)
    except StopAfterDownload:
        pass

    assert len(executed_cmds) == 2
    assert "--downloader" not in executed_cmds[0]
    assert "--downloader" in executed_cmds[1]
    assert "curl" in executed_cmds[1]
    assert stale_part.read_bytes() == b"corrupt"


def test_download_engine_inversion_fallback_on_corrupt_or_missing_file(tmp_path, monkeypatch, valid_media):
    """原生 yt-dlp 虽返回 0 但未生成有效视频文件 (如 <50KB HTML 错误页) 时，触发降级回退。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path

    class StopAfterDownload(Exception):
        pass

    manager._archive_original_video = MagicMock(side_effect=StopAfterDownload)
    manager.db.update_video_status = MagicMock()
    manager._ensure_source_subtitle_preflight = MagicMock(return_value=True)

    executed_cmds = []
    call_count = 0

    def fake_run_tracked(cmd, yid, **kwargs):
        nonlocal call_count
        call_count += 1
        executed_cmds.append(list(cmd))
        if call_count == 1:
            # 原生 yt-dlp 退出码为 0，但生成了损坏小文件 (10KB)
            (tmp_path / f"{yid}.mp4").write_bytes(b"x" * 10_000)
            return
        # 二次 curl 下载成功生成有效大文件
        (tmp_path / f"{yid}.mp4").write_bytes(valid_media)

    manager._run_tracked = fake_run_tracked

    video = {
        "youtube_id": "corrupt12345",
        "title": "Corrupt Small File Title",
        "status": "PENDING",
        "score": 80,
    }
    monkeypatch.setattr(manager, "_check_censorship", lambda *args, **kwargs: False)

    try:
        manager._process_single_video(video)
    except StopAfterDownload:
        pass

    assert len(executed_cmds) == 2
    # 第一次原生，第二次 curl
    assert "--downloader" not in executed_cmds[0]
    assert "--downloader" in executed_cmds[1]
    assert (tmp_path / "corrupt12345.mp4").read_bytes() == valid_media


def test_clean_partial_downloads_comprehensive(tmp_path):
    """clean_partial_downloads 保留续传文件，仅隔离损坏视频。"""
    yid = "clean_test_yid"
    f_part = tmp_path / f"{yid}.f137"
    f_part.write_bytes(b"part_data")
    ytdl_file = tmp_path / f"{yid}.ytdl"
    ytdl_file.write_bytes(b"ytdl_data")
    temp_file = tmp_path / f"{yid}.video.temp"
    temp_file.write_bytes(b"temp_data")
    corrupt_mp4 = tmp_path / f"{yid}.mp4"
    corrupt_mp4.write_bytes(b"corrupt" * 100)  # 700 bytes <= 50,000
    valid_other = tmp_path / "other_video.mp4"
    valid_other.write_bytes(b"valid" * 20_000)  # 100KB

    cleaned = clean_partial_downloads(tmp_path, yid)

    assert f_part.exists()
    assert ytdl_file.exists()
    assert temp_file.exists()
    assert not corrupt_mp4.exists()
    assert valid_other.exists()


def test_pipeline_agent_download_inversion_fallback(tmp_path):
    """PipelineAgent.download_video 优先原生下载，失败回退 curl。"""
    from bot.pipeline_agent import PipelineAgent

    with patch("bot.pipeline_agent.settings.gemini_api_key", "fake_key"):
        agent = PipelineAgent(bot=None, loop=None, chat_id=123)
    agent.output_dir = tmp_path

    recorded_cmds = []
    run_count = 0

    def fake_run(cmd, *args, **kwargs):
        nonlocal run_count
        run_count += 1
        recorded_cmds.append(list(cmd))
        if run_count == 1:
            raise subprocess.CalledProcessError(1, cmd, stderr="Network reset")
        (tmp_path / "agent_dl_123.mp4").write_bytes(b"0" * 60_000)
        return MagicMock(returncode=0)

    with patch("bot.pipeline_agent.subprocess.run", side_effect=fake_run):
        res = agent.download_video("agent_dl_123")
        assert '"ok": true' in res.lower()

    assert len(recorded_cmds) == 2
    assert "--downloader" not in recorded_cmds[0]
    assert "--downloader" in recorded_cmds[1]
    assert "curl" in recorded_cmds[1]


# ── Pillar 2: 单任务懒抢占（Lazy Claiming） ──────────────────────────────────────


def test_lazy_claiming_in_process_high_score_videos(tmp_path, monkeypatch):
    """process_high_score_videos 每轮仅 claim 1 个就绪任务并立即处理，后续任务保持 PENDING。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager.send_telegram_msg = MagicMock()

    v1 = {"youtube_id": "yid_1", "slice_index": 0, "score": 90, "status": "PENDING"}
    v2 = {"youtube_id": "yid_2", "slice_index": 0, "score": 85, "status": "PENDING"}
    v3 = {"youtube_id": "yid_3", "slice_index": 0, "score": 80, "status": "PENDING"}

    db_videos = {"yid_1": "PENDING", "yid_2": "PENDING", "yid_3": "PENDING"}
    claim_history = []
    process_history = []

    def fake_get_pending(min_score=75, limit=15, **kwargs):
        return [
            {"youtube_id": yid, "slice_index": 0, "score": 80, "status": status}
            for yid, status in db_videos.items()
            if status == "PENDING"
        ]

    def fake_claim(yid, slice_index=0):
        if db_videos.get(yid) == "PENDING":
            db_videos[yid] = "DOWNLOADING"
            claim_history.append((yid, dict(db_videos)))
            return True
        return False

    def fake_process_single(video, submission_only=False):
        yid = video["youtube_id"]
        process_history.append((yid, dict(db_videos)))
        db_videos[yid] = "PUBLISHED"

    manager.db.get_high_score_pending_videos = fake_get_pending
    manager.db.claim_video_for_processing = fake_claim
    manager._process_single_video = fake_process_single
    monkeypatch.setattr(manager, "_is_public_publish_window", lambda reason: True)

    manager.process_high_score_videos(limit=3)

    assert len(process_history) == 3
    v1_process_time_state = process_history[0][1]
    assert v1_process_time_state["yid_1"] == "DOWNLOADING"
    assert v1_process_time_state["yid_2"] == "PENDING"
    assert v1_process_time_state["yid_3"] == "PENDING"

    v2_process_time_state = process_history[1][1]
    assert v2_process_time_state["yid_2"] == "DOWNLOADING"
    assert v2_process_time_state["yid_3"] == "PENDING"


def test_lazy_claiming_prevents_infinite_reprocessing_loop(tmp_path, monkeypatch):
    """当任务加工后回退为 PENDING（如源字幕缺失），本轮批次不再重复认领同一任务。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager.send_telegram_msg = MagicMock()

    db_videos = {"deferred_yid": "PENDING"}
    attempt_count = 0

    def fake_get_pending(min_score=75, limit=15, **kwargs):
        return [
            {"youtube_id": yid, "slice_index": 0, "score": 80, "status": status}
            for yid, status in db_videos.items()
            if status == "PENDING"
        ]

    def fake_claim(yid, slice_index=0):
        return True

    def fake_process_single(video, submission_only=False):
        nonlocal attempt_count
        attempt_count += 1
        # 任务在此次处理中被重置回 PENDING
        db_videos[video["youtube_id"]] = "PENDING"

    manager.db.get_high_score_pending_videos = fake_get_pending
    manager.db.claim_video_for_processing = fake_claim
    manager._process_single_video = fake_process_single
    monkeypatch.setattr(manager, "_is_public_publish_window", lambda reason: True)

    manager.process_high_score_videos(limit=5)

    # 验证：尽管 db 仍处于 PENDING 且 batch limit=5，该任务只被尝试 1 次，不发生死循环
    assert attempt_count == 1


def test_market_guard_midway_reverts_claimed_video_to_pending(tmp_path, monkeypatch):
    """认领后若美股盘中开盘，且任务非 preparation_ready，自动回滚认领为 PENDING。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager.send_telegram_msg = MagicMock()

    target_video = {"youtube_id": "guard_yid", "slice_index": 0, "score": 85, "status": "PENDING"}
    status_updates = []

    def fake_update_status(yid, status, **kwargs):
        status_updates.append((yid, status, kwargs.get("error_msg")))

    manager.db.get_high_score_pending_videos = MagicMock(return_value=[target_video])
    manager.db.claim_video_for_processing = MagicMock(return_value=True)
    manager.db.update_video_status = fake_update_status
    manager._process_single_video = MagicMock()

    # 第一次查询时非盘中，认领后开盘
    guard_calls = 0

    def fake_market_guard():
        nonlocal guard_calls
        guard_calls += 1
        return guard_calls > 2

    monkeypatch.setattr(type(settings), "is_us_market_guard_window", lambda _self: fake_market_guard())
    monkeypatch.setattr(manager, "_is_public_publish_window", lambda reason: True)

    manager.process_high_score_videos(limit=1)

    # 验证：未启动重负载加工，且已认领的任务被回滚为 PENDING
    manager._process_single_video.assert_not_called()
    assert any(yid == "guard_yid" and status == "PENDING" for yid, status, _ in status_updates)


# ── Pillar 3: Web 进程生命周期与看门狗加固 ───────────────────────────────────────


def test_trigger_video_async_popen_and_pid_tracking():
    """_trigger_video_async 使用 Popen 启动独立进程组并记录/清理 PID。"""
    import web.app as web_app

    video = {"youtube_id": "async_yid_test", "slice_index": 0}
    pid_updates = []

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.communicate.return_value = ("", "")

    with patch.object(web_app.db, "update_process_pid", side_effect=lambda yid, pid, slice_index=0: pid_updates.append((yid, pid, slice_index))), \
         patch("subprocess.Popen", return_value=mock_proc) as mock_popen:

        web_app._trigger_video_async(video)
        time.sleep(0.1)

    mock_popen.assert_called_once()
    assert mock_popen.call_args.kwargs.get("start_new_session") is True
    assert ("async_yid_test", 12345, 0) in pid_updates
    assert ("async_yid_test", None, 0) in pid_updates


def test_recover_orphaned_pre_submission_tasks_guard():
    """看门狗回收逻辑守卫：
    1. 进程组活着时不回收
    2. PID 为空但管线锁被持有时不回收
    3. 进程组已死且未持锁时正常回收
    """
    import web.app as web_app

    mock_video_active = {"youtube_id": "active_yid", "slice_index": 0, "process_pid": 8888, "status": "DOWNLOADING"}
    mock_video_no_pid = {"youtube_id": "no_pid_yid", "slice_index": 0, "process_pid": None, "status": "DOWNLOADING"}
    mock_video_dead = {"youtube_id": "dead_yid", "slice_index": 0, "process_pid": 9999, "status": "DOWNLOADING"}

    # 1. PID 8888 进程组活着 -> 不回收
    with patch.object(web_app.db, "get_stale_pre_submission_processing_videos", return_value=[mock_video_active]), \
         patch.object(web_app, "_process_group_alive", return_value=True), \
         patch.object(web_app, "_is_pipeline_manager_running", return_value=False), \
         patch.object(web_app.db, "recover_orphaned_pre_submission_task") as mock_recover:
        assert web_app._recover_orphaned_pre_submission_tasks() == 0
        mock_recover.assert_not_called()

    # 2. PID 为 None，但 pipeline.lock 正在被持有 -> 不回收
    with patch.object(web_app.db, "get_stale_pre_submission_processing_videos", return_value=[mock_video_no_pid]), \
         patch.object(web_app, "_process_group_alive", return_value=False), \
         patch.object(web_app, "_is_pipeline_manager_running", return_value=True), \
         patch.object(web_app.db, "recover_orphaned_pre_submission_task") as mock_recover:
        assert web_app._recover_orphaned_pre_submission_tasks() == 0
        mock_recover.assert_not_called()

    # 3. PID 9999 进程组已死，管线未持锁 -> 正常回收
    with patch.object(web_app.db, "get_stale_pre_submission_processing_videos", return_value=[mock_video_dead]), \
         patch.object(web_app, "_process_group_alive", return_value=False), \
         patch.object(web_app, "_is_pipeline_manager_running", return_value=False), \
         patch.object(web_app.db, "recover_orphaned_pre_submission_task", return_value="PENDING") as mock_recover:
        assert web_app._recover_orphaned_pre_submission_tasks() == 1
        mock_recover.assert_called_once_with(
            "dead_yid",
            expected_process_pid=9999,
            error_msg="DOWNLOADING 子进程已不存在；自动有界回收，尚未触发视频号提交。",
            slice_index=0,
        )


# ── Pillar 4: 视频号审核物料异步通知 ──────────────────────────────────────────────


def test_async_wechat_submission_review_notification(tmp_path):
    """_send_wechat_submission_review_material 默认后台异步派发，且支持同步模式与等待。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path

    sent_calls = []

    def fake_sync_send(prefix, title):
        time.sleep(0.05)
        sent_calls.append((prefix, title))
        return True

    manager._send_wechat_submission_review_material_sync = fake_sync_send

    # 1. 默认异步调用：立即返回 threading.Thread，不阻塞主线程
    t_start = time.time()
    result = manager._send_wechat_submission_review_material("prefix_async", "Async Title")
    elapsed = time.time() - t_start

    assert isinstance(result, threading.Thread)
    assert elapsed < 0.04

    # 等待异步任务完成
    manager.wait_for_review_notifications(timeout=1.0)
    assert ("prefix_async", "Async Title") in sent_calls

    # 2. 显式同步调用：sync=True 阻塞执行并直接返回 bool
    sync_res = manager._send_wechat_submission_review_material("prefix_sync", "Sync Title", sync=True)
    assert sync_res is True
    assert ("prefix_sync", "Sync Title") in sent_calls


def test_daily_job_lifecycle_waits_for_review_notifications(tmp_path, monkeypatch):
    """_run_daily_job_unlocked 结束前显式调用 wait_for_review_notifications。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager.wait_for_review_notifications = MagicMock()
    manager.reconcile_wechat_under_review = MagicMock(return_value=0)
    manager.score_pending_videos = MagicMock()
    manager.process_high_score_videos = MagicMock()
    manager._check_wechat_delivery_health = MagicMock()
    manager._dispatch_wechat_interaction_worker = MagicMock()
    monkeypatch.setattr(settings, "wechat_publishing_paused", True)
    monkeypatch.setattr(settings, "enable_kuaishou_browser_publishing", False)
    monkeypatch.setattr(settings, "enable_douyin_browser_publishing", False)

    manager._run_daily_job_unlocked()

    manager.wait_for_review_notifications.assert_called_once_with(timeout=30.0)

"""四支柱优化架构单测：
1. Pillar 1: 下载引擎翻转（原生 yt-dlp 首选，curl 外部下载器异常与产物验真回退）
2. Pillar 2: process_high_score_videos 单任务懒抢占（Lazy Claiming、防紧凑死循环、盘中开盘回滚）
3. Pillar 3: Web 进程生命周期与看门狗加固（Popen + PID 追踪，保护存活进程与持锁管线）
4. Pillar 4: 视频号审核物料异步通知（后台线程派发，lifecycle wait 保护）

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-09-23 | Antigravity | [Code Review Fix] 懒抢占测试接入真实 SQLite 校验 PROCESSING；看门狗测试接入真实进程与 PID 过滤；增加取消信号/SystemExit 拦截、自杀防御与特定审核抢占单测 |
| 1.2.0 | 2026-09-23 | Codex | 下载验真测试使用真实音视频；验证回退保留续传缓存。 |
| 1.1.0 | 2026-09-23 | Antigravity | 补充产物验真 (<50KB) 回退、损坏文件清理、死循环防护与盘中开盘回滚单测 |
| 1.0.0 | 2026-09-23 | Antigravity | 新增四支柱优化核心契约与边缘场景隔离单测 |
"""

import os
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


def test_pipeline_agent_download_inversion_fallback(tmp_path, valid_media):
    """PipelineAgent.download_video 优先原生下载，产物不合格或失败时回退 curl。"""
    from bot.pipeline_agent import PipelineAgent

    with patch("bot.pipeline_agent.settings.gemini_api_key", "fake_key"):
        agent = PipelineAgent(bot=None, loop=None, chat_id=123)
    agent.output_dir = tmp_path

    _real_run = subprocess.run
    recorded_cmds = []
    run_count = 0

    def fake_run(cmd, *args, **kwargs):
        nonlocal run_count
        if any("ffprobe" in str(arg) for arg in cmd):
            return _real_run(cmd, *args, **kwargs)
        run_count += 1
        recorded_cmds.append(list(cmd))
        if run_count == 1:
            # 原生 runner 写入全零损坏文件（无有效音视频轨），验真失败触发回退
            (tmp_path / "agent_dl_123.mp4").write_bytes(b"0" * 60_000)
            return MagicMock(returncode=0)
        # 回退 curl 产出真实媒体，双轨校验通过
        (tmp_path / "agent_dl_123.mp4").write_bytes(valid_media)
        return MagicMock(returncode=0)

    with patch("bot.pipeline_agent.subprocess.run", side_effect=fake_run):
        res = agent.download_video("agent_dl_123")
        assert '"ok": true' in res.lower()

    assert len(recorded_cmds) == 2
    assert "--downloader" not in recorded_cmds[0]
    assert "--downloader" in recorded_cmds[1]
    assert "curl" in recorded_cmds[1]


def test_download_cancellation_by_signals_and_system_exit(tmp_path):
    """当子进程被外部信号或 SystemExit 取消，或回调标记取消时，严禁误触发降级回退重试。"""
    from video_processing.utils.download_strategy import (
        DownloadOptions,
        execute_download_with_fallback,
    )

    options = DownloadOptions(
        ytdlp_path="/fake/yt-dlp",
        url="https://youtu.be/cancel_test",
        output_template=str(tmp_path / "cancel.%(ext)s"),
    )

    # 1. 模拟外部 SIGTERM 取消 (returncode -15)
    run_calls = []
    clean_called = False

    def runner_sigterm(cmd, timeout=None):
        run_calls.append(cmd)
        raise subprocess.CalledProcessError(-15, cmd, stderr="Terminated by signal")

    def fake_cleaner():
        nonlocal clean_called
        clean_called = True

    with pytest.raises(InterruptedError) as exc_info:
        execute_download_with_fallback(
            options=options,
            runner=runner_sigterm,
            verifier=lambda: None,
            cleaner=fake_cleaner,
            total_timeout=60.0,
        )

    assert "cancelled by signal" in str(exc_info.value).lower()
    assert len(run_calls) == 1
    assert clean_called is True

    # 2. 模拟 SystemExit
    run_calls.clear()

    def runner_sysexit(cmd, timeout=None):
        run_calls.append(cmd)
        raise SystemExit(143)

    with pytest.raises(InterruptedError):
        execute_download_with_fallback(
            options=options,
            runner=runner_sysexit,
            verifier=lambda: None,
            cleaner=lambda: None,
            total_timeout=60.0,
        )
    assert len(run_calls) == 1

    # 3. 模拟 is_cancelled_callback 在降级前拦截
    run_calls.clear()
    is_cancelled = False

    def runner_transient_failure(cmd, timeout=None):
        nonlocal is_cancelled
        run_calls.append(cmd)
        is_cancelled = True
        raise RuntimeError("Transient network EOF")

    with pytest.raises(InterruptedError) as exc_info:
        execute_download_with_fallback(
            options=options,
            runner=runner_transient_failure,
            verifier=lambda: None,
            cleaner=lambda: None,
            total_timeout=60.0,
            is_cancelled_callback=lambda: is_cancelled,
        )
    assert len(run_calls) == 1
    assert "before fallback" in str(exc_info.value).lower()


# ── Pillar 2: 单任务懒抢占（Lazy Claiming） ──────────────────────────────────────


def test_lazy_claiming_in_process_high_score_videos(tmp_path, monkeypatch):
    """process_high_score_videos 每轮仅 claim 1 个就绪任务并立即处理，状态置为 PROCESSING，后续任务保持 PENDING。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager.send_telegram_msg = MagicMock()

    manager.db.add_video("yid_1", "Title 1", "test_channel", score=90)
    manager.db.add_video("yid_2", "Title 2", "test_channel", score=85)
    manager.db.add_video("yid_3", "Title 3", "test_channel", score=80)

    observed_states = []

    def fake_process_single(video, submission_only=False):
        yid = video["youtube_id"]
        v1 = manager.db.get_video_by_youtube_id("yid_1")["status"]
        v2 = manager.db.get_video_by_youtube_id("yid_2")["status"]
        v3 = manager.db.get_video_by_youtube_id("yid_3")["status"]
        observed_states.append((yid, {"yid_1": v1, "yid_2": v2, "yid_3": v3}))
        manager.db.update_video_status(yid, "PUBLISHED")

    manager._process_single_video = fake_process_single
    monkeypatch.setattr(manager, "_is_public_publish_window", lambda reason: True)

    manager.process_high_score_videos(limit=3)

    assert len(observed_states) == 3
    # 当 yid_1 正在被处理时，其状态必须为真实 DAL 置的 PROCESSING，且 yid_2/yid_3 仍处于 PENDING
    assert observed_states[0][0] == "yid_1"
    assert observed_states[0][1]["yid_1"] == "PROCESSING"
    assert observed_states[0][1]["yid_2"] == "PENDING"
    assert observed_states[0][1]["yid_3"] == "PENDING"

    # 当 yid_2 正在被处理时，yid_1 已 PUBLISHED，yid_2 为 PROCESSING，yid_3 仍为 PENDING
    assert observed_states[1][0] == "yid_2"
    assert observed_states[1][1]["yid_1"] == "PUBLISHED"
    assert observed_states[1][1]["yid_2"] == "PROCESSING"
    assert observed_states[1][1]["yid_3"] == "PENDING"


def test_lazy_claiming_prevents_infinite_reprocessing_loop(tmp_path, monkeypatch):
    """当任务加工后回退为 PENDING（如源字幕缺失），本轮批次不再重复认领同一任务。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager.send_telegram_msg = MagicMock()

    manager.db.add_video("deferred_yid", "Deferred Title", "test_channel", score=80)
    attempt_count = 0

    def fake_process_single(video, submission_only=False):
        nonlocal attempt_count
        attempt_count += 1
        # 模拟加工中回写 PENDING（例如源字幕检测缺失或外部避让）
        manager.db.update_video_status(video["youtube_id"], "PENDING")

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


def test_recover_orphaned_pre_submission_tasks_guard(tmp_path, monkeypatch):
    """看门狗回收逻辑守卫（使用真实 SQLite 与真实进程状态，不 mock 存活性判断）：
    1. 进程组活着时不回收
    2. PID 为空但管线锁被持有时不回收
    3. 进程组已死且未持锁时正常回收
    """
    import web.app as web_app
    from video_processing.db.database import PipelineDB

    test_db = PipelineDB(str(tmp_path / "watchdog_test.db"))
    monkeypatch.setattr(web_app, "db", test_db)

    # 启动一个立即退出的真实子进程以获取真实 dead_pid
    dead_proc = subprocess.Popen(["true"])
    dead_proc.wait()
    dead_pid = dead_proc.pid

    # 1. PID active (os.getpid() 正在运行 pytest/python) -> 不回收
    test_db.add_video("active_yid", "Active Video", "test_channel", score=80)
    test_db.update_video_status("active_yid", "DOWNLOADING")
    test_db.update_process_pid("active_yid", os.getpid())
    with test_db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET updated_at = datetime('now', '-30 minutes') WHERE youtube_id = 'active_yid'")

    # 2. PID 为空，管线持锁 -> 不回收
    test_db.add_video("no_pid_yid", "No PID Video", "test_channel", score=80)
    test_db.update_video_status("no_pid_yid", "DOWNLOADING")
    with test_db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET updated_at = datetime('now', '-30 minutes') WHERE youtube_id = 'no_pid_yid'")

    # 3. dead_pid 进程已死，且未持锁 -> 正常回收
    test_db.add_video("dead_yid", "Dead Video", "test_channel", score=80)
    test_db.update_video_status("dead_yid", "DOWNLOADING")
    test_db.update_process_pid("dead_yid", dead_pid)
    with test_db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET updated_at = datetime('now', '-30 minutes') WHERE youtube_id = 'dead_yid'")

    # 管线持锁：保护 PID 为空的排队任务
    monkeypatch.setattr(web_app, "_is_pipeline_manager_running", lambda: True)

    recovered = web_app._recover_orphaned_pre_submission_tasks(stale_minutes=20)
    assert recovered == 1

    # active_yid 存活，保持 DOWNLOADING
    assert test_db.get_video_by_youtube_id("active_yid")["status"] == "DOWNLOADING"
    # no_pid_yid 在管线持锁排队中，保持 DOWNLOADING
    assert test_db.get_video_by_youtube_id("no_pid_yid")["status"] == "DOWNLOADING"
    # dead_yid 进程已死亡，成功回收为 PENDING
    assert test_db.get_video_by_youtube_id("dead_yid")["status"] == "PENDING"


def test_process_group_alive_distinguishes_pid_and_pgid(monkeypatch):
    """看门狗 _process_group_alive 应正确识别 Worker PID、PGID，并防御系统守护进程 PID 复用。"""
    from web import app as web_app

    fake_ps_output = (
        "1001  1001 S python -m video_processing.pipeline_manager\n"
        "2002  1001 S yt-dlp https://youtu.be/xxx\n"
        "3003  3003 S /usr/sbin/systemstats --daemon\n"
    )

    def fake_run(cmd, *args, **kwargs):
        return MagicMock(stdout=fake_ps_output, returncode=0)

    monkeypatch.setattr("web.app.subprocess.run", fake_run)

    # 1. 查询独立进程组 PGID 1001 -> 存活
    assert web_app._process_group_alive(1001) is True

    # 2. 查询派生 Worker PID 2002 -> 即使不是 PGID 主进程，也能基于 PID 与合法命令判定存活
    assert web_app._process_group_alive(2002) is True

    # 3. 查询 PID 3003 -> 命令为系统守护进程，触发白名单拦截判定为已死 (防御 PID 复用)
    assert web_app._process_group_alive(3003) is False

    # 4. 查询不存在的 PID/PGID 9999 -> 死亡
    assert web_app._process_group_alive(9999) is False


def test_safe_kill_pid_or_pgid_guards_self():
    """_safe_kill_pid_or_pgid 严禁对自身 PID (Web Server) 执行终止。"""
    import os
    from web import app as web_app

    # 当传入当前进程 PID 时，函数直接返回，绝不 kill 自己
    web_app._safe_kill_pid_or_pgid(os.getpid(), 15)
    web_app._safe_kill_pid_or_pgid(None, 15)
    assert web_app._is_pid_or_pgid_alive(os.getpid()) is True
    assert web_app._is_pid_or_pgid_alive(None) is False


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


def test_wait_for_review_notifications_lifecycle(tmp_path):
    """测试 wait_for_review_notifications 真实等待后台线程完成。"""
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    completed = False

    def background_worker():
        time.sleep(0.05)
        nonlocal completed
        completed = True

    t = threading.Thread(target=background_worker, daemon=True)
    t.start()
    manager._async_review_threads = [t]

    manager.wait_for_review_notifications(timeout=1.0)
    assert completed is True


def test_wechat_review_notification_dal_and_drain(tmp_path):
    """视频号审核物料通知持久化 DAL 及补偿排水机制。"""
    from video_processing.db.database import PipelineDB

    db = PipelineDB(str(tmp_path / "pipeline.db"))

    # 1. 入队持久化
    nid = db.enqueue_wechat_review_notification(
        prefix=str(tmp_path / "yid_rev_1"),
        title="Review Title",
    )
    assert nid > 0

    # 2. 认领待办
    claimed = db.claim_pending_wechat_review_notifications(limit=5)
    assert len(claimed) == 1
    assert claimed[0]["id"] == nid

    # 3. 记录处理状态
    db.record_wechat_review_notification_status(nid, "ACCEPTED")

    # 再次查询已无待办
    assert len(db.get_pending_wechat_review_notifications()) == 0

    # 4. 验证 claim_specific_wechat_review_notification 单任务原子抢占
    nid_spec = db.enqueue_wechat_review_notification(
        prefix=str(tmp_path / "yid_rev_spec"),
        title="Specific Review Title",
    )
    assert db.claim_specific_wechat_review_notification(nid_spec) is True
    # 重复抢占失败（防并发冲突）
    assert db.claim_specific_wechat_review_notification(nid_spec) is False
    db.record_wechat_review_notification_status(nid_spec, "ACCEPTED")

    # 5. 模拟卡死在 PROCESSING 的任务并超时回收
    nid_stale = db.enqueue_wechat_review_notification(
        prefix=str(tmp_path / "yid_rev_2"),
        title="Stale Title",
    )
    db.claim_pending_wechat_review_notifications(limit=5)

    # 手动回拨 last_attempt_at 到 20 分钟前
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE wechat_review_notifications SET last_attempt_at = datetime('now', '-20 minutes') WHERE id = ?",
            (nid_stale,),
        )

    recovered = db.recover_stale_wechat_review_notifications(stale_minutes=10)
    assert recovered == 1

    # 回收后状态重置为 PENDING
    pending = db.get_pending_wechat_review_notifications()
    assert len(pending) == 1
    assert pending[0]["id"] == nid_stale

    # 6. 测试 PipelineManager.drain_pending_review_notifications 补偿发送
    manager = PipelineManager(str(tmp_path / "pipeline.db"))
    manager._OUT_DIR = tmp_path
    drain_sent = []

    def fake_sync_send(prefix, title):
        drain_sent.append((prefix, title))
        return True

    manager._send_wechat_submission_review_material_sync = fake_sync_send
    drained = manager.drain_pending_review_notifications(limit=5)
    assert drained == 1
    assert len(drain_sent) == 1
    assert drain_sent[0][1] == "Stale Title"

    # 排水后待办再次清空
    assert len(db.get_pending_wechat_review_notifications()) == 0


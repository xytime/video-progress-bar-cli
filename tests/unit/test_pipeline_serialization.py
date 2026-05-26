import os
import sys
import time
import fcntl
import threading
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# Ensure src/ is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from video_processing.pipeline_manager import PipelineManager
from video_processing.db.database import PipelineDB
from bot.pipeline_agent import PipelineAgent


def test_pipeline_manager_flock_serialization(tmp_path):
    """验证 PipelineManager._process_single_video 在并发情况下仍保持完全串行。"""
    db_path = tmp_path / "test_serialize.db"
    db = PipelineDB(str(db_path))
    db.add_video("vid1", "Title 1", "Channel")
    db.add_video("vid2", "Title 2", "Channel")

    pm = PipelineManager(db_path=str(db_path))

    # 用来记录各个线程进入临界区（加锁后）的起止时间点
    lock_intervals = []
    intervals_lock = threading.Lock()

    def fake_subprocess_run(cmd, *args, **kwargs):
        # 记录进入模拟的管道执行阶段
        with intervals_lock:
            start_time = time.time()
        
        # 模拟高负载工作时间
        time.sleep(0.4)
        
        with intervals_lock:
            end_time = time.time()
            lock_intervals.append((start_time, end_time))
            
        res = MagicMock()
        res.returncode = 0
        res.stdout = "mock stdout"
        res.stderr = "mock stderr"
        return res

    # 模拟 wechat_uploader 等一系列子进程调用
    # [Gemini_3.5_Flash_fast] 强制使 enable_sigterm_kill 为 False，让其走正常的 subprocess.run 分支，以便被 fake_subprocess_run 拦截
    @patch('src.video_processing.pipeline_manager.settings.enable_sigterm_kill', new=False)
    @patch('src.video_processing.pipeline_manager.subprocess.run', side_effect=fake_subprocess_run)
    @patch('src.video_processing.pipeline_manager.PipelineManager._find_downloaded_video')
    def run_test(mock_find_video, mock_run):
        # 模拟始终能找到已下载的视频文件，方便跳过实际下载以快速测试
        mock_find_video.return_value = str(tmp_path / "vid1.mp4")
        (tmp_path / "vid1.mp4").touch()
        (tmp_path / "vid1_vertical.mp4").touch()
        (tmp_path / "vid1_copy.txt").touch()
        (tmp_path / "vid1_title.txt").touch()

        # 并发启动两个进程/线程处理不同的视频
        video1 = {"youtube_id": "vid1", "title": "Title 1", "score": 90}
        video2 = {"youtube_id": "vid2", "title": "Title 2", "score": 85}

        t1 = threading.Thread(target=pm._process_single_video, args=(video1,))
        t2 = threading.Thread(target=pm._process_single_video, args=(video2,))

        # 同时启动
        t1.start()
        time.sleep(0.05)  # 保证 t1 优先获取锁
        t2.start()

        t1.join()
        t2.join()

        # 验证 lock_intervals 中记录的临界区是否有重叠
        # 我们对时间区间按开始时间排序
        sorted_intervals = sorted(lock_intervals, key=lambda x: x[0])
        assert len(sorted_intervals) == 2
        
        # 第一个区间的结束时间点必须小于或等于第二个区间的开始时间点（表明它们是串行的）
        first_end = sorted_intervals[0][1]
        second_start = sorted_intervals[1][0]
        
        print(f"First end: {first_end}, Second start: {second_start}")
        assert second_start >= first_end

    run_test()


@pytest.mark.asyncio
async def test_pipeline_agent_tools_serialization(tmp_path):
    """验证 PipelineAgent 核心处理工具在并发调用时依然能够通过 fcntl 文件锁实现排队。"""
    # 构造 mock bot 与 event loop
    mock_bot = MagicMock()
    mock_loop = MagicMock()
    
    # 临时配置环境变量以通过初始化
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}):
        agent = PipelineAgent(bot=mock_bot, loop=mock_loop, chat_id=123)
    
    agent.output_dir = tmp_path
    
    lock_intervals = []
    intervals_lock = threading.Lock()

    def fake_subprocess_run(cmd, *args, **kwargs):
        with intervals_lock:
            start_time = time.time()
        time.sleep(0.4)
        with intervals_lock:
            end_time = time.time()
            lock_intervals.append((start_time, end_time))
        res = MagicMock()
        res.returncode = 0
        return res

    # 测试 download_video 工具的锁排队
    @patch('src.bot.pipeline_agent.subprocess.run', side_effect=fake_subprocess_run)
    def run_test(mock_run):
        # 强制清除 mock 缓存
        if (tmp_path / "vid1.mp4").exists():
            (tmp_path / "vid1.mp4").unlink()

        def call_tool(yid):
            agent.download_video(yid)

        t1 = threading.Thread(target=call_tool, args=("vid1",))
        t2 = threading.Thread(target=call_tool, args=("vid2",))

        t1.start()
        time.sleep(0.05)
        t2.start()

        t1.join()
        t2.join()

        # 检查时间区间是否串行
        sorted_intervals = sorted(lock_intervals, key=lambda x: x[0])
        assert len(sorted_intervals) == 2
        assert sorted_intervals[1][0] >= sorted_intervals[0][1]

    run_test()

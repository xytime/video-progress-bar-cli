import sys
from pathlib import Path
import subprocess
import json
import datetime

sys.path.append(str(Path(__file__).parent.parent / "src"))
from video_processing.db import PipelineDB

# 定义主动发现的热门搜索词
DISCOVERY_KEYWORDS = [
    "AI interview",
    "tech keynote 2026",
    "business podcast",
    "founder speech"
]

def fetch_latest_videos(db: PipelineDB, channel_id: str):
    """拉取频道过去 2 天内的最新视频"""
    print(f"Polling channel: {channel_id}")
    url = f"https://www.youtube.com/channel/{channel_id}"
    
    # [Claude_Sonnet_4.6_Thinking_planning] 修复：防止 yt-dlp 遍历整个频道历史
    # --break-on-reject : 遇到第一个不符合日期过滤的视频立即停止
    #                      （YouTube 按最新排序，超过2天即可提前退出）
    # --playlist-end 30 : 最多检查最新 30 条，兜底防止卡死
    cmd = [
        "yt-dlp",
        "--print", "%(id)s|%(title)s",
        "--dateafter", "now-2days",
        "--match-filter", "duration > 120 & duration < 2700",
        "--break-on-reject",   # 关键：遇到第一个不符合日期的视频立即停止
        "--playlist-end", "30",# 兜底：最多看最新 30 条
        "--no-warnings",
        "--cookies-from-browser", "safari",
        url
    ]
    
    try:
        # [Claude_Sonnet_4.6_Thinking_planning] 增加 120s 超时硬上限，防止单频道无限阻塞
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 and result.returncode != 101:
            # returncode=101 是 yt-dlp 的 --break-on-reject 正常退出码，不算错误
            print(f"Warning: Failed to fetch {channel_id}. Error: {result.stderr.strip()}")
            return
            
        output = result.stdout.strip()
        if not output:
            print("  -> No recent matching videos found.")
            return
            
        for line in output.split('\n'):
            parts = line.split('|', 1)
            if len(parts) == 2:
                video_id, title = parts
                added = db.add_video(video_id, title, channel_id, score=0)
                if added:
                    print(f"  -> Added new video to queue: {title}")
                else:
                    print(f"  -> Video already in queue: {title}")
                    
    except subprocess.TimeoutExpired:
        print(f"  -> Timeout: {channel_id} took >120s, skipped. Will retry next run.")
    except Exception as e:
        print(f"Error polling channel {channel_id}: {e}")


def discover_new_channels(db: PipelineDB):
    """通过关键词搜索发现潜在的优质频道，加入推荐列表"""
    print("Running active discovery for new channels...")
    for keyword in DISCOVERY_KEYWORDS:
        print(f"Searching for: {keyword}")
        cmd = [
            "yt-dlp",
            "ytsearch5:" + keyword,  # 抓取前5个搜索结果
            "--print", "%(channel_id)s|%(channel)s",
            "--no-warnings",
            "--cookies-from-browser", "safari"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    parts = line.split('|', 1)
                    if len(parts) == 2:
                        channel_id, channel_name = parts
                        # 尝试添加至待审核列表
                        success = db.add_channel(channel_id, channel_name, status="PENDING", reason=f"Discovered via search: '{keyword}'")
                        if success:
                            print(f"  -> Discovered new channel: {channel_name} ({channel_id})")
        except Exception as e:
            print(f"Error during discovery for '{keyword}': {e}")

def main():
    db = PipelineDB()
    
    # 1. 探索新频道
    discover_new_channels(db)
    
    # 2. 拉取已有白名单的新视频
    approved_channels = db.get_approved_channels()
    print(f"\nFound {len(approved_channels)} approved channels.")
    
    for row in approved_channels:
        fetch_latest_videos(db, row['channel_id'])

if __name__ == "__main__":
    main()

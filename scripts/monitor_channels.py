"""
频道监控与发现脚本

# Modification History
| Version | Date       | Author                         | Description |
|---------|------------|--------------------------------|-------------|
| 1.0.0   | 2026-05-20 | Unknown                        | 初始创建     |
| 1.1.0   | 2026-06-07 | Gemini_3.5_Flash_High_planning | 整合动态热词注入逻辑，支持从 HN 热榜获取动态关键词 |
| 1.2.0   | 2026-06-08 | Claude_Sonnet_4.6_planning     | 标题翻译改用 translation_helper（阿里云 MT 优先）|
| 1.3.0   | 2026-06-09 | Gemini_3.5_Flash_planning      | 升级新视频主动搜索发现逻辑，将符合高赞筛选要求的视频录入 DISCOVERY 源 |
"""
import sys
from pathlib import Path
import subprocess
import json
import datetime

sys.path.append(str(Path(__file__).parent.parent / "src"))
from video_processing.db import PipelineDB
from config.settings import settings  # [Gemini_3.5_Flash_High_planning]
from video_processing.utils.translation_helper import translate_text as _translate_text  # [Claude_Sonnet_4.6_planning]

# 定义主动发现的静态热门搜索词
STATIC_KEYWORDS = [
    "AI interview",
    "tech keynote 2026",
    "business podcast",
    "founder speech"
]

def get_discovery_keywords() -> list[str]:
    """获取发现新频道所需的关键词（合并静态和动态热词）"""
    # [Gemini_3.5_Flash_High_planning] 检查 Feature Flag 是否开启
    if not settings.enable_dynamic_keywords:
        print("[Discovery] Dynamic keywords disabled via settings, using static only.")
        return STATIC_KEYWORDS

    try:
        # 显式将 scripts 目录加入 sys.path 以防 import 失败
        scripts_dir = str(Path(__file__).parent)
        if scripts_dir not in sys.path:
            sys.path.append(scripts_dir)
            
        from fetch_trending_keywords import get_dynamic_keywords
        dynamic = get_dynamic_keywords()
        print(f"[Discovery] Using {len(dynamic)} dynamic + {len(STATIC_KEYWORDS)} static keywords")
        return list(dict.fromkeys(STATIC_KEYWORDS + dynamic))
    except Exception as e:
        print(f"[Discovery] Dynamic keywords unavailable ({e}), using static only.")
        return STATIC_KEYWORDS


def fetch_latest_videos(db: PipelineDB, channel_id: str):
    """拉取频道过去 2 天内的最新视频，同时获取元数据（时长、观看数、点赞数、发布日期）"""
    print(f"Polling channel: {channel_id}")
    url = f"https://www.youtube.com/channel/{channel_id}"
    
    cmd = [
        "yt-dlp",
        "--print", "%(id)s|||%(title)s|||%(duration)s|||%(view_count)s|||%(like_count)s|||%(upload_date)s",
        "--dateafter", "now-2days",
        "--match-filter", "duration > 120 & duration < 2700",
        "--break-on-reject",
        "--playlist-end", "30",
        "--no-warnings",
        "--cookies-from-browser", "safari",
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 and result.returncode != 101:
            print(f"Warning: Failed to fetch {channel_id}. Error: {result.stderr.strip()}")
            return
            
        output = result.stdout.strip()
        if not output:
            print("  -> No recent matching videos found.")
            return

        def _int_or_none(v):
            try: return int(v)
            except: return None
            
        for line in output.split('\n'):
            parts = line.split('|||', 5)
            if len(parts) < 2:
                continue
            video_id = parts[0].strip()
            title    = parts[1].strip()
            duration_sec = _int_or_none(parts[2]) if len(parts) > 2 else None
            view_count   = _int_or_none(parts[3]) if len(parts) > 3 else None
            like_count   = _int_or_none(parts[4]) if len(parts) > 4 else None
            upload_date  = parts[5].strip() if len(parts) > 5 and parts[5].strip() not in ("NA", "") else None
                 
            # 翻译标题（阿里云 MT 优先）
            zh_title = title
            try:
                zh_title = _translate_text(title, src_lang="auto", target_lang="zh-CN")
            except Exception as e:
                print(f"  -> Translator failed for {video_id}: {e}")

            added = db.add_video(
                video_id, title, channel_id, score=0, zh_title=zh_title, source="AUTO",
                duration_sec=duration_sec, view_count=view_count,
                like_count=like_count, upload_date=upload_date,
            )
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
    # [Gemini_3.5_Flash_planning] 独立频道探索逻辑，保持高内聚低耦合
    print("Running active discovery for new channels...")
    keywords = get_discovery_keywords()
    for keyword in keywords:
        print(f"Searching channels for: {keyword}")
        cmd = [
            "yt-dlp",
            "ytsearch5:" + keyword,  # 抓取前5个搜索结果
            "--print", "%(channel_id)s|%(channel)s",
            "--no-warnings",
            "--cookies-from-browser", "safari"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    parts = line.split('|', 1)
                    if len(parts) == 2:
                        channel_id, channel_name = parts
                        success = db.add_channel(channel_id, channel_name, status="PENDING", reason=f"Discovered via search: '{keyword}'")
                        if success:
                            print(f"  -> Discovered new channel: {channel_name} ({channel_id})")
        except Exception as e:
            print(f"Error during channel discovery for '{keyword}': {e}")


def discover_high_like_videos(db: PipelineDB):
    """通过关键词搜索发现最近24小时内的高赞视频，存入数据库以供浏览和手动触发"""
    # [Gemini_3.5_Flash_planning] 独立高赞视频发现逻辑，避免与频道发现逻辑混合
    print("Running active discovery for high-like videos...")
    
    def _int_or_none(v):
        try: return int(v)
        except: return None

    import datetime
    yesterday_str = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d")
    
    keywords = get_discovery_keywords()
    for keyword in keywords:
        print(f"Searching high-like videos for: {keyword}")
        cmd = [
            "yt-dlp",
            "ytsearch10:" + keyword,  # 抓取前10个搜索结果
            "--print", "%(id)s|||%(title)s|||%(duration)s|||%(view_count)s|||%(like_count)s|||%(upload_date)s|||%(channel_id)s",
            "--no-warnings",
            "--cookies-from-browser", "safari"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    parts = line.split('|||', 6)
                    if len(parts) == 7:
                        video_id = parts[0].strip()
                        title = parts[1].strip()
                        duration_sec = _int_or_none(parts[2])
                        view_count = _int_or_none(parts[3])
                        like_count = _int_or_none(parts[4])
                        upload_date = parts[5].strip()
                        channel_id = parts[6].strip()

                        # 筛选最近24-48小时内发布且观看量>500的视频
                        if upload_date and upload_date >= yesterday_str:
                            if view_count and view_count > 500:
                                zh_title = title
                                try:
                                    zh_title = _translate_text(title, src_lang="auto", target_lang="zh-CN")
                                except Exception as e:
                                    print(f"  -> Translator failed for {video_id}: {e}")

                                # 以 DISCOVERY 源入库，score=0，防自动处理，仅在 Web 端高赞 Tab 供浏览
                                added = db.add_video(
                                    video_id, title, channel_id, score=0, zh_title=zh_title, source="DISCOVERY",
                                    duration_sec=duration_sec, view_count=view_count,
                                    like_count=like_count, upload_date=upload_date,
                                )
                                if added:
                                    print(f"  -> Discovered high-like video: {title} (likes={like_count}, views={view_count})")
        except subprocess.TimeoutExpired:
            print(f"  -> Timeout searching '{keyword}'")
        except Exception as e:
            print(f"Error during video discovery for '{keyword}': {e}")


def main():
    db = PipelineDB()
    
    # 1. 探索新频道
    discover_new_channels(db)
    
    # 2. 探索高赞视频
    discover_high_like_videos(db)
    
    # 3. 拉取已有白名单的新视频
    approved_channels = db.get_approved_channels()
    print(f"\nFound {len(approved_channels)} approved channels.")
    
    for row in approved_channels:
        fetch_latest_videos(db, row['channel_id'])

if __name__ == "__main__":
    main()

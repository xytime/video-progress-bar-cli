"""
频道监控与发现脚本

# Modification History
| Version | Date       | Author                         | Description |
|---------|------------|--------------------------------|-------------|
| 1.0.0   | 2026-05-20 | Unknown                        | 初始创建     |
| 1.1.0   | 2026-06-07 | Gemini_3.5_Flash_High_planning | 整合动态热词注入逻辑，支持从 HN 热榜获取动态关键词 |
| 1.2.0   | 2026-06-08 | Claude_Sonnet_4.6_planning     | 标题翻译改用 translation_helper（阿里云 MT 优先）|
| 1.3.0   | 2026-06-09 | Gemini_3.5_Flash_planning      | 升级新视频主动搜索发现逻辑，将符合高赞筛选要求的视频录入 DISCOVERY 源 |
| 1.4.0   | 2026-06-09 | Gemini_3.5_Flash_planning      | discover_high_like_videos 引入类别抓取及敏感词过滤检查，并在 add_video 时存入 |
| 1.5.0   | 2026-06-09 | Gemini_3.5_Flash_planning      | 将高赞视频时间窗口从 24 小时扩大至 3 天，解决刷新内容少的问题 |
| 1.6.0   | 2026-06-11 | Claude_Sonnet_4.6              | [静默失败修复] exit 101 且 stdout 为空时输出真实 Cookie/auth 错误，不再静默当成"无新视频" |
| 1.7.0   | 2026-06-11 | Gemini_3.5_Flash_planning      | [高赞发现优化] 提升搜索数为30，添加 --dateafter 3天，解决历史高赞霸榜且无更新问题 |
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
    "founder speech",
    "world cup 2026",
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
        "--dateafter", "now-3days",
        "--match-filter", "duration > 120 & duration < 2700",
        "--break-on-reject",
        "--playlist-end", "30",
        "--no-warnings",
        *settings.get_yt_cookie_args(),
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        # exit 101 = yt-dlp partial errors (e.g. cookie/bot-check); treat as real failure
        # and surface the error so it doesn't look like "no new videos"
        if result.returncode not in (0, 101):
            print(f"Warning: Failed to fetch {channel_id}. Error: {result.stderr.strip()[:200]}")
            return
        if result.returncode == 101 and not result.stdout.strip():
            # All requests rejected — surface the actual stderr instead of silently skipping
            err_line = result.stderr.strip().split('\n')[0][:200] if result.stderr.strip() else "unknown error"
            print(f"  -> Cookie/auth error (exit 101): {err_line}")
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
            *settings.get_yt_cookie_args()
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
    """通过关键词搜索发现最近3天内的高赞视频，进行敏感词检测和分类提取，存入数据库以供浏览和手动触发"""
    # [Gemini_3.5_Flash_planning] 独立高赞视频发现逻辑，避免与频道发现逻辑混合
    print("Running active discovery for high-like videos...")
    
    # 导入安全审查引擎 [Gemini_3.5_Flash_planning]
    from video_processing.censor_engine import check_text, check_channel_policy
    
    def _int_or_none(v):
        try: return int(v)
        except: return None

    import datetime
    # [Gemini_3.5_Flash_planning] 将高赞视频发现窗口扩大至 3 天，提供更多发现结果
    yesterday_str = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y%m%d")
    
    keywords = get_discovery_keywords()
    for keyword in keywords:
        print(f"Searching high-like videos for: {keyword}")
        cmd = [
            "yt-dlp",
            "ytsearch30:" + keyword,  # [Gemini_3.5_Flash_planning] 抓取前30个搜索结果以提高最新视频命中率
            "--dateafter", "now-3days",  # [Gemini_3.5_Flash_planning] 仅抓取最近3天的视频，规避历史热门视频干扰
            "--print", "%(id)s|||%(title)s|||%(duration)s|||%(view_count)s|||%(like_count)s|||%(upload_date)s|||%(channel_id)s|||%(categories.0)s",
            "--no-warnings",
            *settings.get_yt_cookie_args()
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    parts = line.split('|||', 7)
                    if len(parts) == 8:
                        video_id = parts[0].strip()
                        title = parts[1].strip()
                        duration_sec = _int_or_none(parts[2])
                        view_count = _int_or_none(parts[3])
                        like_count = _int_or_none(parts[4])
                        upload_date = parts[5].strip()
                        channel_id = parts[6].strip()
                        category = parts[7].strip()
                        if category in ("NA", ""):
                            category = None

                        # 筛选最近 3 天内发布且观看量>500的视频
                        if upload_date and upload_date >= yesterday_str:
                            if view_count and view_count > 500:
                                zh_title = title
                                try:
                                    zh_title = _translate_text(title, src_lang="auto", target_lang="zh-CN")
                                except Exception as e:
                                    print(f"  -> Translator failed for {video_id}: {e}")

                                # [Gemini_3.5_Flash_planning] 进行敏感词检测
                                censor_tag = None
                                censor_score = None
                                try:
                                    block_res = check_text(zh_text=zh_title, en_text=title)
                                    if block_res.hit:
                                        censor_tag = block_res.tag
                                        censor_score = block_res.score
                                    else:
                                        policy_res = check_channel_policy(zh_text=zh_title, en_text=title)
                                        if policy_res.hit:
                                            censor_tag = policy_res.tag
                                            censor_score = policy_res.score
                                except Exception as e:
                                    print(f"  -> Censor engine failed for {video_id}: {e}")

                                # 以 DISCOVERY 源入库，score=0，防自动处理，仅在 Web 端高赞 Tab 供浏览
                                added = db.add_video(
                                    video_id, title, channel_id, score=0, zh_title=zh_title, source="DISCOVERY",
                                    duration_sec=duration_sec, view_count=view_count,
                                    like_count=like_count, upload_date=upload_date,
                                    category=category, censor_tag=censor_tag, censor_score=censor_score
                                )
                                if added:
                                    print(f"  -> Discovered high-like video: {title} (likes={like_count}, views={view_count}, category={category}, censor={censor_tag})")
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

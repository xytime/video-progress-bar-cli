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
| 1.8.0   | 2026-06-11 | Claude_Opus_4.6_Thinking_planning | [Timeout修复] ytsearch30+dateafter导致大量超时，回调为ytsearch10，timeout 120→18s |
| 1.9.0   | 2026-06-14 | Claude_Opus_4.8                | [限流缓解] 频道轮询间加 1~2.5s 随机间隔；exit 101 退避后重试一次；日志措辞由"Cookie/auth error"改为"瞬时限流"，避免误判 cookie 失效 |
| 2.0.0   | 2026-06-23 | Claude_Opus_4.8                | [发布断流根治] ①裸 "yt-dlp" 改 settings.ytdlp_path 绝对路径——cron 最小 PATH 找不到致全灭(monitor.log 1555 条 FileNotFoundError)；②三处加 --ignore-no-formats-error——YouTube 格式门控使 --print 元数据整体中止(返回 0 候选)，发现仅需元数据故忽略格式错误 |
| 2.1.0   | 2026-07-09 | Codex                          | [白名单优先] 批准频道轮询前置；探索型发现降为每6小时一次；本轮白名单已限流时跳过探索，避免高价值频道被前置搜索流量拖死 |
| 2.2.0   | 2026-07-10 | Codex                          | [监控可观测性] 输出逐频道健康报告，区分成功/空结果/SSL/限流/超时；整轮全部失败时返回非零，避免频道更新静默中断 |
| 2.3.0   | 2026-07-12 | Codex                          | [分层降频] Wall Street Truthbombs 每小时、演讲类每3小时、其他保留频道每6小时；关闭全网探索并记录逐频道轮询时间 |
| 2.4.0   | 2026-07-12 | Codex                          | [首次初始化] 增加 --bootstrap：一次性全量轮询批准频道，并将发现窗口放宽到最近5天 |
| 2.5.0   | 2026-07-12 | Codex                          | [访问减压] 频道最多解析12条；取消被拒后的即时重试；连续拒绝按6/12/24小时逐频道熔断 |
| 3.0.0   | 2026-07-28 | Codex                          | [断供根治] 官方 Data API 主源、RSS 无密钥降级；发现脱离 yt-dlp，RSS 条目待元数据补全后才可评分 |
"""
import sys
import argparse
from pathlib import Path
import subprocess
import json
import datetime
import time      # [Claude_Opus_4.8] 频道轮询间隔，规避 YouTube 瞬时限流
import random    # [Claude_Opus_4.8] 间隔抖动 + 退避重试

sys.path.append(str(Path(__file__).parent.parent / "src"))
from video_processing.db import PipelineDB
from config.settings import settings  # [Gemini_3.5_Flash_High_planning]
from video_processing.utils.translation_helper import translate_text as _translate_text  # [Claude_Sonnet_4.6_planning]
from video_processing.utils.youtube_catalog import YouTubeCatalogError, fetch_channel_catalog

# 由 cron 每 30 分钟唤醒，但不再每轮访问所有频道。
CORE_CHANNEL_IDS = {"UCTK_cv-y88CScoudcXnS1Ew"}  # Wall Street Truthbombs
SPEECH_CHANNEL_IDS = {
    "UCt84aUC9OG6di8kSdKzEHTQ",  # Google for Education
    "UCLv7Gzc3VTO6ggFlXY0sOyw",  # Harvard University
    "UCzWwWbbKHg4aodl0S35R6XA",  # Hoover Institution
    "UC-EnprmCZ3OXyAoG7vjVNCA",  # Stanford
    "UCAuUUnT6oDeKwE6v1NGQxug",  # TED
    "UCsT0YIqwnpJCM-mx7-gSA4Q",  # TEDx Talks
    "UCnBT5HobLD5_iyHsZNL85Ng",  # UC Berkeley Inspires
    "UCSh-dNnqe1agUSzPM01LgBA",  # Yale University
}
POLL_INTERVALS = {"core": 3600, "speech": 3 * 3600, "other": 6 * 3600}
POLL_STATE_PATH = Path(__file__).parent.parent / "output" / "monitor_schedule_state.json"
RATE_LIMIT_STATE_PATH = Path(__file__).parent.parent / "output" / "monitor_access_backoff.json"
ACCESS_BACKOFF_HOURS = (6, 12, 24)

# [Claude_Opus_4.8 v2.0.0] yt-dlp 绝对路径（单一真相源，见 settings.ytdlp_path）。
# 严禁裸 "yt-dlp"：cron 以 .venv/bin/python 直跑本脚本时不激活 venv，最小 PATH 找不到 yt-dlp
# → 每轮发现全灭却被静默吞成"无新视频"（发布断流根因之一，已复现 FileNotFoundError）。
_YTDLP = settings.ytdlp_path
# 发现仅需元数据，不下载；YouTube 对格式下发做 bot/PO-token 门控时 --print 会整体中止，
# 故统一忽略"无可用格式"错误，保证 view/like/duration 等元数据照常取回。
_IGNORE_NO_FORMATS = "--ignore-no-formats-error"

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


def fetch_latest_videos(db: PipelineDB, channel_id: str, lookback_days: int = 3):
    """拉取频道近期候选；Data API 主源，RSS 只保住待补全候选。"""
    print(f"Polling channel: {channel_id}")
    try:
        catalog = fetch_channel_catalog(
            channel_id,
            lookback_days=lookback_days,
            api_key=settings.youtube_data_api_key,
            timeout_sec=settings.youtube_data_api_timeout_sec,
        )
        if catalog.source == "youtube_rss":
            print(f"  -> RSS degraded mode: {catalog.fallback_reason}")
        if not catalog.videos:
            print("  -> No recent matching videos found.")
            return "empty" if catalog.metadata_complete else "degraded"

        for video in catalog.videos:
            # 翻译标题（阿里云 MT 优先）
            zh_title = video.title
            try:
                zh_title = _translate_text(video.title, src_lang="auto", target_lang="zh-CN")
            except Exception as e:
                print(f"  -> Translator failed for {video.youtube_id}: {e}")

            result = db.upsert_monitored_video(
                video.youtube_id, video.title, channel_id,
                zh_title=zh_title,
                duration_sec=video.duration_sec,
                view_count=video.view_count,
                like_count=video.like_count,
                upload_date=video.upload_date,
                metadata_complete=catalog.metadata_complete,
            )
            if result == "inserted":
                state = "queue" if catalog.metadata_complete else "metadata pending"
                print(f"  -> Added new video ({state}): {video.title}")
            elif result == "refreshed":
                print(f"  -> Refreshed video metadata: {video.title}")
        return "ok" if catalog.metadata_complete else "degraded"

    except YouTubeCatalogError as e:
        print(f"  -> Catalog unavailable for {channel_id}: {e}")
        return "error"


def should_run_discovery(now: datetime.datetime | None = None) -> bool:
    """探索型发现只在 6 小时窗口运行，避免每 30 分钟都打搜索流量。"""
    now = now or datetime.datetime.now()
    return now.minute < 30 and now.hour in {0, 6, 12, 18}


def _channel_tier(channel_id: str) -> str:
    if channel_id in CORE_CHANNEL_IDS:
        return "core"
    if channel_id in SPEECH_CHANNEL_IDS:
        return "speech"
    return "other"


def _load_poll_state() -> dict[str, str]:
    try:
        return json.loads(POLL_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_poll_state(state: dict[str, str]) -> None:
    try:
        POLL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = POLL_STATE_PATH.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(POLL_STATE_PATH)
    except OSError as exc:
        print(f"[Monitor] Failed to save schedule state: {exc}")


def _load_access_backoff() -> dict[str, dict]:
    try:
        data = json.loads(RATE_LIMIT_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_access_backoff(state: dict[str, dict]) -> None:
    try:
        RATE_LIMIT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = RATE_LIMIT_STATE_PATH.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(RATE_LIMIT_STATE_PATH)
    except OSError as exc:
        print(f"[Monitor] Failed to save access backoff state: {exc}")


def _is_backoff_active(channel_id: str, now: datetime.datetime, state: dict[str, dict]) -> bool:
    until_raw = (state.get(channel_id) or {}).get("cooldown_until")
    if not until_raw:
        return False
    try:
        return now < datetime.datetime.fromisoformat(until_raw)
    except ValueError:
        return False


def _record_access_result(channel_id: str, result: str, now: datetime.datetime,
                          state: dict[str, dict]) -> None:
    if result in {"ok", "empty", "degraded"}:
        state.pop(channel_id, None)
        return
    if result != "limited":
        return
    failures = int((state.get(channel_id) or {}).get("consecutive_failures", 0)) + 1
    cooldown_hours = ACCESS_BACKOFF_HOURS[min(failures - 1, len(ACCESS_BACKOFF_HOURS) - 1)]
    state[channel_id] = {
        "consecutive_failures": failures,
        "cooldown_until": (now + datetime.timedelta(hours=cooldown_hours)).isoformat(timespec="seconds"),
    }


def _is_channel_due(channel_id: str, now: datetime.datetime, state: dict[str, str]) -> bool:
    last_raw = state.get(channel_id)
    if not last_raw:
        return True
    try:
        last = datetime.datetime.fromisoformat(last_raw)
    except ValueError:
        return True
    return (now - last).total_seconds() >= POLL_INTERVALS[_channel_tier(channel_id)]


def _write_monitor_report(results: list[dict], approved_count: int) -> None:
    """写入本轮结构化健康快照，便于看板/告警区分失败与真实空结果。"""
    report = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "approved_count": approved_count,
        "polled_count": len(results),
        "summary": {
            status: sum(1 for item in results if item["status"] == status)
            for status in ("ok", "degraded", "empty", "limited", "timeout", "error")
        },
        "channels": results,
    }
    report_path = Path(__file__).parent.parent / "output" / "monitor_health.json"
    try:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[Monitor] Failed to write health report: {exc}")



def discover_new_channels(db: PipelineDB):
    """通过关键词搜索发现潜在的优质频道，加入推荐列表"""
    # [Gemini_3.5_Flash_planning] 独立频道探索逻辑，保持高内聚低耦合
    print("Running active discovery for new channels...")
    keywords = get_discovery_keywords()
    for keyword in keywords:
        print(f"Searching channels for: {keyword}")
        cmd = [
            _YTDLP,
            # [Claude_Opus_4.8 v2.0.0] 频道发现仅需 channel_id：用 --flat-playlist 跳过逐视频提取，
            # 避免加 --ignore-no-formats-error 后逐个完整解析导致 ytsearch5 超时（实测 60s 超时 → 3.5s）。
            "--flat-playlist",
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
            _YTDLP,
            _IGNORE_NO_FORMATS,
            "ytsearch10:" + keyword,  # [Claude_Opus_4.6_Thinking_planning] 回调为10：ytsearch30+dateafter导致yt-dlp需翻百页凑数，大量超时
            "--dateafter", "now-3days",  # [Gemini_3.5_Flash_planning] 仅抓取最近3天的视频，规避历史热门视频干扰
            "--print", "%(id)s|||%(title)s|||%(duration)s|||%(view_count)s|||%(like_count)s|||%(upload_date)s|||%(channel_id)s|||%(categories.0)s",
            "--no-warnings",
            *settings.get_yt_cookie_args()
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)  # [Claude_Opus_4.6_Thinking_planning] 120→180s，dateafter过滤需更多时间
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
    parser = argparse.ArgumentParser(description="按频道分层轮询 YouTube 元数据")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="首次初始化：所有批准频道立即轮询，并将窗口放宽到最近 5 天",
    )
    args = parser.parse_args()
    db = PipelineDB()

    # 1. 先拉取已有白名单的新视频，避免探索流量耗尽额度后拖死高价值频道。
    approved_channels = db.get_approved_channels()
    print(f"\nFound {len(approved_channels)} approved channels.")

    now = datetime.datetime.now()
    poll_state = _load_poll_state()
    access_backoff = _load_access_backoff()
    if access_backoff:
        print(
            f"[Monitor] Clearing {len(access_backoff)} legacy yt-dlp cooldown record(s); "
            "Data API/RSS discovery does not use this backoff."
        )
        access_backoff = {}
    results = []
    scheduled_channels = [
        row for row in approved_channels
        if _is_channel_due(row["channel_id"], now, poll_state)
    ]
    # 频道发现不再走 yt-dlp；旧的反爬冷却不能继续拦住 Data API/RSS 供给。
    backoff_channels = []
    due_channels = approved_channels if args.bootstrap else scheduled_channels
    lookback_days = 5 if args.bootstrap else 3
    if args.bootstrap:
        print("[Monitor] Bootstrap mode: all approved channels, lookback=5 days")
    print(
        "[Monitor] Due channels: "
        f"{len(due_channels)}/{len(approved_channels)} "
        f"(core={sum(_channel_tier(r['channel_id']) == 'core' for r in due_channels)}, "
        f"speech={sum(_channel_tier(r['channel_id']) == 'speech' for r in due_channels)}, "
        f"other={sum(_channel_tier(r['channel_id']) == 'other' for r in due_channels)})"
    )
    # [Claude_Opus_4.8] 频道间加 1~2.5s 随机间隔，避免连续快速轮询触发 YouTube 限流（exit 101）
    for idx, row in enumerate(due_channels):
        if idx > 0:
            time.sleep(random.uniform(1.0, 2.5))
        channel_id = row["channel_id"]
        result = fetch_latest_videos(db, channel_id, lookback_days=lookback_days)
        poll_state[channel_id] = now.isoformat(timespec="seconds")
        _record_access_result(channel_id, result, now, access_backoff)
        results.append({"channel_id": row["channel_id"], "channel_name": row["channel_name"], "status": result})

    _save_poll_state(poll_state)
    _save_access_backoff(access_backoff)

    # 无频道到期时保留上一轮真实健康快照，避免用全 0 抹掉最近一次访问结果。
    if results:
        _write_monitor_report(results, len(approved_channels))
    else:
        print("[Monitor] No channel polled; preserving previous health report.")
    failed_results = [item for item in results if item["status"] in {"limited", "timeout", "error"}]
    if failed_results:
        print(
            f"[Monitor] WARNING: {len(failed_results)}/{len(results)} approved channels failed this round; "
            "inspect output/monitor_health.json."
        )
    if results and len(failed_results) == len(results):
        print("[Monitor] ERROR: every approved channel failed; returning non-zero to expose upstream outage.")
        raise SystemExit(2)

    # 2. 全网探索关闭：当前只服务核心频道和演讲类白名单，避免额外搜索流量。
    print("\n[Discovery] Disabled: whitelist-only low-traffic mode.")

if __name__ == "__main__":
    main()

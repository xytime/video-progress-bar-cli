"""定时刷新播放量并重算评分 — 捞回"发现时不火、现已涨上来"的被埋没视频

背景：发现时把 view_count/like_count 冻结入库，评分基于当时数据。几天后视频可能已涨成
爆款，但分数没跟着重算 → 卡在 PENDING 永不发布。本脚本对近期可发布 PENDING 重新拉取
当前 YouTube 播放量、按现有 scoring 规则重算，把 ≥75 的捞出来（不改任何发布标准）。

约束：优先用官方 API 每批最多 50 条；无 API 时逐条限流防 bot-check；
只动 AUTO 源、非手动锁分；只升不降地修正分数；全程日志。

# Modification History
| Version | Date       | Author          | Description                              |
|---------|------------|-----------------|------------------------------------------|
| 1.0.0   | 2026-06-25 | Claude_Opus_4.8 | 一次性：刷新播放量重算，捞回被埋没爆款   |
| 1.1.0   | 2026-06-25 | Claude_Opus_4.8 | 改滚动近8天窗口，挂 cron 每小时第15分定期运行（错开发现:00/:30）|
| 1.2.0   | 2026-06-25 | Claude_Opus_4.8 | [严重修复] 重算前排除 BLACKLISTED 频道与 blacklisted_videos 墓碑——此前漏检导致已拉黑频道视频被重算顶发 |
| 1.3.0   | 2026-06-25 | Claude_Opus_4.8 | [审查整改] 候选查询下沉 PipelineDB.get_rescore_candidates（消除裸 SQL/手抄黑名单过滤/时区漂移）；fetch_current 健壮解析 yt-dlp 输出，避免异常被静默吞成"取不到" |
| 1.4.0   | 2026-07-12 | Codex           | [访问减压] 单轮最多查询50条，并跳过已达到频道专属发布线的演讲类候选 |
| 1.5.0   | 2026-09-25 | Codex           | 按到期时间公平轮转，优先批量读取官方统计并保存刷新结果；失败有冷却 |
"""
import subprocess
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from config.settings import settings
from video_processing.db import PipelineDB
from video_processing.utils.youtube_catalog import YouTubeCatalogError, fetch_video_statistics

CAP = 50  # 单轮最多复查 50 条；官方 API 可在一次请求中取完


def fetch_current(yid: str):
    cmd = [settings.ytdlp_path, "--ignore-no-formats-error", "--no-warnings",
           *settings.get_yt_cookie_args(),
           "--print", "%(view_count)s|%(like_count)s", yid]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=45).stdout.strip().split("\n")[0]
        parts = out.split("|")
        if len(parts) < 2:
            return (None, None)
        v, l = parts[0].strip(), parts[1].strip()
        return (int(v) if v.isdigit() else None,
                int(l) if l.isdigit() else None)
    except Exception:
        return (None, None)


def main():
    db = PipelineDB()
    # 候选与黑名单过滤全部下沉至 DAL（单一真相源，杜绝手抄过滤漂移重发黑名单频道）
    rows = db.get_rescore_candidates(
        days=8, limit=CAP, channel_min_scores=settings.auto_publish_channel_min_scores,
    )

    print(f"[rescore] 候选 {len(rows)} 条（近 8 天、低于各自频道发布线），开始刷新…", flush=True)
    rescued, updated, failed = [], 0, 0
    statistics = {}
    if settings.youtube_data_api_key and rows:
        try:
            statistics = fetch_video_statistics(
                list(dict.fromkeys(row["youtube_id"] for row in rows)),
                api_key=settings.youtube_data_api_key,
                timeout_sec=settings.youtube_data_api_timeout_sec,
            )
        except YouTubeCatalogError as exc:
            print(f"[rescore] 批量统计读取失败，本轮记录冷却后再试：{exc}", flush=True)
    for i, row in enumerate(rows, 1):
        yid, si = row["youtube_id"], row["slice_index"]
        cv, cl = statistics.get(yid, (None, None)) if settings.youtube_data_api_key else fetch_current(yid)
        result = db.record_rescore_attempt(yid, si or 0, cv, cl)
        if cv is None:
            failed += 1
        elif result is not None:
            previous, new = result
            updated += 1
            publish_line = (
                settings.speech_publish_score_line
                if row.get("channel_id") in settings.speech_channel_id_set
                else 75
            )
            if previous < publish_line <= new:
                rescued.append((new, cv, cl or 0, yid))
                print(f"  ★捞回 分{new} 发布线{publish_line} 播放{cv} 赞{cl} {yid}（老分{previous}）", flush=True)
        if i % 20 == 0:
            print(f"  …进度 {i}/{len(rows)}  已捞回 {len(rescued)}  取不到 {failed}", flush=True)
        if not settings.youtube_data_api_key and i < len(rows):
            time.sleep(random.uniform(1.5, 3.0))

    print(f"\n[rescore] 完成：扫描{len(rows)} 成功刷新{updated} 跨发布线{len(rescued)} 取不到{failed}", flush=True)
    rescued.sort(reverse=True)
    for new, cv, cl, yid in rescued:
        print(f"  分{new}  播放{cv:>7}  赞{cl:>5}  {yid}", flush=True)


if __name__ == "__main__":
    main()

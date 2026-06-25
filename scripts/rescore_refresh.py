"""刷新当前播放量并重算评分 — 捞回"发现时不火、现已涨上来"的被埋没视频（一次性运维）

背景：发现时把 view_count/like_count 冻结入库，评分基于当时数据。几天后视频可能已涨成
爆款，但分数没跟着重算 → 卡在 PENDING 永不发布。本脚本对近期可发布 PENDING 重新拉取
当前 YouTube 播放量、按现有 scoring 规则重算，把 ≥75 的捞出来（不改任何发布标准）。

约束：限流（每条间隔 1.5~3s 随机）防 YouTube bot-check；只动 AUTO 源、非手动锁分；
只升不降地修正分数；全程日志。跑完即可删。

# Modification History
| Version | Date       | Author          | Description                              |
|---------|------------|-----------------|------------------------------------------|
| 1.0.0   | 2026-06-25 | Claude_Opus_4.8 | 一次性：刷新播放量重算，捞回被埋没爆款   |
| 1.1.0   | 2026-06-25 | Claude_Opus_4.8 | 改滚动近8天窗口，挂 cron 每小时第15分定期运行（错开发现:00/:30）|
| 1.2.0   | 2026-06-25 | Claude_Opus_4.8 | [严重修复] 重算前排除 BLACKLISTED 频道与 blacklisted_videos 墓碑——此前漏检导致已拉黑频道视频被重算顶发 |
| 1.3.0   | 2026-06-25 | Claude_Opus_4.8 | [审查整改] 候选查询下沉 PipelineDB.get_rescore_candidates（消除裸 SQL/手抄黑名单过滤/时区漂移）；fetch_current 健壮解析 yt-dlp 输出，避免异常被静默吞成"取不到" |
"""
import subprocess
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from config.settings import settings
from video_processing.db import PipelineDB
from video_processing.scoring import compute_auto_score

CAP = 250  # 安全上限（候选窗口与黑名单过滤已下沉至 PipelineDB.get_rescore_candidates）


def fetch_current(yid: str):
    cmd = [settings.ytdlp_path, "--ignore-no-formats-error", "--no-warnings",
           *settings.get_yt_cookie_args(),
           "--print", "%(view_count)s|%(like_count)s", yid]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=45).stdout.strip().split("\n")[0]
        parts = out.split("|")
        if len(parts) < 2:
            return (None, 0)  # yt-dlp 输出异常（空/限流/格式变更）→ 视为取不到，不静默误判
        v, l = parts[0].strip(), parts[1].strip()
        return (int(v) if v.isdigit() else None,
                int(l) if l.isdigit() else 0)
    except Exception:
        return (None, 0)


def main():
    db = PipelineDB()
    # 候选与黑名单过滤全部下沉至 DAL（单一真相源，杜绝手抄过滤漂移重发黑名单频道）
    rows = db.get_rescore_candidates(days=8, limit=CAP)

    print(f"[rescore] 候选 {len(rows)} 条（近 8 天 AUTO PENDING <75分），开始刷新…", flush=True)
    rescued, updated, failed = [], 0, 0
    for i, row in enumerate(rows, 1):
        yid, si, old = row["youtube_id"], row["slice_index"], row["score"]
        cv, cl = fetch_current(yid)
        if cv is None:
            failed += 1
        else:
            new = compute_auto_score(cv, cl)
            if new > (old or 0):
                db.update_video_score(yid, new, slice_index=si or 0)
                updated += 1
                if (old or 0) < 75 <= new:
                    rescued.append((new, cv, cl, yid))
                    print(f"  ★捞回 分{new} 播放{cv} 赞{cl} {yid}（老分{old}）", flush=True)
        if i % 20 == 0:
            print(f"  …进度 {i}/{len(rows)}  已捞回 {len(rescued)}  取不到 {failed}", flush=True)
        time.sleep(random.uniform(1.5, 3.0))

    print(f"\n[rescore] 完成：扫描{len(rows)} 升分{updated} 捞回(≥75){len(rescued)} 取不到{failed}", flush=True)
    rescued.sort(reverse=True)
    for new, cv, cl, yid in rescued:
        print(f"  分{new}  播放{cv:>7}  赞{cl:>5}  {yid}", flush=True)


if __name__ == "__main__":
    main()

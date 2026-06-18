#!/usr/bin/env python3
"""scripts/recover_av1_videos.py — 盘后批量恢复「AV1 缓存导致渲染崩溃」的高分视频

# Modification History
| Version | Date       | Author          | Description                                                                 |
|---------|------------|-----------------|-----------------------------------------------------------------------------|
| 1.0.0   | 2026-06-18 | Claude_Opus_4.8 | 初版：识别高分且源为 AV1 的卡住视频，删源+删成片+重置 PENDING，交由调度器重下(H.264)重渲 |

背景
----
imageio-ffmpeg 内置的 AOM AV1 解码器解码 YouTube AV1 流时会**间歇性 SIGSEGV**，
导致 `_burn_subtitles` 渲染崩溃。pipeline_manager v3.16.0 / pipeline_agent v1.7.0
已将下载格式改为优先 H.264，但**已经下载到本地的 AV1 源**在重试时会被复用 →
再次崩溃。本脚本把这些视频的本地 AV1 源删掉并重置为 PENDING，让流水线按新策略
**重新下载为 H.264** 再渲染，从根本上绕开崩溃。

⚠️ 重负载约束（硬性）
--------------------
重置后，调度器会对这些视频执行「重新下载 + Whisper + 渲染」= **吃多核 CPU 的重活**。
本机与实盘交易行情管线共用，**美股盘中禁止重负载**（北京 21:15–次日 04:15）。
- 本脚本默认**拒绝在盘中运行**（可 --force 跳过，不建议）。
- 强烈建议用 --limit 小批量重置（默认 5），确保渲染在下一次开盘前跑完。
- 重置只是把任务排队；真正的重活由调度器执行，运行期间请 `uptime` 盯 load1。

用法
----
    # 预览将要处理哪些视频（默认 dry-run，不改任何东西）
    .venv/bin/python scripts/recover_av1_videos.py

    # 实际执行：重置分数最高的 5 个 AV1 卡住视频
    .venv/bin/python scripts/recover_av1_videos.py --apply --limit 5
"""
from __future__ import annotations

import os
import sys
import argparse
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.db import PipelineDB                       # noqa: E402
from video_processing.utils.file_utils import (                 # noqa: E402
    VIDEO_CONTAINER_SUFFIXES,
    safe_remove,
)

OUTPUT_DIR = PROJECT_ROOT / "output"
ARCHIVE_DIR = OUTPUT_DIR / "original_video"

# 非终态、需要恢复的状态（PUBLISHED/SEGMENTED/DISCOVERY 不动）
DEFAULT_STATUSES = ["FAILED", "LOGIN_REQUIRED", "DOWNLOADING"]


def beijing_now() -> datetime:
    """返回北京时间（UTC+8，不依赖主机时区设置）。"""
    return datetime.now(timezone.utc) + timedelta(hours=8)


def in_market_window(now_bj: datetime) -> bool:
    """美股盘中 = 北京 21:15 → 次日 04:15。"""
    minutes = now_bj.hour * 60 + now_bj.minute
    return minutes >= (21 * 60 + 15) or minutes < (4 * 60 + 15)


def source_files(yid: str) -> list[Path]:
    """该 yid 在热目录 + 冷归档里的所有源视频主文件（stem == yid）。"""
    found: list[Path] = []
    for d in (OUTPUT_DIR, ARCHIVE_DIR):
        if not d.is_dir():
            continue
        for f in d.glob(f"{yid}.*"):
            if f.suffix.lower() in VIDEO_CONTAINER_SUFFIXES and f.stem == yid:
                found.append(f)
    return found


def video_codec(path: Path) -> str:
    """ffprobe 取首个视频流编码；失败返回空串。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def derived_render_files(yid: str) -> list[Path]:
    """需要删除的成片/中途产物（强制重渲）；保留 cover/copy/title/.ass 以省重复工。"""
    return [p for p in (
        OUTPUT_DIR / f"{yid}_vertical.mp4",
        OUTPUT_DIR / f"{yid}_vertical.staged.mp4",
        OUTPUT_DIR / f"{yid}_trimmed.mp4",
    ) if p.exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description="恢复 AV1 缓存导致崩溃的高分视频")
    ap.add_argument("--apply", action="store_true", help="实际执行（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=5, help="单次最多重置多少个（默认 5）")
    ap.add_argument("--min-score", type=int, default=75, help="只处理分数 >= 该值（默认 75）")
    ap.add_argument("--statuses", default=",".join(DEFAULT_STATUSES),
                    help=f"逗号分隔的目标状态（默认 {','.join(DEFAULT_STATUSES)}）")
    ap.add_argument("--force", action="store_true", help="盘中也允许运行（不建议）")
    args = ap.parse_args()

    now_bj = beijing_now()
    load1 = os.getloadavg()[0]
    print(f"[时间] 北京 {now_bj:%Y-%m-%d %H:%M}  |  load1={load1:.2f}  |  "
          f"模式={'APPLY' if args.apply else 'DRY-RUN'}")

    if in_market_window(now_bj):
        print("⛔ 当前处于美股盘中窗口（北京 21:15–04:15）。重负载会饿死实盘行情管线。")
        if not args.force:
            print("   已拒绝运行。请等北京 04:15 收盘后再跑，或 --force 强制（不建议）。")
            return 2
        print("   --force 已指定，继续（请务必 nice -n 19 并盯 load1）。")

    db = PipelineDB()
    seen: set[str] = set()
    candidates: list[dict] = []
    for status in [s.strip() for s in args.statuses.split(",") if s.strip()]:
        for v in db.get_videos_by_status(status):
            yid = v["youtube_id"]
            if yid in seen or (v.get("score") or 0) < args.min_score:
                continue
            seen.add(yid)
            srcs = source_files(yid)
            if not srcs:
                continue  # 无本地源 → 重试本就会按新策略重下 H.264，无需处理
            if any(video_codec(s) == "av1" for s in srcs):
                candidates.append({"v": v, "srcs": srcs})

    candidates.sort(key=lambda c: -(c["v"].get("score") or 0))
    print(f"[扫描] 命中 {len(candidates)} 个「高分 + 本地源为 AV1」的卡住视频。")
    if not candidates:
        return 0

    batch = candidates[: args.limit]
    print(f"[计划] 本次处理前 {len(batch)} 个（--limit {args.limit}）：\n")
    for c in batch:
        v = c["v"]
        print(f"  - {v['youtube_id']} (score={v.get('score')}, status={v['status']}, "
              f"slice={v.get('slice_index', 0)})")
        for s in c["srcs"]:
            print(f"      删源: {s.name}")
        for d in derived_render_files(v["youtube_id"]):
            print(f"      删成片: {d.name}")

    if not args.apply:
        print("\n(dry-run，未改动。加 --apply 实际执行。)")
        return 0

    print("\n[执行]")
    for c in batch:
        v = c["v"]
        yid = v["youtube_id"]
        for s in c["srcs"]:
            print(f"  rm {s}  -> {safe_remove(s)}")
        for d in derived_render_files(yid):
            print(f"  rm {d}  -> {safe_remove(d)}")
        db.update_video_status(yid, "PENDING", slice_index=v.get("slice_index", 0))
        print(f"  ✅ {yid} -> PENDING")

    print(f"\n完成：已重置 {len(batch)} 个。调度器将按 H.264 重新下载并重渲。")
    print("⚠️ 渲染是重活，请确认在下一次开盘（北京 21:15）前能跑完，期间用 `uptime` 盯 load1。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

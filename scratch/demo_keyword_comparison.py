#!/usr/bin/env python3
"""
[演示脚本] 动态热词注入 —— 效果对比展示
只读演示，不修改任何数据库或生产配置。

用法：
    .venv/bin/python scratch/demo_keyword_comparison.py

# [Claude_Sonnet_4.6_Thinking_planning]
"""

import sys
import json
import time
import httpx
from pathlib import Path
from datetime import datetime, timezone

# ── 颜色输出工具 ────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
RED    = "\033[31m"
BLUE   = "\033[34m"

def hr(char="─", width=62):
    print(char * width)

def header(title):
    hr("═")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    hr("═")

def section(title):
    print()
    print(f"{BOLD}{YELLOW}▶ {title}{RESET}")
    hr()

# ── 静态词库（旧方案 · 原 DISCOVERY_KEYWORDS）─────────────────────────────
STATIC_KEYWORDS = [
    "AI interview",
    "tech keynote 2026",
    "business podcast",
    "founder speech",
]

# ── HN 热词过滤信号（与 fetch_trending_keywords.py 完全一致）───────────────
TECH_SIGNALS = [
    "AI", "LLM", "GPT", "Claude", "Gemini", "model", "agent",
    "startup", "funding", "open source", "framework", "API",
    "machine learning", "deep learning", "research", "paper",
]

HN_TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL       = "https://hacker-news.firebaseio.com/v0/item/{}.json"
CACHE_PATH        = Path(__file__).parent.parent / "output" / "trending_keywords.json"


def fetch_hn_keywords_live(top_n: int = 30) -> tuple[list[str], list[dict]]:
    """从 HN 拉取热词，同时返回命中的原始标题数据供展示"""
    print(f"  {DIM}正在请求 HackerNews API…{RESET}")
    try:
        ids = httpx.get(HN_TOPSTORIES_URL, timeout=10).json()[:top_n]
    except Exception as e:
        print(f"  {RED}✗ HN API 请求失败: {e}{RESET}")
        return [], []

    keywords = []
    raw_hits = []
    with httpx.Client(timeout=5) as client:
        for i, story_id in enumerate(ids, 1):
            try:
                item = client.get(HN_ITEM_URL.format(story_id)).json()
                title = item.get("title", "")
                score = item.get("score", 0)
                signal = next((s for s in TECH_SIGNALS if s.lower() in title.lower()), None)
                if signal:
                    keyword = " ".join(title.split()[:5])
                    keywords.append(keyword)
                    raw_hits.append({"title": title, "score": score, "signal": signal, "keyword": keyword})
            except Exception:
                continue

    return list(dict.fromkeys(keywords)), raw_hits  # 去重保序


def load_cached_keywords() -> tuple[list[str], float]:
    """读取本地缓存，返回关键词列表及缓存时间戳"""
    if not CACHE_PATH.exists():
        return [], 0.0
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return data.get("keywords", []), data.get("updated_at", 0.0)
    except Exception:
        return [], 0.0


def simulate_yt_search_queries(keywords: list[str]) -> list[str]:
    """模拟 discover_new_channels() 会构造的 yt-dlp 搜索命令（只展示，不执行）"""
    return [f'yt-dlp "ytsearch5:{kw}" --print %(channel_id)s|%(channel)s' for kw in keywords]


# ══════════════════════════════════════════════════════════════════════════════
# 主演示流程
# ══════════════════════════════════════════════════════════════════════════════
def main():
    header("动态热词注入 · 效果对比演示  (只读，不修改任何生产数据)")

    # ─────────────────────────────────────────────────────────────────────────
    # PART 1 — 旧方案（纯静态关键词）
    # ─────────────────────────────────────────────────────────────────────────
    section("BEFORE  旧方案 — 静态关键词（硬编码，永远不变）")
    print(f"  搜索词数量: {BOLD}{len(STATIC_KEYWORDS)}{RESET} 个\n")
    for kw in STATIC_KEYWORDS:
        print(f"  {DIM}•{RESET} {kw}")
    print()
    print(f"  {DIM}→ yt-dlp 将对以上 {len(STATIC_KEYWORDS)} 个词各执行一次 ytsearch5:{RESET}")

    # ─────────────────────────────────────────────────────────────────────────
    # PART 2 — 检查缓存状态
    # ─────────────────────────────────────────────────────────────────────────
    section("缓存状态检查")
    cached_kws, cached_ts = load_cached_keywords()
    if cached_kws:
        age_min = (time.time() - cached_ts) / 60
        cache_time = datetime.fromtimestamp(cached_ts, tz=timezone.utc).astimezone()
        freshness = f"{GREEN}✓ 有效 (距上次刷新 {age_min:.1f} 分钟){RESET}" if age_min < 60 else f"{YELLOW}⚠ 已过期 (距上次刷新 {age_min:.0f} 分钟，下次调用将自动刷新){RESET}"
        print(f"  缓存文件: {CACHE_PATH.name}")
        print(f"  更新时间: {cache_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"  缓存状态: {freshness}")
        print(f"  缓存词条: {len(cached_kws)} 个")
    else:
        print(f"  {YELLOW}⚠ 无有效缓存，将实时从 HN 拉取{RESET}")

    # ─────────────────────────────────────────────────────────────────────────
    # PART 3 — 实时拉取 HN 热词（演示用，强制重新拉取以展示完整流程）
    # ─────────────────────────────────────────────────────────────────────────
    section("实时拉取 HackerNews Top Stories（top_n=30）")
    t0 = time.time()
    dynamic_kws, raw_hits = fetch_hn_keywords_live(top_n=30)
    elapsed = time.time() - t0

    if raw_hits:
        print(f"  {GREEN}✓ 命中 {len(raw_hits)} 条科技/AI 相关帖子 (耗时 {elapsed:.1f}s){RESET}\n")
        print(f"  {'HN 热榜分':<8}  {'触发信号':<14}  {'原始标题'}")
        hr("-", 62)
        for hit in raw_hits:
            score_col  = f"{CYAN}{hit['score']:<8}{RESET}"
            signal_col = f"{YELLOW}{hit['signal']:<14}{RESET}"
            title_col  = hit["title"][:38] + ("…" if len(hit["title"]) > 38 else "")
            print(f"  {score_col} {signal_col} {title_col}")
    else:
        print(f"  {RED}✗ 未获取到任何热词（网络错误或无相关帖子）{RESET}")

    # ─────────────────────────────────────────────────────────────────────────
    # PART 4 — 新方案（合并后词库）
    # ─────────────────────────────────────────────────────────────────────────
    section("AFTER  新方案 — 静态 + 动态合并关键词")
    merged = list(dict.fromkeys(STATIC_KEYWORDS + dynamic_kws))
    print(f"  搜索词数量: {BOLD}{GREEN}{len(merged)}{RESET} 个"
          f"  ({len(STATIC_KEYWORDS)} 静态 + {len(dynamic_kws)} 动态)\n")

    for i, kw in enumerate(merged):
        tag = f"{DIM}[static]{RESET} " if kw in STATIC_KEYWORDS else f"{GREEN}[HN今日]{RESET} "
        print(f"  {tag}{kw}")

    # ─────────────────────────────────────────────────────────────────────────
    # PART 5 — 数量对比总结
    # ─────────────────────────────────────────────────────────────────────────
    section("效果对比总结")
    print(f"  {'指标':<24} {'旧方案（静态）':>12}   {'新方案（动态）':>12}")
    hr("-", 62)
    print(f"  {'搜索词总数':<26} {len(STATIC_KEYWORDS):>8} 个   {BOLD}{GREEN}{len(merged):>8} 个{RESET}")
    print(f"  {'覆盖今日 HN 热点':<25} {'✗':>9}     {GREEN}{'✓':>9}{RESET}")
    print(f"  {'自动更新频率':<25} {'永不更新':>8}   {GREEN}{'每小时':>8}{RESET}")
    print(f"  {'回退保护':<25} {'N/A':>9}     {GREEN}{'✓ 自动回退':>9}{RESET}")
    print(f"  {'需要更改代码':<25} {'每次都要':>8}   {GREEN}{'不需要':>8}{RESET}")

    print()
    hr("═")
    print(f"  {BOLD}✅  演示完成。以上为只读展示，未修改任何数据库或配置文件。{RESET}")
    print(f"  如确认效果良好，只需在 .env 中加入：")
    print(f"  {CYAN}  ENABLE_DYNAMIC_KEYWORDS=true{RESET}")
    hr("═")


if __name__ == "__main__":
    main()

"""
动态热词抓取器 — 基于 HackerNews Top Stories 提炼科技热词
用于每日注入 monitor_channels.py 的动态搜索词库。

# Modification History
| Version | Date       | Author                         | Description |
|---------|------------|--------------------------------|-------------|
| 1.0.0   | 2026-06-07 | Gemini_3.5_Flash_High_planning | 初始创建     |
"""

import sys
import json
import time
from pathlib import Path
import httpx

# 添加 src 到 path 以便导入 settings
sys.path.append(str(Path(__file__).parent.parent / "src"))
from config.settings import settings

HN_TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"

# AI/科技过滤关键词（只保留与技术/AI/商业相关的热词）
# [Gemini_3.5_Flash_High_planning] 提取符合以下信号的标题
TECH_SIGNALS = [
    "AI", "LLM", "GPT", "Claude", "Gemini", "model", "agent",
    "startup", "funding", "open source", "framework", "API",
    "machine learning", "deep learning", "research", "paper",
]

def fetch_hn_trending_keywords(top_n: int = 30) -> list[str]:
    """从 HN 当日热帖中提取科技/AI 相关搜索词"""
    try:
        # [Gemini_3.5_Flash_High_planning] 使用 httpx 代替 requests，因为 requests 未在 requirements 中声明
        response = httpx.get(HN_TOPSTORIES_URL, timeout=10)
        response.raise_for_status()
        ids = response.json()[:top_n]
    except Exception as e:
        print(f"[TrendFetch] HN API error: {e}")
        return []
    
    keywords = []
    # 使用 httpx Client 复用连接，提高请求效率
    with httpx.Client(timeout=5) as client:
        for story_id in ids:
            try:
                res = client.get(HN_ITEM_URL.format(story_id))
                res.raise_for_status()
                item = res.json()
                title = item.get("title", "")
                # 简单规则：标题包含科技信号词时，取前5个词作为搜索词
                if any(sig.lower() in title.lower() for sig in TECH_SIGNALS):
                    words = title.split()[:5]
                    keyword = " ".join(words)
                    keywords.append(keyword)
                    print(f"  [TrendFetch] Keyword extracted: {keyword!r}")
            except Exception as e:
                # [Gemini_3.5_Flash_High_planning] 容错处理，单条失败不影响整体
                continue
    
    return list(dict.fromkeys(keywords))  # 去重，保序


def get_dynamic_keywords() -> list[str]:
    """读取或刷新动态关键词缓存（每小时最多刷新一次）"""
    settings.ensure_directories()
    cache_path = settings.default_output_dir / "trending_keywords.json"
    
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - data.get("updated_at", 0) < 3600:  # 1小时缓存
                # [Gemini_3.5_Flash_High_planning] 命中缓存时直接返回
                return data.get("keywords", [])
        except Exception as e:
            print(f"[TrendFetch] Cache read error: {e}, will re-fetch")
    
    top_n = getattr(settings, "hn_top_n", 30)
    keywords = fetch_hn_trending_keywords(top_n=top_n)
    
    try:
        cache_path.write_text(json.dumps({
            "updated_at": time.time(),
            "keywords": keywords,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[TrendFetch] Cache write error: {e}")
        
    return keywords


if __name__ == "__main__":
    kws = get_dynamic_keywords()
    print(f"\nFetched {len(kws)} trending keywords:")
    for kw in kws:
        print(f"  - {kw}")

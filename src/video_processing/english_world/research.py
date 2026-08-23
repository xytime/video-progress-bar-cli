"""英语世界短视频候选研究服务。

只读取公开 YouTube 元数据并写入独立 English World Job 账本；不下载媒体、
不调用学习卡渲染器、也不接触发布账本。儿童适宜性在此仅是元数据预筛，制作前
仍必须根据实际视频和字幕复核。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-21 | Codex | 新增可审计的英语世界候选检索、风险预筛和独立任务完成服务。 |
| 1.0.1 | 2026-08-21 | Codex | 改用当前 yt-dlp 支持的 ytsearch 提取器，日期仍由元数据排序。 |
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Iterable
from uuid import uuid4

from video_processing.db.database import PipelineDB

logger = logging.getLogger(__name__)

_SEARCH_QUERIES = (
    "BBC Earth wildlife news",
    "science news explained for kids",
    "positive technology news explained",
    "health education news explained",
    "culture human interest news short",
)
_BLOCKED_TERMS = frozenset({
    "war", "military", "missile", "battle", "politic", "election", "president",
    "crime", "murder", "shooting", "terror", "disaster", "earthquake", "flood",
    "death", "dead", "fatal", "adult", "sex", "drug", "weapon",
})
_TOPIC_TERMS = {
    "nature": frozenset({"animal", "wildlife", "ocean", "whale", "nature", "species", "forest"}),
    "science": frozenset({"science", "space", "research", "study", "discovery", "climate"}),
    "education": frozenset({"school", "student", "learning", "education", "teacher"}),
    "technology": frozenset({"technology", "robot", "innovation", "science", "ai"}),
    "life": frozenset({"food", "culture", "community", "family", "people", "health"}),
}


class EnglishWorldResearchService:
    """将外部元数据搜索收敛为可选择、可追溯、但不产生媒体副作用的候选任务。"""

    def __init__(
        self,
        db: PipelineDB,
        *,
        searcher: Callable[[str], Iterable[dict[str, Any]]] | None = None,
        inspector: Callable[[str], dict[str, Any]] | None = None,
    ):
        self.db = db
        self._searcher = searcher or _youtube_search
        self._inspector = inspector or _youtube_inspect

    def research(self, job_id: str) -> dict[str, Any] | None:
        """领取研究任务并保存候选；失败仅写本任务，不影响通用队列。"""
        job = self.db.claim_english_world_job_for_research(job_id)
        if job is None:
            return None
        try:
            source_url = str(job.get("source_url") or "").strip()
            raw_items = [self._inspector(source_url)] if source_url else self._find_today_candidates()
            candidates = _rank_candidates(raw_items)
            if not candidates:
                raise RuntimeError("没有找到通过儿童题材预筛的候选；未创建任何视频任务")
            self.db.complete_english_world_research(job_id, candidates=candidates)
            return self.db.get_english_world_job(job_id)
        except Exception as exc:  # noqa: BLE001 - background worker must persist its failure receipt
            logger.exception("[EnglishWorld] research failed: job=%s", job_id)
            self.db.fail_english_world_job(job_id, str(exc))
            return self.db.get_english_world_job(job_id)

    def _find_today_candidates(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for query in _SEARCH_QUERIES:
            for item in self._searcher(query):
                key = str(item.get("id") or item.get("webpage_url") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                results.append(item)
        return results


def _youtube_search(query: str) -> Iterable[dict[str, Any]]:
    """使用 yt-dlp 的只读搜索提取器，不下载或写入媒体文件。"""
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(f"ytsearch8:{query}", download=False)
    return list((info or {}).get("entries") or [])


def _youtube_inspect(source_url: str) -> dict[str, Any]:
    """只读取用户明确提供 URL 的元数据，仍不下载内容。"""
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        return ydl.extract_info(source_url, download=False) or {}


def _rank_candidates(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """用透明的关键词与时长规则预筛；不将预筛误称为内容审查。"""
    candidates: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).date()
    for item in items:
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "")
        blob = f"{title} {description}".lower()
        if not title or any(term in blob for term in _BLOCKED_TERMS):
            continue
        duration = _as_int(item.get("duration"))
        if duration is not None and not 15 <= duration <= 150:
            continue
        video_id = str(item.get("id") or "").strip()
        url = str(item.get("webpage_url") or item.get("original_url") or "").strip()
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url:
            continue
        topic = _topic_for(blob)
        upload_date = str(item.get("upload_date") or "") or None
        recency = 1 if upload_date == now.strftime("%Y%m%d") else 0
        score = 20 + recency * 20 + (10 if duration else 0) + _topic_score(topic)
        candidates.append({
            "id": uuid4().hex,
            "source_url": url,
            "youtube_id": video_id or None,
            "source_title": title,
            "source_channel": str(item.get("channel") or item.get("uploader") or "未知来源"),
            "upload_date": upload_date,
            "duration_sec": duration,
            "topic": topic,
            "learning_value": _learning_value(topic),
            "safety_note": "已通过标题、简介和时长预筛；制作前仍须核对实际画面与英文字幕。",
            "caption_status": "待制作前核验",
            "recommendation_score": score,
        })
    candidates.sort(key=lambda item: (-int(item["recommendation_score"]), str(item["source_title"]).lower()))
    return candidates[:5]


def _topic_for(blob: str) -> str:
    for topic, terms in _TOPIC_TERMS.items():
        if any(term in blob for term in terms):
            return topic
    return "life"


def _topic_score(topic: str) -> int:
    return {"nature": 18, "science": 16, "education": 14, "technology": 12, "life": 10}[topic]


def _learning_value(topic: str) -> str:
    return {
        "nature": "适合学习自然观察、动物与环境主题词汇。",
        "science": "适合学习新闻式科学表达与因果句型。",
        "education": "适合学习校园与成长主题的日常表达。",
        "technology": "适合学习生活化科技词汇，制作前复核是否适龄。",
        "life": "适合学习日常社会与人文主题的完整听读表达。",
    }[topic]


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

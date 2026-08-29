"""英语世界短视频候选研究服务。

只读取公开 YouTube 元数据并写入独立 English World Job 账本；不下载媒体、
不调用学习卡渲染器、也不接触发布账本。儿童适宜性在此仅是元数据预筛，制作前
仍必须根据实际视频和字幕复核。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-21 | Codex | 新增可审计的英语世界候选检索、风险预筛和独立任务完成服务。 |
| 1.0.1 | 2026-08-21 | Codex | 改用当前 yt-dlp 支持的 ytsearch 提取器，日期仍由元数据排序。 |
| 1.0.2 | 2026-08-24 | Codex | 候选元数据读取继承已验证的 YouTube Cookie；单个搜索批次受限时跳过并继续其余查询。 |
| 1.0.3 | 2026-08-24 | Codex | yt-dlp 搜索无可用元数据时，以既有白名单频道的官方 Data API / RSS 目录只读降级。 |
| 1.0.4 | 2026-08-24 | Codex | 补足新闻标题中的政治、冲突和伤害线索预筛，避免目录降级扩大候选风险面。 |
| 1.0.5 | 2026-08-24 | Codex | 目录降级以预筛结果为空为准；天气/灾害线索只标记画面复核，不再关键词误杀。 |
| 1.0.6 | 2026-08-29 | Codex | 搜索与显式 URL 候选均按频道 ID 严格限制为三家授权来源，拒绝仅凭频道名冒充。 |
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Iterable
from uuid import uuid4

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.utils.youtube_catalog import YouTubeCatalogError, fetch_channel_catalog

logger = logging.getLogger(__name__)

_SEARCH_QUERIES = (
    "BBC Earth wildlife news",
    "science news explained for kids",
    "positive technology news explained",
    "health education news explained",
    "culture human interest news short",
)
_APPROVED_SOURCE_CHANNELS = (
    ("UCWUA2W6LueNy9BSovivFVvQ", "CBC Kids News"),
    ("UCAeWdyKJXGWmVAXFpgLNNTg", "CBS Evening News"),
    ("UCBi2mrWuNuyYy4gbM6fU18Q", "ABC News"),
)
_HARD_BLOCKED_TERMS = frozenset({
    "war", "military", "missile", "battle", "politic", "election", "president",
    "crime", "murder", "shooting", "terror", "adult", "sex", "drug", "weapon",
    "trump", "iran", "tariff", "sanction", "border",
})
_VISUAL_REVIEW_TERMS = frozenset({
    "disaster", "earthquake", "flood", "storm", "tornado", "lightning", "wildfire",
    "death", "dead", "fatal", "victim", "remains", "evacuation", "emergency", "threat",
})
_TOPIC_TERMS = {
    "nature": frozenset({"animal", "wildlife", "ocean", "whale", "nature", "species", "forest"}),
    "science": frozenset({"science", "space", "research", "study", "discovery", "climate", "weather", "storm", "tornado", "lightning"}),
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
            if not candidates and not source_url:
                candidates = _rank_candidates(_catalog_fallback_candidates())
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
            try:
                items = self._searcher(query)
            except Exception as exc:  # noqa: BLE001 - 外部元数据批次应彼此隔离
                logger.warning(
                    "[EnglishWorld] search batch skipped: query=%r error_type=%s",
                    query,
                    type(exc).__name__,
                )
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("id") or item.get("webpage_url") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                results.append(item)
        return results


def _catalog_fallback_candidates() -> list[dict[str, Any]]:
    """读取既有授权频道目录；仅在 yt-dlp 搜索无可用条目时启用。"""
    results: list[dict[str, Any]] = []
    for channel_id, channel_name in _APPROVED_SOURCE_CHANNELS:
        try:
            catalog = fetch_channel_catalog(
                channel_id,
                lookback_days=14,
                api_key=settings.youtube_data_api_key,
                timeout_sec=settings.youtube_data_api_timeout_sec,
            )
        except YouTubeCatalogError as exc:
            logger.warning(
                "[EnglishWorld] catalog fallback skipped: channel=%s error_type=%s",
                channel_name,
                type(exc).__name__,
            )
            continue
        for video in catalog.videos:
            results.append({
                "id": video.youtube_id,
                "webpage_url": f"https://www.youtube.com/watch?v={video.youtube_id}",
                "title": video.title,
                "channel": channel_name,
                "channel_id": channel_id,
                "upload_date": video.upload_date,
                "duration": video.duration_sec,
            })
    return results


def _youtube_ydl_options() -> dict[str, Any]:
    """将 settings 的 Cookie 单一真相源适配为 yt-dlp Python API 选项。"""
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # 搜索结果中的单条视频受限不应中断其它候选的元数据预筛。
        "ignoreerrors": True,
    }
    cookie_args = settings.get_yt_cookie_args()
    if cookie_args[:1] == ["--cookies"] and len(cookie_args) == 2:
        options["cookiefile"] = cookie_args[1]
    elif cookie_args[:1] == ["--cookies-from-browser"] and len(cookie_args) == 2:
        options["cookiesfrombrowser"] = (cookie_args[1],)
    return options


def _youtube_search(query: str) -> Iterable[dict[str, Any]]:
    """使用 yt-dlp 的只读搜索提取器，不下载或写入媒体文件。"""
    from yt_dlp import YoutubeDL

    with YoutubeDL(_youtube_ydl_options()) as ydl:
        info = ydl.extract_info(f"ytsearch8:{query}", download=False)
    return list((info or {}).get("entries") or [])


def _youtube_inspect(source_url: str) -> dict[str, Any]:
    """只读取用户明确提供 URL 的元数据，仍不下载内容。"""
    from yt_dlp import YoutubeDL

    with YoutubeDL(_youtube_ydl_options()) as ydl:
        return ydl.extract_info(source_url, download=False) or {}


def _rank_candidates(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """用透明的关键词与时长规则预筛；不将预筛误称为内容审查。"""
    candidates: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).date()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        approved_channel = _approved_channel_name(item)
        if approved_channel is None:
            continue
        description = str(item.get("description") or "")
        blob = f"{title} {description}".lower()
        if not title or any(term in blob for term in _HARD_BLOCKED_TERMS):
            continue
        duration = _as_int(item.get("duration"))
        # 成片最多 30 秒不等于原始报道必须只有 30 秒；较长来源可在制作前选择自然句边界。
        if duration is not None and not 15 <= duration <= 600:
            continue
        video_id = str(item.get("id") or "").strip()
        url = str(item.get("webpage_url") or item.get("original_url") or "").strip()
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url:
            continue
        topic = _topic_for(blob)
        needs_visual_review = any(term in blob for term in _VISUAL_REVIEW_TERMS)
        upload_date = str(item.get("upload_date") or "") or None
        recency = 1 if upload_date == now.strftime("%Y%m%d") else 0
        score = 20 + recency * 20 + (10 if duration else 0) + _topic_score(topic)
        candidates.append({
            "id": uuid4().hex,
            "source_url": url,
            "youtube_id": video_id or None,
            "source_title": title,
            "source_channel": approved_channel,
            "upload_date": upload_date,
            "duration_sec": duration,
            "topic": topic,
            "learning_value": _learning_value(topic),
            "safety_note": (
                "标题/简介含灾害或紧急线索；仅可在核对无真实伤亡、恐慌、疏散或令人不适画面后制作。"
                if needs_visual_review else
                "已通过标题、简介和时长预筛；制作前仍须核对实际画面与英文字幕。"
            ),
            "caption_status": "待制作前核验",
            "recommendation_score": score,
        })
    candidates.sort(key=lambda item: (-int(item["recommendation_score"]), str(item["source_title"]).lower()))
    return candidates[:5]


def _approved_channel_name(item: dict[str, Any]) -> str | None:
    """只相信 YouTube 的稳定频道 ID；显示名不能授予来源能力。"""
    channel_id = str(item.get("channel_id") or item.get("uploader_id") or "").strip()
    for approved_id, approved_name in _APPROVED_SOURCE_CHANNELS:
        if channel_id == approved_id:
            return approved_name
    return None


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

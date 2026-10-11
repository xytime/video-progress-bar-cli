"""专题候选的纯规则：关键词命中不授予加工或发布权限。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-11 | Codex | 实现 v0.2 字段、源身份、元数据与版本规则；导入无运行副作用 |
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CATEGORIES = ("宏观经济", "科技产业", "商业历史", "健康科学", "地缘战略")
REASONS = ("不相关", "来源不可信", "不适合受众", "已重复", "其他")
TERMINAL = ("COMPLETE", "PARTIAL", "FAILED", "INTERRUPTED")


class TopicError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def utc_now():
    return datetime.now(timezone.utc)


def stamp(now):
    return now.astimezone(timezone.utc).isoformat()


def quota_day(now):
    return now.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def source_key(video_id):
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise TopicError("INVALID_SOURCE", "视频身份无效", 422)
    return hashlib.sha256(("youtube:" + video_id).encode()).hexdigest()


def topic_fields(value):
    name = str(value.get("name", "")).strip()
    query = " ".join(str(value.get("query", "")).split())
    category = value.get("category")
    lookback, days = value.get("lookback_days", 7), value.get("valid_days", 7)
    if not 1 <= len(name) <= 40:
        raise TopicError("INVALID_NAME", "名称应为 1–40 个字符", 422)
    if not 1 <= len(query) <= 120 or any(ord(c) < 32 for c in query):
        raise TopicError("INVALID_QUERY", "查询词应为 1–120 个字符", 422)
    if category not in CATEGORIES:
        raise TopicError("INVALID_CATEGORY", "请选择有效类别", 422)
    if type(lookback) is not int or lookback not in (3, 7, 30):
        raise TopicError("INVALID_LOOKBACK", "搜索范围可选 3、7、30 天", 422)
    if type(days) is not int or not 1 <= days <= 30:
        raise TopicError("INVALID_EXPIRY", "有效期应为 1–30 天", 422)
    normalized = unicodedata.normalize("NFKC", query).casefold()
    return dict(name=name, query=query, category=category, lookback_days=lookback,
                valid_days=days, identity=digest([normalized, category, lookback]))


def seconds(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match or not any(match.groups()):
        return None
    h, m, s = (int(v or 0) for v in match.groups())
    return h * 3600 + m * 60 + s


def count(value):
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
        return n if n >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def metadata(video_id, item):
    """只保留本期所需字段；查询成功未返回与查询失败由调用者区分。"""
    source_key(video_id)
    if item is None:
        return dict(youtube_id=video_id, availability="UNAVAILABLE", title="视频不可用",
                    description="", channel_id="", channel_name="", published_at=None,
                    duration=None, views=None, likes=None, language=None)
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    published = snippet.get("publishedAt")
    try:
        if datetime.fromisoformat(published.replace("Z", "+00:00")).tzinfo is None:
            published = None
    except (AttributeError, ValueError, TypeError):
        published = None
    live = snippet.get("liveBroadcastContent")
    status = item.get("status") or {}
    unavailable = status.get("privacyStatus") == "private" or status.get("uploadStatus") in ("deleted", "failed", "rejected")
    availability = "UNAVAILABLE" if unavailable else "LIVE" if live in ("live", "upcoming") else "AVAILABLE" if live == "none" else "UNKNOWN"
    return dict(youtube_id=video_id, title=str(snippet.get("title") or "")[:1000],
                description=str(snippet.get("description") or "")[:10000],
                channel_id=str(snippet.get("channelId") or "")[:100],
                channel_name=str(snippet.get("channelTitle") or "")[:500],
                published_at=published, duration=seconds((item.get("contentDetails") or {}).get("duration")),
                views=count(stats.get("viewCount")), likes=count(stats.get("likeCount")),
                language=None, availability=availability)


def eligibility(meta, check, presence):
    if meta["availability"] in ("UNAVAILABLE", "LIVE"):
        return "UNAVAILABLE", "源视频不可用、直播中或尚未开播"
    if meta["availability"] == "UNKNOWN" or not all(meta.get(k) for k in ("title", "channel_id", "channel_name", "published_at")) or meta["duration"] is None:
        return "INCOMPLETE", "必要资料不足，不能收藏"
    if not 180 <= meta["duration"] <= 1800:
        return "RESTRICTED", "时长受限：需为 3–30 分钟"
    if presence.get("blacklisted") or presence.get("channel_blocked"):
        return "RESTRICTED", "已在黑名单或频道排除名单"
    hit = check(meta)
    if hit:
        return "RESTRICTED", hit
    return "CHECKABLE", "可人工核实；元数据检查不代表内容或发布批准"


def content_version(meta, rule_version, state, reason):
    material = {k: v for k, v in meta.items() if k not in ("views", "likes")}
    return digest([material, rule_version, state, reason])

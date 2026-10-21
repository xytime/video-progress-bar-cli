"""视频预筛选纯规则；数值合格始终不授予生产资格。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 参数、精确时间窗口、缺失数据及人工预筛选分类 |
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from decimal import Decimal

from .topic_candidates import TopicError, digest

PURPOSE = "PREFILTER_ONLY"
DEFAULTS = dict(name="人物与科技快讯", keywords=["Elon Musk", "Jensen Huang", "plague"],
                lookback_hours=48, max_duration=300, min_views=10000,
                min_like_ratio=0.015, candidate_count=50)
CATEGORIES = ("QUALIFIED", "REJECTED", "INCOMPLETE", "FAILED")


def fields(value):
    name = value.get("name", "").strip()
    words = value.get("keywords")
    if not 1 <= len(name) <= 40:
        raise TopicError("INVALID_NAME", "规则名称需为 1–40 字", 422)
    if not isinstance(words, list) or not 1 <= len(words) <= 10:
        raise TopicError("INVALID_KEYWORDS", "请输入 1–10 个关键词，每行一个短语", 422)
    keywords = []
    for word in words:
        if not isinstance(word, str) or not 1 <= len(word.strip()) <= 80 or re.search(r'["|\x00-\x1f]', word):
            raise TopicError("INVALID_KEYWORDS", "短语需为 1–80 字，不含引号、竖线或控制字符", 422)
        word = " ".join(word.split())
        if word.casefold() not in {w.casefold() for w in keywords}:
            keywords.append(word)
    query = "|".join('"' + w + '"' for w in keywords)
    if len(query.encode("utf-8")) > 450:
        raise TopicError("INVALID_KEYWORDS", "关键词合并后过长，请减少短语", 422)
    result = dict(name=name, keywords=keywords, query=query, purpose=PURPOSE)
    for key, low, high, label in (("lookback_hours", 1, 720, "回溯小时"),
                                 ("max_duration", 1, 1800, "最长秒数"),
                                 ("min_views", 0, 10**12, "最低播放量"),
                                 ("candidate_count", 1, 50, "候选数量")):
        number = value.get(key)
        if type(number) is not int or not low <= number <= high:
            raise TopicError("INVALID_" + key.upper(), f"{label}需为 {low}–{high} 的整数", 422)
        result[key] = number
    ratio = value.get("min_like_ratio")
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
        raise TopicError("INVALID_RATIO", "点赞率需在 0%–100% 之间", 422)
    result["min_like_ratio"] = ratio
    return result


def classify(meta, rule, started, presence, policy_reason=None):
    """类别互斥；保留所有明确不达标原因，缺失绝不冒充 0。"""
    missing = []
    for key in ("title", "channel_id", "channel_name", "published_at"):
        if not meta.get(key):
            missing.append(key)
    for key in ("duration", "views", "likes"):
        if meta.get(key) is None:
            missing.append(key)
    if meta.get("availability") == "UNKNOWN":
        missing.append("视频状态")
    reasons = []
    if meta.get("availability") in ("UNAVAILABLE", "LIVE"):
        reasons.append("视频不可用、直播中、未开播或回放处理中")
    if missing and not reasons:
        return "INCOMPLETE", ["资料不足：" + "、".join(missing)]
    if meta.get("published_at"):
        published = datetime.fromisoformat(meta["published_at"].replace("Z", "+00:00"))
        if not started - timedelta(hours=rule["lookback_hours"]) <= published <= started:
            reasons.append("发布时间不在本轮时间窗口内")
    duration, views, likes = (meta.get(k) for k in ("duration", "views", "likes"))
    if duration is not None and not 0 < duration <= rule["max_duration"]:
        reasons.append("时长为 0 或超过上限")
    if views is not None and (views < rule["min_views"] or views == 0):
        reasons.append("播放量不足或无法计算点赞率")
    if views and likes is not None and Decimal(likes) < Decimal(views) * Decimal(str(rule["min_like_ratio"])):
        reasons.append("点赞率不足")
    if presence.get("blacklisted") or presence.get("channel_blocked"):
        reasons.append("黑名单或频道排除名单受限")
    if policy_reason:
        reasons.append(policy_reason)
    return ("REJECTED", reasons) if reasons else ("QUALIFIED", ["指标合格；仅供人工核实，不代表内容或发布批准"])


def observation(meta, rule, started, presence, policy_version, policy_reason=None):
    category, reasons = classify(meta, rule, started, presence, policy_reason)
    return dict(metadata=meta, category=category, reasons=reasons, policy_version=policy_version,
                content_version=digest([meta, policy_version, category, reasons]), purpose=PURPOSE)

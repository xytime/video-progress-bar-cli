"""视频运营类型的纯分类规则，供商品与生词片尾共用；不读取运营配置。"""
from __future__ import annotations

VIDEO_GROUPS = ("english_world", "wallstreet", "ted", "ai_news", "other")
GROUP_LABELS = dict(zip(VIDEO_GROUPS, ("英语世界短视频", "华尔街事实炸弹", "TED 类", "AI 相关资讯", "其他")))


def classify_video(context: dict, channels: dict) -> tuple[str, str]:
    """内容形态优先，其次精确频道 ID，再次显式 AI 主题，最后其他。"""
    if context.get("content_type") == "ENGLISH_WORLD_SHORT":
        return "english_world", "内容类型 ENGLISH_WORLD_SHORT"
    channel = context.get("source_channel_id") or ""
    for group in ("wallstreet", "ted", "ai_news"):
        if channel.strip() and channel.strip() in channels[group]:
            return group, "来源频道精确匹配"
    if context.get("product_topic") == "AI":
        return "ai_news", "显式主题 AI"
    return "other", "未命中特定类型"

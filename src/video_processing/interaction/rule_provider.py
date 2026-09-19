"""自生长驱动的程序化兜底互动生成引擎。

不依赖外部模型网络请求，直接利用 StrategyStore 中沉淀的精选自生长模板与语义槽位，
动态组装高水准、符合平台排版规范的互动评论。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-19 | Codex | 使用合同受控渲染，避免模板字段与实际文本漂移 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现基于自生长知识库的程序化兜底生成器 |
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .contract import (
    InteractionDraft,
    InteractionType,
    render_interaction_comment,
    validate_interaction_draft,
)
from .strategy_store import StrategyStore

logger = logging.getLogger(__name__)


class RuleInteractionProvider:
    """基于自生长经验的程序化兜底提供者。"""

    def __init__(self, store: Optional[StrategyStore] = None) -> None:
        self.store = store or StrategyStore()

    def generate(
        self,
        *,
        title: str,
        description: str,
        category: str = "General",
    ) -> InteractionDraft:
        """根据视频信息自适应选择自生长模板并填充生成草稿。"""
        clean_title = re.sub(r"[#＃\[\]【】\s]+", " ", title).strip()
        core_subject = self._extract_core_subject(clean_title, description)
        chosen_type = self._infer_interaction_type(clean_title, description, category)

        # 从自生长库获取最佳匹配模板
        templates = self.store.get_templates(category=category, interaction_type=chosen_type)
        if not templates:
            templates = self.store.get_templates(category="General", interaction_type=chosen_type)
        if not templates:
            templates = self.store.get_templates(category="General")

        template = templates[0] if templates else None

        if template and template.get("interaction_type") == chosen_type.value:
            raw_topic = template.get("topic_template", "针对视频中关于{core_subject}的核心探讨，你怎么看？")
            topic = raw_topic.replace("{core_subject}", core_subject)
            poll_options = list(template.get("poll_options", ["支持并看好", "持保留意见"]))
            share_hook = template.get("share_hook", "💬 你的看法是什么？在评论区留下你的观点，转给好友一起探讨！")
            interaction_type = chosen_type
        else:
            topic = f"针对视频中关于{core_subject}的核心探讨，你怎么看？"
            poll_options = ["支持并看好", "持保留意见"]
            share_hook = "💬 你的看法是什么？在评论区留下你的观点，转给好友一起探讨！"
            interaction_type = chosen_type

        # 组装高可读性格式化评论
        formatted_comment = render_interaction_comment(
            topic=topic,
            interaction_type=interaction_type,
            poll_options=poll_options,
            share_hook=share_hook,
        )

        return validate_interaction_draft(
            topic=topic,
            interaction_type=interaction_type,
            poll_options=poll_options,
            share_hook=share_hook,
            formatted_comment=formatted_comment,
            provider="self_growing_rule",
            category=category,
        )

    def _extract_core_subject(self, title: str, description: str) -> str:
        """从标题中提取核心对象或主题。"""
        # 截取标题前缀或破折号、冒号前的核心主体
        parts = re.split(r"[:：|｜\-—_！？!?,，]", title)
        candidate = (parts[0] if parts else title).strip()
        if len(candidate) > 20:
            candidate = candidate[:20]
        return candidate or "本期话题"

    def _infer_interaction_type(self, title: str, description: str, category: str) -> InteractionType:
        """根据关键词判断最贴切的互动与转发动机。"""
        combined = f"{title} {description}".lower()

        # 避坑/预警类词汇
        if any(w in combined for w in ["风险", "危机", "崩盘", "避坑", "骗局", "误区", "千万别", "红线", "警惕", "暴跌"]):
            return InteractionType.WARNING_SHARE

        # 干货/教程/复盘类
        if any(w in combined for w in ["教程", "实操", "清单", "复盘", "干货", "步骤", "全流程", "拆解", "指南"]):
            return InteractionType.MEMO_COLLECTION

        # 深度认知/共鸣类
        if any(w in combined for w in ["真相", "残酷", "底层逻辑", "思维", "心声", "宿命", "人性", "为什么"]):
            return InteractionType.VOICE_RESONANCE

        # 行业前沿/大厂争锋
        if any(w in combined for w in ["发布", "颠覆", "突破", "全面开源", "对标", "巨头", "争端"]):
            return InteractionType.GROUP_DISCUSSION

        # 默认站队投票
        return InteractionType.POLL_STAND

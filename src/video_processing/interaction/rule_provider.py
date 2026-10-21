"""自生长驱动的程序化兜底互动生成引擎。

不依赖外部模型网络请求，直接利用 StrategyStore 中沉淀的精选自生长模板与语义槽位，
动态组装高水准、符合平台排版规范的互动评论。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-10-21 | Antigravity | 新增题材智能路由（Finance/AI/Tech/Health/General）、确定性哈希轮换与趣味度校验门禁。 |
| 1.2.0 | 2026-09-20 | Codex | 英文原标题时优先取中文简介主题，避免兜底文案截断或生硬复述。 |
| 1.1.0 | 2026-09-19 | Codex | 使用合同受控渲染，避免模板字段与实际文本漂移 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现基于自生长知识库的程序化兜底生成器 |
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from .contract import (
    InteractionDraft,
    InteractionType,
    check_bland_interaction_copy,
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
        effective_category = self._infer_category(clean_title, description, category)
        chosen_type = self._infer_interaction_type(clean_title, description, effective_category)

        # 从自生长库获取最佳匹配模板池
        templates = self.store.get_templates(category=effective_category, interaction_type=chosen_type)
        if not templates:
            templates = self.store.get_templates(category="General", interaction_type=chosen_type)
        if not templates:
            templates = self.store.get_templates(category=effective_category)
        if not templates:
            templates = self.store.get_templates(category="General")

        template = self._pick_rotated_template(templates, clean_title, description)

        if template and template.get("interaction_type") == chosen_type.value:
            raw_topic = template.get("topic_template", "五年后回看这条判断，大概率是？")
            topic = raw_topic.replace("{core_subject}", core_subject)
            poll_options = list(template.get("poll_options", ["预言太早了", "节奏刚刚好", "还是说保守了"]))
            share_hook = template.get("share_hook", "如果给五年后的自己留句话，你会写什么？")
            interaction_type = chosen_type
        else:
            topic = "五年后回看这条判断，大概率是？"
            poll_options = ["预言太早了", "节奏刚刚好", "还是说保守了"]
            share_hook = "如果给五年后的自己留句话，你会写什么？"
            interaction_type = chosen_type

        # 组装高可读性格式化评论
        formatted_comment = render_interaction_comment(
            topic=topic,
            interaction_type=interaction_type,
            poll_options=poll_options,
            share_hook=share_hook,
        )

        draft = validate_interaction_draft(
            topic=topic,
            interaction_type=interaction_type,
            poll_options=poll_options,
            share_hook=share_hook,
            formatted_comment=formatted_comment,
            provider="self_growing_rule",
            category=effective_category,
        )
        check_bland_interaction_copy(
            topic=draft.topic,
            poll_options=draft.poll_options,
            share_hook=draft.share_hook,
        )
        return draft

    @staticmethod
    def _pick_rotated_template(templates: list[dict], title: str, description: str) -> Optional[dict]:
        """按视频标题与简介做确定性哈希轮换，避免不同视频永远命中第 0 号模板。"""
        if not templates:
            return None
        if len(templates) == 1:
            return templates[0]
        digest = hashlib.sha256(f"{title}::{description[:200]}".encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % len(templates)
        return templates[idx]

    @staticmethod
    def _has_en_word(text: str, words: tuple[str, ...]) -> bool:
        pattern = r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b"
        return bool(re.search(pattern, text))

    @classmethod
    def _infer_category(cls, title: str, description: str, raw_category: str) -> str:
        """根据传入分类或标题/简介关键词，映射到策略库四大黄金赛道。"""
        combined = f"{title} {description} {raw_category}".lower()
        norm_cat = (raw_category or "").strip()

        if (
            norm_cat in {"Finance", "财经"}
            or any(
                w in combined
                for w in (
                    "美联储", "华尔街", "美债", "利率", "降息", "加息", "通胀", "汇率", "美元",
                    "黄金", "债市", "股市", "银行", "信贷", "抛售", "量化", "泡沫", "主权债",
                    "养老金", "财报", "破产", "危机", "崩盘", "避险", "资产", "周期", "商业",
                )
            )
            or cls._has_en_word(
                combined,
                (
                    "fed", "wall street", "bank", "banks", "credit", "debt", "rate", "rates",
                    "inflation", "market", "selloff", "tax", "tariff", "earnings", "forecast",
                    "business", "lender", "billion", "billions", "economy", "economic",
                ),
            )
        ):
            return "Finance"

        if (
            norm_cat in {"Health", "健康科学"}
            or any(
                w in combined
                for w in (
                    "健康", "长寿", "抗衰", "大脑", "睡眠", "熬夜", "心血管", "癌症", "基因",
                    "细胞", "成瘾", "多巴胺", "代谢", "饮食", "运动", "医疗", "寿命", "老年",
                    "阿尔茨海默", "养生", "焦虑", "孤独", "亲密关系", "痛苦", "情绪", "心理",
                )
            )
            or cls._has_en_word(
                combined,
                (
                    "brain", "health", "longevity", "sleep", "cancer", "addiction", "ozempic",
                    "loneliness", "intimacy", "mental", "therapy", "aging", "body",
                ),
            )
        ):
            return "Health"

        if (
            norm_cat in {"AI/Tech", "Tech", "Science & Technology", "科技"}
            or any(
                w in combined
                for w in (
                    "人工智能", "大模型", "算力", "芯片", "半导体", "英伟达", "机器人",
                    "算法", "开源", "智能体", "自动驾驶", "科技", "技术", "软件", "硬件", "网络",
                )
            )
            or cls._has_en_word(
                combined,
                (
                    "ai", "agent", "agents", "llm", "gpu", "nvidia", "tech", "technology",
                    "robot", "robotics", "quantum", "starlink", "satellite", "satellites",
                    "hack", "cyber", "software", "chip", "chips",
                ),
            )
        ):
            return "AI/Tech"

        return "General"

    def _extract_core_subject(self, title: str, description: str) -> str:
        """从标题中提取核心对象或主题。"""
        # 优先使用中文标题；英文原题容易在定长截断后变成无意义片段。
        parts = re.split(r"[:：|｜\-—_！？!?,，]", title)
        candidate = (parts[0] if parts else title).strip()
        if not re.search(r"[\u4e00-\u9fff]", candidate):
            description_lead = re.split(r"[。！？!?#\n]", description, maxsplit=1)[0]
            candidate = re.sub(r"\s+", " ", description_lead).strip()
        if len(candidate) > 28:
            candidate = candidate[:28].rstrip("，、：:；; ")
        return candidate or "本期话题"

    @classmethod
    def _infer_interaction_type(cls, title: str, description: str, category: str) -> InteractionType:
        """根据关键词判断最贴切的互动与转发动机。"""
        combined = f"{title} {description}".lower()

        # 避坑/预警类词汇
        if (
            any(w in combined for w in ("风险", "危机", "崩盘", "避坑", "骗局", "误区", "千万别", "红线", "警惕", "暴跌", "陷阱", "坏账", "中断", "故障"))
            or cls._has_en_word(combined, ("warning", "trap", "crisis", "loss", "losses", "hack", "selloff", "ambush", "crash", "risk", "lost"))
        ):
            return InteractionType.WARNING_SHARE

        # 干货/教程/复盘类
        if (
            any(w in combined for w in ("教程", "实操", "清单", "复盘", "干货", "步骤", "全流程", "拆解", "指南", "要点", "财报"))
            or cls._has_en_word(combined, ("takeaways", "takeaway", "guide", "how to", "regulate", "report", "forecast", "lessons"))
        ):
            return InteractionType.MEMO_COLLECTION

        # 深度认知/共鸣类
        if (
            any(w in combined for w in ("真相", "残酷", "底层逻辑", "思维", "心声", "宿命", "人性", "为什么", "孤独", "意义"))
            or cls._has_en_word(combined, ("loneliness", "intimacy", "purpose", "pain", "why", "truth", "power", "success"))
        ):
            return InteractionType.VOICE_RESONANCE

        # 行业前沿/大厂争锋
        if (
            any(w in combined for w in ("发布", "颠覆", "突破", "全面开源", "对标", "巨头", "争端", "超越"))
            or cls._has_en_word(combined, ("breakthrough", "launch", "open source", "vs", "future", "architect"))
        ):
            return InteractionType.GROUP_DISCUSSION

        # 默认站队投票
        return InteractionType.POLL_STAND

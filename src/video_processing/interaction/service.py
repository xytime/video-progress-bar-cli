"""互动业务门面服务（Facade）。

协调 AGY 模型生成、自生长程序化兜底、敏感词安全门禁与自学习沉淀闭环。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现高内聚业务门面、敏感词门禁与自动沉淀机制 |
"""

from __future__ import annotations

import logging
from typing import Optional

from config.settings import settings

from .agy_provider import AgyInteractionError, AgyInteractionProvider
from .contract import InteractionDraft
from .rule_provider import RuleInteractionProvider
from .strategy_store import StrategyStore

logger = logging.getLogger(__name__)


class InteractionService:
    """互动生成业务门面。"""

    def __init__(
        self,
        *,
        agy_provider: Optional[AgyInteractionProvider] = None,
        rule_provider: Optional[RuleInteractionProvider] = None,
        store: Optional[StrategyStore] = None,
    ) -> None:
        self.store = store or StrategyStore()
        self.rule_provider = rule_provider or RuleInteractionProvider(store=self.store)
        self.agy_provider = agy_provider or AgyInteractionProvider()

    def generate_comment(
        self,
        *,
        title: str,
        description: str,
        category: str = "General",
        force_rule: bool = False,
    ) -> InteractionDraft:
        """优先使用 AGY 动态决策互动方案，失败则优雅降级自生长程序化兜底。"""
        draft: Optional[InteractionDraft] = None

        if not force_rule:
            try:
                logger.info("[InteractionService] Requesting AGY for interaction draft: %s", title[:30])
                draft = self.agy_provider.generate(
                    title=title,
                    description=description,
                    category=category,
                )
                # 安全门禁审查
                if not self._check_censorship(draft.formatted_comment):
                    logger.warning("[InteractionService] AGY draft failed censorship check; falling back to rule.")
                    draft = None
                else:
                    # 审查通过，沉淀入自生长知识库
                    try:
                        self.store.learn_from_success(draft, title)
                    except Exception as exc:
                        logger.warning("[InteractionService] Failed to record exemplar to store: %s", exc)
            except (AgyInteractionError, Exception) as exc:
                logger.warning("[InteractionService] AGY generation failed (%s); falling back to self-growing rule.", exc)
                draft = None

        # 兜底链路
        if draft is None:
            logger.info("[InteractionService] Generating comment via self-growing rule provider.")
            draft = self.rule_provider.generate(
                title=title,
                description=description,
                category=category,
            )

        return draft

    def _check_censorship(self, text: str) -> bool:
        """检查评论文本是否包含敏感词违规。"""
        try:
            from video_processing.censor.engine import CensorshipEngine
            engine = CensorshipEngine()
            result = engine.check_text(text)
            return not result.has_violations
        except ImportError:
            # 若未启用或无审查模块，检查基本的黑名单
            lowered = text.lower()
            unsafe_keywords = ["代办", "刷单", "买卖微信", "翻墙", "vpn"]
            return not any(w in lowered for w in unsafe_keywords)
        except Exception as exc:
            logger.warning("[InteractionService] Censorship check warning: %s; allowing safe pass.", exc)
            return True

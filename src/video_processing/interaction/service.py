"""互动业务门面服务（Facade）。

协调 AGY 模型生成、自生长程序化兜底、敏感词安全门禁与自学习沉淀闭环。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-09-19 | Codex | 公开提交前复审门禁，持久化文案重试同样遵循当前审查策略 |
| 1.1.0 | 2026-09-19 | Antigravity | 修复审查门禁：接入真实 censor_engine，实现双通道 Fail-Closed 一票否决并移除生成期写盘副作用 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现高内聚业务门面、敏感词门禁与自动沉淀机制 |
"""

from __future__ import annotations

import logging
from typing import Optional

from config.settings import settings

from .agy_provider import AgyInteractionError, AgyInteractionProvider
from .contract import CensorshipViolationError, InteractionDraft
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
        """优先使用 AGY 动态决策互动方案，失败则优雅降级自生长程序化兜底。

        全链路受 Fail-Closed 内容审查门禁保护：任何生成结果（包含兜底）若命中违规词，
        一票否决且绝不放行。
        """
        draft: Optional[InteractionDraft] = None

        if not force_rule:
            try:
                logger.info("[InteractionService] Requesting AGY for interaction draft: %s", title[:30])
                agy_draft = self.agy_provider.generate(
                    title=title,
                    description=description,
                    category=category,
                )
                # 安全门禁审查
                if not self._check_censorship(agy_draft.formatted_comment):
                    logger.warning("[InteractionService] AGY 生成内容未能通过安全审查，降级至兜底规则。")
                else:
                    draft = agy_draft
            except (AgyInteractionError, Exception) as exc:
                logger.warning("[InteractionService] AGY generation failed (%s); falling back to self-growing rule.", exc)
                draft = None

        # 兜底链路
        if draft is None:
            logger.info("[InteractionService] Generating comment via self-growing rule provider.")
            rule_draft = self.rule_provider.generate(
                title=title,
                description=description,
                category=category,
            )
            # 兜底生成必须同样接受严格审查（防输入标题自身包含违禁词）
            if not self._check_censorship(rule_draft.formatted_comment):
                logger.error("[InteractionService] 兜底互动内容同样命中安全审查拦截，Fail-Closed 一票否决！")
                raise CensorshipViolationError(
                    f"互动评论内容未能通过安全审查 (标题: {title[:20]}...)"
                )
            draft = rule_draft

        return draft

    def validate_comment_for_submission(self, text: str) -> None:
        """提交前复审实际正文；已保存的草稿不能绕过更新后的内容策略。"""
        if not self._check_censorship(text):
            raise CensorshipViolationError("实际提交评论未通过当前安全审查，禁止发表")

    def _check_censorship(self, text: str) -> bool:
        """检查评论文本是否符合内容安全红线与频道策略。

        Fail-Closed 保证：任何违禁命中、模块加载失败或运行时异常均一票否决（返回 False）。
        """
        if not text or not text.strip():
            return False

        try:
            from video_processing.censor_engine import check_channel_policy, check_text

            # 1. 检查违法违规 P0/P1/P2 词库
            res_text = check_text(zh_text=text)
            if res_text.hit:
                logger.warning(
                    "[InteractionService] 内容安全拦截: 命中 %s (词汇: '%s')",
                    res_text.tag,
                    res_text.matched,
                )
                return False

            # 2. 检查频道内容策略层 (Channel Policy)
            res_cp = check_channel_policy(zh_text=text)
            if res_cp.hit:
                logger.warning(
                    "[InteractionService] 频道策略拦截: 命中 %s (词汇: '%s')",
                    res_cp.tag,
                    res_cp.matched,
                )
                return False

            return True

        except Exception as exc:
            # 审查引擎发生任何未知错误，绝对不允许 fail-open
            logger.error("[InteractionService] 审查引擎执行异常 (%s)，Fail-Closed 拒绝放行。", exc)
            return False

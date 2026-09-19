"""AGY 互动评论模型提供者适配层。

利用受限的 agy CLI 结构化输出能力，调用最新高阶思考模型，
输出完全符合数据合同的互动方案。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：封装 AGY 结构化交互生成与受限重试 |
| 1.1.0 | 2026-09-19 | Codex | 拒绝字段强制转换及额外字段，宿主确定性生成实际待审评论 |
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from config.settings import settings
from video_processing.utils.agy_provider import AgyProviderError, run_agy_structured

from .contract import (InteractionContractError, InteractionDraft, InteractionType,
                       render_interaction_comment, validate_interaction_draft)
from .prompt import INTERACTION_JSON_SCHEMA, build_interaction_prompt

logger = logging.getLogger(__name__)


class AgyInteractionError(RuntimeError):
    """AGY 互动模型调用失败或返回不合规。"""


class AgyInteractionProvider:
    """AGY 互动模型提供者。"""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        command: Optional[str] = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.model = model or getattr(settings, "copywriter_agy_model", "gemini-3.8-flash-high")
        self.command = command or getattr(settings, "copywriter_agy_bin", "agy")
        self.timeout_seconds = timeout_seconds

    def generate(
        self,
        *,
        title: str,
        description: str,
        category: str = "General",
    ) -> InteractionDraft:
        """调用 AGY 生成结构化互动草稿，并提供一次受限重试。"""
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                prompt_text = build_interaction_prompt(
                    title=title,
                    description=description,
                    category=category,
                    retrying=attempt > 0,
                )
                payload = run_agy_structured(
                    prompt_text,
                    schema=INTERACTION_JSON_SCHEMA,
                    model=self.model,
                    command=self.command,
                    timeout_sec=self.timeout_seconds,
                )
                if not isinstance(payload, dict) or set(payload) != {"topic", "interaction_type", "poll_options", "share_hook"}:
                    raise InteractionContractError("AGY 输出字段与合同不符")
                kind = InteractionType(payload["interaction_type"])
                rendered = render_interaction_comment(
                    topic=payload["topic"], interaction_type=kind,
                    poll_options=payload["poll_options"], share_hook=payload["share_hook"],
                )
                return validate_interaction_draft(
                    topic=payload["topic"],
                    interaction_type=kind,
                    poll_options=payload["poll_options"],
                    share_hook=payload["share_hook"],
                    formatted_comment=rendered,
                    provider=f"agy:{self.model}",
                    category=category,
                )
            except (AgyProviderError, KeyError, TypeError, ValueError, InteractionContractError) as exc:
                last_error = exc
                logger.warning(
                    "[AgyInteractionProvider] Attempt %d failed: %s", attempt + 1, type(exc).__name__
                )
                if attempt == 0:
                    time.sleep(2)

        raise AgyInteractionError(f"AGY 互动生成失败: {type(last_error).__name__}") from last_error

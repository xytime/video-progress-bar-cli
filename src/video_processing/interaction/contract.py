"""互动评论数据合同与严格校验模型。

定义所有进出互动引擎的强类型数据模型，确保与外部模型、存储及浏览器执行层解耦。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：定义 InteractionType, InteractionDraft, InteractionResult 及合同校验 |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class InteractionType(str, Enum):
    """互动引导类型枚举。"""
    POLL_STAND = "POLL_STAND"                   # 站队投票
    WARNING_SHARE = "WARNING_SHARE"             # 利他避坑转发
    GROUP_DISCUSSION = "GROUP_DISCUSSION"       # 群聊研讨转发
    MEMO_COLLECTION = "MEMO_COLLECTION"         # 备忘收藏转发
    VOICE_RESONANCE = "VOICE_RESONANCE"         # 观点嘴替共鸣


class InteractionContractError(ValueError):
    """互动评论内容不满足质量或平台格式合同。"""


@dataclass(frozen=True)
class InteractionDraft:
    """互动评论待发表草稿。"""
    topic: str
    interaction_type: InteractionType
    poll_options: List[str]
    share_hook: str
    formatted_comment: str
    provider: str
    category: str = "General"


@dataclass(frozen=True)
class InteractionResult:
    """发评执行结果。"""
    platform_post_id: str
    status: str                                 # COMMENTED, SKIPPED_EXISTS, PENDING_REVIEW, FAILED
    draft: Optional[InteractionDraft] = None
    evidence_path: Optional[str] = None
    error_message: Optional[str] = None
    commented_at: Optional[str] = None


def validate_interaction_draft(
    *,
    topic: str,
    interaction_type: str | InteractionType,
    poll_options: List[str],
    share_hook: str,
    formatted_comment: str,
    provider: str,
    category: str = "General",
) -> InteractionDraft:
    """严格校验互动草稿字段，不符合平台规范或体验合同则抛出 InteractionContractError。"""
    topic = (topic or "").strip()
    if not topic:
        raise InteractionContractError("互动话题 (topic) 不能为空")
    if len(topic) > 100:
        raise InteractionContractError(f"互动话题过长 ({len(topic)} > 100 字)")

    try:
        norm_type = InteractionType(interaction_type)
    except ValueError:
        raise InteractionContractError(f"不支持的互动类型代码: {interaction_type}")

    if not isinstance(poll_options, list):
        raise InteractionContractError("投票选项 (poll_options) 必须是列表")
    
    # 选项校验（如果有选项，通常 2-4 项）
    clean_options = [str(opt).strip() for opt in poll_options if str(opt).strip()]
    if norm_type == InteractionType.POLL_STAND and len(clean_options) < 2:
        raise InteractionContractError("投票型互动必须提供至少 2 个有效选项")

    share_hook = (share_hook or "").strip()
    if not share_hook:
        raise InteractionContractError("转发引导语 (share_hook) 不能为空")

    formatted_comment = (formatted_comment or "").strip()
    if not formatted_comment:
        raise InteractionContractError("最终排版文本 (formatted_comment) 不能为空")

    # 微信评论字数限制合同（建议 50-300 字，太短无价值，太长移动端不友好）
    if len(formatted_comment) < 30:
        raise InteractionContractError(f"排版评论过短 ({len(formatted_comment)} < 30 字)")
    if len(formatted_comment) > 350:
        raise InteractionContractError(f"排版评论过长 ({len(formatted_comment)} > 350 字)")

    return InteractionDraft(
        topic=topic,
        interaction_type=norm_type,
        poll_options=clean_options,
        share_hook=share_hook,
        formatted_comment=formatted_comment,
        provider=provider.strip(),
        category=category.strip() or "General",
    )

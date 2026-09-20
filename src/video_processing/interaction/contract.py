"""互动评论数据合同与严格校验模型。

定义所有进出互动引擎的强类型数据模型，确保与外部模型、存储及浏览器执行层解耦。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.4.0 | 2026-09-20 | Antigravity | 放宽 share_hook 上限至 30 字，支持启发式开放反问句，优化评论区真实互动。 |
| 1.3.0 | 2026-09-20 | Codex | 将短评论长度上限收口到宿主合同，模型超长输出自动降级为规则草稿。 |
| 1.2.0 | 2026-09-20 | Codex | 评论采用问题、选项与单句收束的短格式，移除重复栏目标题和多重号召。 |
| 1.1.0 | 2026-09-19 | Codex | 收紧字段边界，并由受控渲染器绑定结构化字段与最终文本 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：定义 InteractionType, InteractionDraft, InteractionResult 及合同校验 |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence


class InteractionType(str, Enum):
    """互动引导类型枚举。"""
    POLL_STAND = "POLL_STAND"                   # 站队投票
    WARNING_SHARE = "WARNING_SHARE"             # 利他避坑转发
    GROUP_DISCUSSION = "GROUP_DISCUSSION"       # 群聊研讨转发
    MEMO_COLLECTION = "MEMO_COLLECTION"         # 备忘收藏转发
    VOICE_RESONANCE = "VOICE_RESONANCE"         # 观点嘴替共鸣


class InteractionContractError(ValueError):
    """互动评论内容不满足质量或平台格式合同。"""


class CensorshipViolationError(InteractionContractError):
    """互动评论内容命中安全审查敏感违规词，一票否决。"""


MAX_TOPIC_LENGTH = 24
MAX_SHARE_HOOK_LENGTH = 30
MAX_OPTION_LENGTH = 14
MIN_OPTIONS = 2
MAX_OPTIONS = 3
MAX_FORMATTED_COMMENT_LENGTH = 140


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
    if not isinstance(topic, str):
        raise InteractionContractError("互动话题 (topic) 必须是字符串")
    topic = topic.strip()
    if not topic:
        raise InteractionContractError("互动话题 (topic) 不能为空")
    if len(topic) > MAX_TOPIC_LENGTH:
        raise InteractionContractError(f"互动话题过长 ({len(topic)} > {MAX_TOPIC_LENGTH} 字)")

    try:
        norm_type = InteractionType(interaction_type)
    except (TypeError, ValueError):
        raise InteractionContractError(f"不支持的互动类型代码: {interaction_type}")

    if not isinstance(poll_options, list):
        raise InteractionContractError("投票选项 (poll_options) 必须是列表")
    if not MIN_OPTIONS <= len(poll_options) <= MAX_OPTIONS:
        raise InteractionContractError(f"投票选项必须为 {MIN_OPTIONS}-{MAX_OPTIONS} 项")
    if not all(isinstance(option, str) for option in poll_options):
        raise InteractionContractError("投票选项必须全部是字符串")
    clean_options = [option.strip() for option in poll_options]
    if not all(clean_options):
        raise InteractionContractError("投票选项不能包含空字符串")
    if any(len(option) > MAX_OPTION_LENGTH for option in clean_options):
        raise InteractionContractError(f"投票选项不能超过 {MAX_OPTION_LENGTH} 字")

    if not isinstance(share_hook, str):
        raise InteractionContractError("转发引导语 (share_hook) 必须是字符串")
    share_hook = share_hook.strip()
    if not share_hook:
        raise InteractionContractError("转发引导语 (share_hook) 不能为空")
    if len(share_hook) > MAX_SHARE_HOOK_LENGTH:
        raise InteractionContractError(f"转发引导语过长 ({len(share_hook)} > {MAX_SHARE_HOOK_LENGTH} 字)")

    if not isinstance(formatted_comment, str):
        raise InteractionContractError("最终排版文本 (formatted_comment) 必须是字符串")
    formatted_comment = formatted_comment.strip()
    if not formatted_comment:
        raise InteractionContractError("最终排版文本 (formatted_comment) 不能为空")

    # 手机端首评合同：太短缺乏语境，太长会遮蔽原视频讨论。
    if len(formatted_comment) < 30:
        raise InteractionContractError(f"排版评论过短 ({len(formatted_comment)} < 30 字)")
    if len(formatted_comment) > MAX_FORMATTED_COMMENT_LENGTH:
        raise InteractionContractError(f"排版评论过长 ({len(formatted_comment)} > {MAX_FORMATTED_COMMENT_LENGTH} 字)")
    expected_comment = render_interaction_comment(
        topic=topic,
        interaction_type=norm_type,
        poll_options=clean_options,
        share_hook=share_hook,
    )
    if formatted_comment != expected_comment:
        raise InteractionContractError("最终排版文本必须与已校验字段的受控渲染结果一致")

    if not isinstance(provider, str) or not provider.strip():
        raise InteractionContractError("提供者 (provider) 不能为空")
    if not isinstance(category, str):
        raise InteractionContractError("类目 (category) 必须是字符串")

    return InteractionDraft(
        topic=topic,
        interaction_type=norm_type,
        poll_options=clean_options,
        share_hook=share_hook,
        formatted_comment=formatted_comment,
        provider=provider.strip(),
        category=category.strip() or "General",
    )


def render_interaction_comment(
    *,
    topic: str,
    interaction_type: InteractionType,
    poll_options: Sequence[str],
    share_hook: str,
) -> str:
    """把已验证字段渲染为唯一的评论文本，避免结构与实际发表文本漂移。"""
    if not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > MAX_TOPIC_LENGTH:
        raise InteractionContractError("互动话题必须是受限的非空字符串")
    if not isinstance(interaction_type, InteractionType):
        raise InteractionContractError("互动类型必须是 InteractionType")
    if not isinstance(poll_options, (list, tuple)) or not MIN_OPTIONS <= len(poll_options) <= MAX_OPTIONS:
        raise InteractionContractError(f"投票选项必须为 {MIN_OPTIONS}-{MAX_OPTIONS} 项列表")
    if not all(isinstance(option, str) and option.strip() and len(option.strip()) <= MAX_OPTION_LENGTH for option in poll_options):
        raise InteractionContractError("投票选项必须是受限的非空字符串")
    if not isinstance(share_hook, str) or not share_hook.strip() or len(share_hook.strip()) > MAX_SHARE_HOOK_LENGTH:
        raise InteractionContractError("转发引导语必须是受限的非空字符串")

    letters = ("A", "B", "C", "D")
    lines = [topic.strip()]
    lines.extend(f"{letters[index]} {option.strip()}" for index, option in enumerate(poll_options))
    lines.append(share_hook.strip())
    return "\n".join(lines)

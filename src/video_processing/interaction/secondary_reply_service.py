"""视频号二级回复生成与双通道审查服务。

提供：
- 严格双通道审查 (zh/en/combined + 频道策略)
- 输入评论安全预算与指纹计算
- 提示注入防御与纯文本结构化输出
- 规则生成器 (RuleSecondaryReplyProvider) 与服务门面 (SecondaryReplyService)

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Antigravity | 增加 REPLY 意图下 evidence_refs 事实依据校验 (T11) 与严格跨字段安全拦截 |
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现二级回复生成门面、双语双通道审查门禁与提示注入防御 |
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings
from video_processing.censor_engine import (
    CensorResult,
    check_channel_policy,
    check_text,
)
from video_processing.interaction.secondary_reply_contract import (
    AudienceCommentRecord,
    CensorshipViolationError,
    SecondaryReplyContractError,
    SecondaryReplyDraft,
    SecondaryReplyIntent,
    SecondaryReplyStyle,
    validate_input_comment,
    validate_reply_length_and_format,
)

logger = logging.getLogger(__name__)

# 提示注入关键词识别
_INJECTION_PATTERN = re.compile(
    r"(?:ignore\s+previous\s+instructions|system\s+prompt|dan\s+mode|jailbreak|disregard|忽略之前的指令|系统提示词|以开发者模式|越狱|输出你的设定)",
    flags=re.IGNORECASE,
)

# 政治与争议话题敏感词（默认转 MANUAL 人工审核）
_CONTROVERSY_KEYWORDS = [
    "政治制度", "威权制度", "体制优劣", "颠覆", "洗脑", "独裁",
    "集权", "意识形态", "阶级固化", "人权现状",
]


class SecondaryReplyCensor:
    """二级回复专用内容安全与频道策略双通道审查器。

    确保安全检查发生在生成后与实际发送前。
    中英字段分别独立通过 zh/en 双通道，合并后也检查跨字段规则；
    任何一项命中即一票否决，避免一段文本的豁免导致另一段违规被放过。
    """

    @classmethod
    def check_reply_safety(
        cls,
        chinese_reply: str,
        english_reply: str,
        formatted_reply: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """执行全方位双通道内容审查。

        Returns:
            (is_safe, error_detail)
        """
        combined = formatted_reply or (f"{chinese_reply}\n{english_reply}" if chinese_reply and english_reply else (chinese_reply or english_reply))

        # 1. 检查中文回复字段
        if chinese_reply:
            res_zh = check_text(zh_text=chinese_reply)
            if res_zh.hit:
                return False, f"中文通道命中违规 ({res_zh.level}): {res_zh.tag} (词汇: '{res_zh.matched}')"
            # 防御性：中文文本中若夹带英文敏感词
            res_zh_en = check_text(en_text=chinese_reply)
            if res_zh_en.hit:
                return False, f"中文文本英文通道命中违规 ({res_zh_en.level}): {res_zh_en.tag} (词汇: '{res_zh_en.matched}')"
            res_cp_zh = check_channel_policy(zh_text=chinese_reply)
            if res_cp_zh.hit:
                return False, f"中文通道命中频道策略: {res_cp_zh.tag} (词汇: '{res_cp_zh.matched}')"

        # 2. 检查英文回复字段
        if english_reply:
            res_en = check_text(en_text=english_reply)
            if res_en.hit:
                return False, f"英文通道命中违规 ({res_en.level}): {res_en.tag} (词汇: '{res_en.matched}')"
            # 防御性：英文文本中若夹带拼音或中文敏感词
            res_en_zh = check_text(zh_text=english_reply)
            if res_en_zh.hit:
                return False, f"英文文本中文通道命中违规 ({res_en_zh.level}): {res_en_zh.tag} (词汇: '{res_en_zh.matched}')"
            res_cp_en = check_channel_policy(en_text=english_reply)
            if res_cp_en.hit:
                return False, f"英文通道命中频道策略: {res_cp_en.tag} (词汇: '{res_cp_en.matched}')"

        # 3. 检查合并后的整段文本（双语通道协同检测）
        res_comb = check_text(zh_text=chinese_reply, en_text=english_reply)
        if res_comb.hit:
            return False, f"合并文本命中违规 ({res_comb.level}): {res_comb.tag} (词汇: '{res_comb.matched}')"
        res_comb_cp = check_channel_policy(zh_text=chinese_reply, en_text=english_reply)
        if res_comb_cp.hit:
            return False, f"合并文本命中频道策略: {res_comb_cp.tag} (词汇: '{res_comb_cp.matched}')"

        return True, None


def _cjk_bigrams(text: str) -> set:
    cleaned = re.sub(r"[\s\W\d_]+", "", text or "")
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def best_relevant_evidence_ref(comment_text: str, video_context: Optional[Dict[str, Any]]) -> Optional[str]:
    """从已提供材料中选出与评论有字面重叠的片段；没有任何重叠则认为材料与评论无关，返回 None。

    这只是确定性的最低门槛（防止给无关材料硬挂来源），不证明语义上的事实依据。
    """
    evidence = (video_context or {}).get("evidence")
    if not isinstance(evidence, dict):
        return None
    cbg = _cjk_bigrams(comment_text)
    best_ref, best_score = None, 0
    for ref in allowed_evidence_refs(video_context):
        score = len(cbg & _cjk_bigrams(evidence[ref]))
        if score > best_score:
            best_ref, best_score = ref, score
    return best_ref


def allowed_evidence_refs(video_context: Optional[Dict[str, Any]]) -> List[str]:
    """从上游提供的材料白名单取可引用的证据 ID（video_context['evidence'] 为 {ref_id: 片段文本}）。"""
    evidence = (video_context or {}).get("evidence")
    if not isinstance(evidence, dict):
        return []
    return [k for k, v in evidence.items() if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()]


class RuleSecondaryReplyProvider:
    """基于确定性规则与受控语料的二级回复生成器。

    仅为 fixture/离线演示提供者（FIXTURE_ONLY）：固定套话不是正式生成能力，
    编排层默认拒绝发送此类草稿，真实 provider 保持 unavailable，直至另行验证。
    """

    FIXTURE_ONLY = True

    def generate(
        self,
        comment: AudienceCommentRecord,
        video_context: Optional[Dict[str, Any]] = None,
        preferred_style: Optional[SecondaryReplyStyle] = None,
    ) -> SecondaryReplyDraft:
        content = comment.content.strip()

        # 1. 检查输入评论长度预算（不静默截断）
        _, is_truncated, _ = validate_input_comment(content)
        if is_truncated:
            return SecondaryReplyDraft(
                platform_post_id=comment.platform_post_id,
                comment_id=comment.comment_id,
                intent=SecondaryReplyIntent.MANUAL,
                style=preferred_style or SecondaryReplyStyle.PRAGMATIC,
                chinese_reply="",
                english_reply="",
                formatted_reply="",
                reason_code="INPUT_EXCEEDS_BUDGET",
                evidence_refs=[],
                provider="rule_secondary_provider",
            )

        # 2. 检查提示注入企图
        if _INJECTION_PATTERN.search(content):
            logger.warning("[RuleSecondaryReplyProvider] 检测到疑似提示注入: %s", content[:50])
            return SecondaryReplyDraft(
                platform_post_id=comment.platform_post_id,
                comment_id=comment.comment_id,
                intent=SecondaryReplyIntent.MANUAL,
                style=preferred_style or SecondaryReplyStyle.PRAGMATIC,
                chinese_reply="",
                english_reply="",
                formatted_reply="",
                reason_code="PROMPT_INJECTION_DETECTED",
                evidence_refs=[],
                provider="rule_secondary_provider",
            )

        # 3. 检查争议/体制政治敏感内容 -> 默认 MANUAL 人工接管
        if any(kw in content for kw in _CONTROVERSY_KEYWORDS):
            return SecondaryReplyDraft(
                platform_post_id=comment.platform_post_id,
                comment_id=comment.comment_id,
                intent=SecondaryReplyIntent.MANUAL,
                style=preferred_style or SecondaryReplyStyle.PHILOSOPHICAL,
                chinese_reply="",
                english_reply="",
                formatted_reply="",
                reason_code="POLITICAL_CONTROVERSY_MANUAL_REVIEW",
                evidence_refs=[],
                provider="rule_secondary_provider",
            )

        # 4. 检查纯表情 / 无意义灌水 / 极短问候 -> SKIP
        cleaned = re.sub(r"[\s\d\W]+", "", content)
        spam_tokens = ["打卡", "好看", "支持", "好", "赞", "up", "dd", "1", "666", "沙发", "第一"]
        is_repetitive_spam = False
        if cleaned:
            temp = cleaned.lower()
            for tok in spam_tokens:
                temp = temp.replace(tok, "")
            if not temp:
                is_repetitive_spam = True

        if len(cleaned) < 2 or is_repetitive_spam:
            return SecondaryReplyDraft(
                platform_post_id=comment.platform_post_id,
                comment_id=comment.comment_id,
                intent=SecondaryReplyIntent.SKIP,
                style=preferred_style or SecondaryReplyStyle.PRAGMATIC,
                chinese_reply="",
                english_reply="",
                formatted_reply="",
                reason_code="NO_SUBSTANTIVE_CONTENT",
                evidence_refs=[],
                provider="rule_secondary_provider",
            )

        # 5. 事实纠错或勘误询问 -> MANUAL 保留人工裁决
        if any(err_kw in content for err_kw in ["勘误", "说错了", "数据不对", "字幕翻译错", "有硬伤"]):
            return SecondaryReplyDraft(
                platform_post_id=comment.platform_post_id,
                comment_id=comment.comment_id,
                intent=SecondaryReplyIntent.MANUAL,
                style=preferred_style or SecondaryReplyStyle.PRAGMATIC,
                chinese_reply="",
                english_reply="",
                formatted_reply="",
                reason_code="FACTUAL_CORRECTION_MANUAL_REVIEW",
                evidence_refs=[],
                provider="rule_secondary_provider",
            )

        # 6a. 没有经审核的材料就不能声称“有依据”：转人工，绝不凭空编造 evidence_refs
        allowed_refs = allowed_evidence_refs(video_context)
        relevant_ref = best_relevant_evidence_ref(content, video_context)
        if not allowed_refs or relevant_ref is None:
            return SecondaryReplyDraft(
                platform_post_id=comment.platform_post_id,
                comment_id=comment.comment_id,
                intent=SecondaryReplyIntent.MANUAL,
                style=preferred_style or SecondaryReplyStyle.PRAGMATIC,
                chinese_reply="",
                english_reply="",
                formatted_reply="",
                reason_code="NO_REVIEWED_VIDEO_MATERIAL" if not allowed_refs else "EVIDENCE_NOT_RELEVANT",
                evidence_refs=[],
                provider="rule_secondary_provider",
            )

        # 6. 有实质价值的提问或观点分享 -> 生成高质回复
        style = preferred_style or SecondaryReplyStyle.MACRO
        video_title = (video_context or {}).get("title") or "深度分析"

        # 根据意图与风格构建符合方案 A 长度与格式标准的回复
        if "为什么" in content or "怎么看" in content or "?" in content or "？" in content:
            style = SecondaryReplyStyle.MACRO
            zh = "这涉及核心底层逻辑与外部变量的博弈，更详细的数据可参考正文推演。"
            en = "This reflects core structural trade-offs amid external shifts."
            reason = "ANSWER_ANALYTICAL_QUERY"
            evidence = [relevant_ref]  # 仅引用与评论有字面关联、调用方提供且已审核的材料
        elif "对比" in content or "相比" in content:
            style = SecondaryReplyStyle.PHILOSOPHICAL
            zh = "两种路径各有约束与代价，本质是不同发展阶段下的选择取舍。"
            en = "Divergent paths reflect distinct constraints and trade-offs."
            reason = "COMPARATIVE_ANALYSIS"
            evidence = [relevant_ref]  # 仅引用与评论有字面关联、调用方提供且已审核的材料
        elif "哈哈" in content or "乐" in content or "有意思" in content:
            style = SecondaryReplyStyle.HUMOROUS
            zh = "观察入微，现实运行中的反差往往比设计好的剧本更具戏剧性。"
            en = "Keen observation; systemic irony often eclipses fiction."
            reason = "HUMOROUS_RESONANCE"
            evidence = [relevant_ref]  # 仅引用与评论有字面关联、调用方提供且已审核的材料
        else:
            style = SecondaryReplyStyle.PRAGMATIC
            zh = "感谢深度探讨，这一视角对理解后续行业周期演进很有价值。"
            en = "Appreciate the thoughtful insight on industry evolution."
            reason = "CONSTRUCTIVE_FEEDBACK"
            evidence = [relevant_ref]  # 仅引用与评论有字面关联、调用方提供且已审核的材料

        zh_nfc, en_nfc, formatted = validate_reply_length_and_format(zh, en)

        return SecondaryReplyDraft(
            platform_post_id=comment.platform_post_id,
            comment_id=comment.comment_id,
            intent=SecondaryReplyIntent.REPLY,
            style=style,
            chinese_reply=zh_nfc,
            english_reply=en_nfc,
            formatted_reply=formatted,
            reason_code=reason,
            evidence_refs=evidence,
            provider="rule_secondary_provider",
        )


class SecondaryReplyService:
    """二级回复业务门面。

    整合：
    - 观众评论安全规范化
    - 生成服务提供方
    - 双重审查门禁（生成后与提交前）
    """

    def __init__(
        self,
        provider: Optional[RuleSecondaryReplyProvider] = None,
        censor: Optional[SecondaryReplyCensor] = None,
    ) -> None:
        self.provider = provider or RuleSecondaryReplyProvider()
        self.censor = censor or SecondaryReplyCensor()

    def generate_draft(
        self,
        comment: AudienceCommentRecord,
        video_context: Optional[Dict[str, Any]] = None,
        preferred_style: Optional[SecondaryReplyStyle] = None,
    ) -> SecondaryReplyDraft:
        """为单条观众评论生成二级回复建议草稿并进行首轮安全门禁检查。"""
        draft = self.provider.generate(
            comment=comment,
            video_context=video_context,
            preferred_style=preferred_style,
        )

        if draft.intent == SecondaryReplyIntent.REPLY:
            # 1. 严格格式校验
            validate_reply_length_and_format(draft.chinese_reply, draft.english_reply)

            # 2. 检查事实依据引用 (T11: 绝不凭空捏造事实来源)
            if not draft.evidence_refs or not all(isinstance(ref, str) and ref.strip() for ref in draft.evidence_refs):
                raise SecondaryReplyContractError("生成建议回复必须包含有效的事实来源证据引用 (evidence_refs)")
            # 引用必须全部来自上游提供的材料白名单，未知引用拒绝
            allowed = set(allowed_evidence_refs(video_context))
            if not set(draft.evidence_refs) <= allowed:
                raise SecondaryReplyContractError("evidence_refs 含未提供的来源引用")

            # 3. 首轮内容安全与政策审查
            is_safe, error_detail = self.censor.check_reply_safety(
                chinese_reply=draft.chinese_reply,
                english_reply=draft.english_reply,
                formatted_reply=draft.formatted_reply,
            )
            if not is_safe:
                logger.error("[SecondaryReplyService] 草稿生成未能通过安全审查: %s", error_detail)
                raise CensorshipViolationError(f"二级回复草稿安全审查拦截: {error_detail}")

        return draft

    def validate_for_submission(
        self,
        chinese_reply: str,
        english_reply: str,
        formatted_reply: Optional[str] = None,
    ) -> str:
        """提交前终审门禁：无论草稿何时生成，发送前必须以当前最新政策终审。"""
        # 1. 格式校验
        zh_nfc, en_nfc, formatted = validate_reply_length_and_format(chinese_reply, english_reply)
        check_target = formatted_reply or formatted

        # 2. 内容审查与频道策略终审
        is_safe, error_detail = self.censor.check_reply_safety(
            chinese_reply=zh_nfc,
            english_reply=en_nfc,
            formatted_reply=check_target,
        )
        if not is_safe:
            raise CensorshipViolationError(f"提交前终审安全审查拦截: {error_detail}")

        return check_target

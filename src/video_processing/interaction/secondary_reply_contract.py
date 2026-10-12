"""视频号二级回复数据合同、格式规范与严格校验模型。

定义二级回复领域的强类型数据模型、长度方案 A 校验、控制字符与格式防御。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现长度方案 A (中<=75/英<=150/合<=230)、无内嵌换行/Emoji/标签、输入预算与意图合同 |
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Tuple


class SecondaryReplyIntent(str, Enum):
    """二级回复决策意图。"""
    REPLY = "REPLY"     # 建议回复
    SKIP = "SKIP"       # 忽略/无需回复（无实质意义/纯表情/灌水）
    MANUAL = "MANUAL"   # 人工接管（争议/体制/超出预算/纠错存疑）


class SecondaryReplyStyle(str, Enum):
    """二级回复表达风格偏好。"""
    MACRO = "MACRO"                     # 宏观视角 / 开放式互动
    PHILOSOPHICAL = "PHILOSOPHICAL"     # 哲理思辨 / 对比剖析
    HUMOROUS = "HUMOROUS"               # 幽默互动 / 机智风趣
    PRAGMATIC = "PRAGMATIC"             # 务实严谨 / 事实补充


class SecondaryReplyStatus(str, Enum):
    """二级回复任务生命周期状态。"""
    DRAFTED = "DRAFTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CLAIMED = "CLAIMED"
    SUBMIT_INTENT = "SUBMIT_INTENT"
    UNCERTAIN = "UNCERTAIN"
    VERIFIED = "VERIFIED"
    SKIPPED = "SKIPPED"
    MANUAL = "MANUAL"
    FAILED = "FAILED"


class SecondaryReplyContractError(ValueError):
    """二级回复内容或结构不满足契约规范。"""


class CensorshipViolationError(SecondaryReplyContractError):
    """二级回复内容命中安全审查或频道策略违规，一票否决。"""


class IllegalControlCharError(SecondaryReplyContractError):
    """文本包含非法控制字符。"""


class BudgetExceededError(SecondaryReplyContractError):
    """输入评论超过安全预算。"""


# 长度方案 A 约束常量
MAX_ZH_CODEPOINTS = 75
MAX_EN_CODEPOINTS = 150
MAX_COMBINED_CODEPOINTS = 230
MAX_INPUT_COMMENT_BUDGET = 300

# 正则表达式防御
_EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\ufe0e\ufe0f]",
    flags=re.UNICODE,
)
_TAG_PATTERN = re.compile(r"<[^>]+>|\[[^\]]+\]|\*\*|__|^#+\s+", flags=re.UNICODE | re.MULTILINE)
_SEPARATOR_PATTERN = re.compile(r"[-=_~*·]{3,}")


def check_no_illegal_control_chars(text: str, field_name: str = "text") -> None:
    """拒绝非法控制字符（除允许的空格外，禁用 \\x00-\\x1f 及 \\x7f-\\x9f）。"""
    for ch in text:
        code = ord(ch)
        # 允许常规制表符外，拒绝其他所有 C0/C1 控制符
        if (code < 32 and ch not in ("\n", "\r", "\t")) or (127 <= code <= 159):
            raise IllegalControlCharError(
                f"{field_name} 包含非法控制字符 U+{code:04X}，拒绝提交"
            )
        # 严格检查 Unicode 类别
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cs") and ch not in ("\n", "\r", "\t"):
            raise IllegalControlCharError(
                f"{field_name} 包含非法控制符类别 {cat} (U+{code:04X})"
            )


def check_no_emojis(text: str, field_name: str = "text") -> None:
    """严格拒绝任何 Emoji 表情字符。"""
    match = _EMOJI_PATTERN.search(text)
    if match:
        raise SecondaryReplyContractError(
            f"{field_name} 包含禁止的 Emoji 表情: '{match.group()}'"
        )


def check_no_tags_or_separators(text: str, field_name: str = "text") -> None:
    """严格拒绝任何标签、Markdown 标记或装饰分隔线。"""
    tag_match = _TAG_PATTERN.search(text)
    if tag_match:
        raise SecondaryReplyContractError(
            f"{field_name} 包含禁止的标签或格式标记: '{tag_match.group()}'"
        )
    sep_match = _SEPARATOR_PATTERN.search(text)
    if sep_match:
        raise SecondaryReplyContractError(
            f"{field_name} 包含禁止的装饰分隔符: '{sep_match.group()}'"
        )


def validate_reply_length_and_format(
    chinese_reply: str,
    english_reply: str,
) -> Tuple[str, str, str]:
    """严格实施长度方案 A 校验并生成确定性正文。

    规则：
    - 中文 <= 75 Unicode 码点 (NFC)
    - 英文 <= 150 Unicode 码点 (NFC)
    - 合并 (zh\\nen) <= 230 Unicode 码点 (NFC)
    - 不设最小字数限制
    - 两个非空字段之间恰好一个换行，字段内无换行
    - 无标签、无 Emoji、无分隔线
    - 非法控制符拒绝并报告，不默默改变获批正文
    """
    if not isinstance(chinese_reply, str) or not isinstance(english_reply, str):
        raise SecondaryReplyContractError("中英文回复内容必须为字符串")

    zh_nfc = unicodedata.normalize("NFC", chinese_reply.strip())
    en_nfc = unicodedata.normalize("NFC", english_reply.strip())

    if not zh_nfc and not en_nfc:
        raise SecondaryReplyContractError("中英文回复内容不能同时为空")

    # 1. 控制字符防御
    check_no_illegal_control_chars(zh_nfc, "中文回复")
    check_no_illegal_control_chars(en_nfc, "英文回复")

    # 2. 字段内不得包含任何换行符
    if "\n" in zh_nfc or "\r" in zh_nfc:
        raise SecondaryReplyContractError("中文回复字段内部不得包含换行符")
    if "\n" in en_nfc or "\r" in en_nfc:
        raise SecondaryReplyContractError("英文回复字段内部不得包含换行符")

    # 3. 标签与 Emoji 防御
    check_no_emojis(zh_nfc, "中文回复")
    check_no_emojis(en_nfc, "英文回复")
    check_no_tags_or_separators(zh_nfc, "中文回复")
    check_no_tags_or_separators(en_nfc, "英文回复")

    # 4. 长度方案 A 码点计数 (Unicode Code Points)
    zh_len = len(zh_nfc)
    en_len = len(en_nfc)

    if zh_len > MAX_ZH_CODEPOINTS:
        raise SecondaryReplyContractError(
            f"中文回复超过方案 A 上限 ({zh_len} > {MAX_ZH_CODEPOINTS} 码点)"
        )
    if en_len > MAX_EN_CODEPOINTS:
        raise SecondaryReplyContractError(
            f"英文回复超过方案 A 上限 ({en_len} > {MAX_EN_CODEPOINTS} 码点)"
        )

    if zh_nfc and en_nfc:
        formatted = f"{zh_nfc}\n{en_nfc}"
    else:
        formatted = zh_nfc or en_nfc

    formatted_len = len(formatted)
    if formatted_len > MAX_COMBINED_CODEPOINTS:
        raise SecondaryReplyContractError(
            f"合并回复超过方案 A 上限 ({formatted_len} > {MAX_COMBINED_CODEPOINTS} 码点)"
        )

    return zh_nfc, en_nfc, formatted


def validate_input_comment(
    content: str,
    max_codepoints: int = MAX_INPUT_COMMENT_BUDGET,
) -> Tuple[str, bool, str]:
    """校验观众评论输入预算，计算不可变内容摘要。

    决不静默截断！如果超出预算，保留完整原文并在返回中标记 is_truncated=True，
    上层必须据此降级为 MANUAL。
    """
    if not isinstance(content, str):
        raise SecondaryReplyContractError("观众评论必须为字符串")

    norm_content = unicodedata.normalize("NFC", content)
    content_hash = hashlib.sha256(norm_content.encode("utf-8")).hexdigest()

    is_truncated = len(norm_content) > max_codepoints
    return norm_content, is_truncated, content_hash


@dataclass(frozen=True)
class AudienceCommentRecord:
    """采集解析后的一级观众评论记录。"""
    platform_post_id: str
    comment_id: str
    nickname: str
    content: str
    content_hash: str
    createtime: str
    like_count: int = 0
    is_author: bool = False
    has_author_reply: bool = False
    level_two_count: int = 0


@dataclass(frozen=True)
class SecondaryReplyDraft:
    """二级回复建议草稿。"""
    platform_post_id: str
    comment_id: str
    intent: SecondaryReplyIntent
    style: SecondaryReplyStyle
    chinese_reply: str
    english_reply: str
    formatted_reply: str
    reason_code: str
    evidence_refs: List[str]
    provider: str
    revision: int = 1

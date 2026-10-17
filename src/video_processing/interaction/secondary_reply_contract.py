"""视频号二级回复数据合同、格式规范与严格校验模型。

定义二级回复领域的强类型数据模型、长度方案 A 校验、控制字符与格式防御。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Antigravity | 增强控制字符防御（严格拒绝 \\r 及 C0/C1 控制符）、新增 comment_list 强类型解析与一级/二级分页状态机 (T01/T02/T03/T12) |
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现长度方案 A (中<=75/英<=150/合<=230)、无内嵌换行/Emoji/标签、输入预算与意图合同 |
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


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


class TopLevelPaginationStatus(str, Enum):
    """一级评论列表分页状态。"""
    COMPLETE = "COMPLETE"                # downContinueFlag == 0, 当前页为最后一页
    HAS_MORE = "HAS_MORE"                # downContinueFlag == 1, 仍有下一页一级评论
    INVALID = "INVALID"                  # 数据结构异常


class SecondaryPaginationStatus(str, Enum):
    """二级回复列表分页与可见性完整状态。"""
    NO_REPLIES = "NO_REPLIES"                           # levelTwoComment 为空，无二级回复
    COMPLETE_WITH_REPLIES = "COMPLETE_WITH_REPLIES"     # levelTwoComment 完整，无作者二级回复
    AUTHOR_ALREADY_REPLIED = "AUTHOR_ALREADY_REPLIED"   # 已有作者二级回复
    UNSUPPORTED_FOLDED_PAGINATION = "UNSUPPORTED_FOLDED_PAGINATION" # 存在未知二级折叠/分页 (downContinueFlag == 1)


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
    """拒绝非法控制字符（除显式单换行外，严格禁用所有 C0/C1 控制符，包含 \\r、\\x00-\\x1f 及 \\x7f-\\x9f）。"""
    for ch in text:
        code = ord(ch)
        # 单独字段内部连换行都不允许；此处允许唯一合法字符为 \\n（用于字段间换行），严禁 \\r 与其他控制符
        if (code < 32 and ch != "\n") or (127 <= code <= 159):
            raise IllegalControlCharError(
                f"{field_name} 包含非法控制字符 U+{code:04X}，拒绝提交"
            )
        # 严格检查 Unicode 类别
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cs") and ch != "\n":
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

    # 1. 字段内不得包含任何换行符
    if "\n" in zh_nfc or "\r" in zh_nfc:
        raise SecondaryReplyContractError("中文回复字段内部不得包含换行符")
    if "\n" in en_nfc or "\r" in en_nfc:
        raise SecondaryReplyContractError("英文回复字段内部不得包含换行符")

    # 2. 控制字符防御
    check_no_illegal_control_chars(zh_nfc, "中文回复")
    check_no_illegal_control_chars(en_nfc, "英文回复")

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


@dataclass(frozen=True)
class CommentListParseResult:
    """WeChat comment_list API 响应解析结果。"""
    platform_post_id: str
    top_level_status: TopLevelPaginationStatus
    last_buff: str
    comments: List[AudienceCommentRecord]
    author_first_comment: Optional[AudienceCommentRecord]
    secondary_states: Dict[str, SecondaryPaginationStatus]
    unsupported_comments: List[str]

    def is_safe_to_reply(self, comment_id: str) -> bool:
        """检查该一级评论是否具备足够完整证据以安全发出二级回复。

        T02 铁律：若二级分页状态为 UNSUPPORTED_FOLDED_PAGINATION 或 AUTHOR_ALREADY_REPLIED，
        绝对不得发出写请求！
        """
        state = self.secondary_states.get(comment_id)
        return state in (SecondaryPaginationStatus.NO_REPLIES, SecondaryPaginationStatus.COMPLETE_WITH_REPLIES)


def parse_wechat_comment_list_payload(
    payload: Dict[str, Any],
    platform_post_id: str,
    author_username: Optional[str] = None,
    strict_schema: bool = True,
) -> CommentListParseResult:
    """严格解析 WeChat 评论列表 API 响应或脱敏 fixture。

    强安全保障：
    1. T01: 无作者首评且仅 1 条观众评论依然稳定发现；支持根据 downContinueFlag 判断扫描完整度。
    2. T02: 分别判断一级与二级分页完整性，未知折叠或二级 downContinueFlag=1 标记为 UNSUPPORTED_FOLDED_PAGINATION，拒绝写操作。
    3. T03: 严格按 commentId 绑定，相同昵称、相同正文的不同评论各自保留独立记录，绝不串号。
    4. T12: 拒绝非法控制字符、拒绝类型强转（如 commentId 传 int）、在严格模式下校验必填项。
    """
    if not isinstance(payload, dict):
        raise SecondaryReplyContractError("API 响应载荷必须为字典对象")

    data_block: Any = payload
    for key in ("comment_list", "data", "data"):
        if isinstance(data_block, dict) and key in data_block and isinstance(data_block[key], dict):
            data_block = data_block[key]

    if not isinstance(data_block, dict) or "comment" not in data_block:
        raise SecondaryReplyContractError("API 响应缺少 comment 列表字段")

    comment_items = data_block.get("comment")
    if not isinstance(comment_items, list):
        raise SecondaryReplyContractError("comment 字段必须为列表类型")

    top_down_flag = data_block.get("downContinueFlag", 0)
    if strict_schema and not isinstance(top_down_flag, int):
        raise SecondaryReplyContractError(f"downContinueFlag 必须为整型，禁止类型强转: {type(top_down_flag)}")
    top_level_status = (
        TopLevelPaginationStatus.HAS_MORE if top_down_flag == 1 else TopLevelPaginationStatus.COMPLETE
    )
    last_buff = str(data_block.get("lastBuff") or "")

    comments: List[AudienceCommentRecord] = []
    author_first_comment: Optional[AudienceCommentRecord] = None
    secondary_states: Dict[str, SecondaryPaginationStatus] = {}
    unsupported_comments: List[str] = []

    for item in comment_items:
        if not isinstance(item, dict):
            raise SecondaryReplyContractError("评论条目必须为字典对象")

        cid_raw = item.get("commentId")
        if cid_raw is None:
            raise SecondaryReplyContractError("评论缺少 commentId 必填字段")
        if strict_schema and not isinstance(cid_raw, str):
            raise SecondaryReplyContractError(f"commentId 必须为字符串类型，禁止类型强转: {type(cid_raw)}")
        cid = str(cid_raw).strip()
        if not cid:
            raise SecondaryReplyContractError("commentId 不能为空")

        content_raw = item.get("commentContent") if "commentContent" in item else item.get("content", "")
        if strict_schema and not isinstance(content_raw, str):
            raise SecondaryReplyContractError(f"评论正文必须为字符串类型: {type(content_raw)}")
        content_str = str(content_raw)
        check_no_illegal_control_chars(content_str, f"评论 {cid} 正文")
        norm_content = unicodedata.normalize("NFC", content_str)
        content_hash = hashlib.sha256(norm_content.encode("utf-8")).hexdigest()

        nickname = str(item.get("commentNickname") if "commentNickname" in item else item.get("nickname", ""))
        createtime = str(item.get("commentCreatetime") if "commentCreatetime" in item else item.get("createtime", ""))
        like_count = int(item.get("commentLikeCount") or item.get("like_count") or 0)

        # 检查是否为作者自身的一级评论（如首评）
        username = str(item.get("username") or "")
        display_flag = int(item.get("displayFlag") or 0)
        is_author = False
        if bool(item.get("is_author")):
            is_author = True
        elif author_username and username == author_username:
            is_author = True
        elif display_flag & 131072 != 0:
            is_author = True

        # 解析二级回复 (levelTwoComment)
        sub_list = item.get("levelTwoComment") or []
        if strict_schema and not isinstance(sub_list, list):
            raise SecondaryReplyContractError(f"levelTwoComment 必须为列表: {type(sub_list)}")

        has_author_reply = False
        item_down_flag = item.get("downContinueFlag", 0)
        if strict_schema and not isinstance(item_down_flag, int):
            raise SecondaryReplyContractError(f"条目 downContinueFlag 必须为整型: {type(item_down_flag)}")
        has_folded_unsupported = (item_down_flag == 1)

        for sub in sub_list:
            if not isinstance(sub, dict):
                raise SecondaryReplyContractError("二级回复条目必须为字典对象")
            sub_down_flag = sub.get("downContinueFlag", 0)
            if sub_down_flag == 1:
                has_folded_unsupported = True
            sub_username = str(sub.get("username") or "")
            sub_role = str(sub.get("data-author-role") or sub.get("author_role") or "")
            sub_nick = str(sub.get("commentNickname") or "")
            if (author_username and sub_username == author_username) or (not author_username and sub_role == "author"):
                has_author_reply = True

        # 判定二级状态
        if has_folded_unsupported:
            sec_status = SecondaryPaginationStatus.UNSUPPORTED_FOLDED_PAGINATION
            unsupported_comments.append(cid)
        elif has_author_reply:
            sec_status = SecondaryPaginationStatus.AUTHOR_ALREADY_REPLIED
        elif sub_list:
            sec_status = SecondaryPaginationStatus.COMPLETE_WITH_REPLIES
        else:
            sec_status = SecondaryPaginationStatus.NO_REPLIES

        secondary_states[cid] = sec_status

        record = AudienceCommentRecord(
            platform_post_id=platform_post_id,
            comment_id=cid,
            nickname=nickname,
            content=norm_content,
            content_hash=content_hash,
            createtime=createtime,
            like_count=like_count,
            is_author=is_author,
            has_author_reply=has_author_reply,
            level_two_count=len(sub_list),
        )

        if is_author:
            author_first_comment = record
        else:
            comments.append(record)

    return CommentListParseResult(
        platform_post_id=platform_post_id,
        top_level_status=top_level_status,
        last_buff=last_buff,
        comments=comments,
        author_first_comment=author_first_comment,
        secondary_states=secondary_states,
        unsupported_comments=unsupported_comments,
    )

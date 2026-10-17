"""视频号二级回复数据合同、格式规范与严格校验模型。

定义二级回复领域的强类型数据模型、长度方案 A 校验、控制字符与格式防御。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-17 | Antigravity | 收敛 SecondaryReplySubmissionGuard 至契约层以消除编排器对浏览器适配器的反向依赖；新增只读验证强类型契约 PlatformVerificationReport 并移除缺失证据默认成功行为 |
| 1.1.0 | 2026-10-12 | Antigravity | 增强控制字符防御（严格拒绝 \\r 及 C0/C1 控制符）、新增 comment_list 强类型解析与一级/二级分页状态机 (T01/T02/T03/T12) |
| 1.0.0 | 2026-10-12 | Codex | 初始创建：实现长度方案 A (中<=75/英<=150/合<=230)、无内嵌换行/Emoji/标签、输入预算与意图合同 |
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse


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


COMMENT_SUBMIT_PATHS = {
    "/cgi-bin/mmfinderassistant-bin/comment/create_comment",
    "/micro/interaction/cgi-bin/mmfinderassistant-bin/comment/create_comment",
}


class SecondaryReplySubmissionGuard:
    """二级回复网络发送前强校验守卫 (Route Guard)。

    任何非受信来源、错作品、错 root/reply ID、错账号、错正文、缺少必填字段或重复出站请求均在网络发送前硬拦截。
    """

    def __init__(
        self,
        expected_export_id: str,
        expected_root_comment_id: str,
        expected_content: str,
        expected_finder_id: Optional[str] = None,
        trusted_origins: Tuple[str, ...] = (),
    ) -> None:
        from video_processing.core.wechat_page_contract import is_official_wechat_origin

        self._is_official_wechat_origin = is_official_wechat_origin
        self.trusted_origins = tuple(trusted_origins)
        self.expected_export_id = expected_export_id
        self.expected_root_comment_id = expected_root_comment_id
        self.expected_content = expected_content
        self.expected_finder_id = expected_finder_id
        self.requests: List[Dict[str, Any]] = []
        self.mismatched_requests: List[Dict[str, Any]] = []
        self.responses: List[Dict[str, Any]] = []
        self.allowed_request: Any = None
        self.uncorrelated_responses: List[Dict[str, Any]] = []

    def capture_request(self, request: Any) -> bool:
        """检查出站发评请求。若合法则放行并记录，若不符则返回 False 触发硬阻断。"""
        if request.method != "POST":
            return True

        url_path = urlparse(request.url).path
        if url_path not in COMMENT_SUBMIT_PATHS:
            return True

        if self.requests:
            self.mismatched_requests.append({
                "reason": "DUPLICATE_SUBMISSION",
                "details": "一次流程仅允许最多一次出站发评请求",
                "url": request.url,
            })
            return False

        is_safe_origin = self._is_official_wechat_origin(request.url) or any(
            request.url.startswith(o) for o in self.trusted_origins
        )
        if not is_safe_origin:
            self.mismatched_requests.append({
                "reason": "UNTRUSTED_ORIGIN",
                "url": request.url,
            })
            return False

        try:
            payload = request.post_data_json
        except Exception:
            payload = None

        if not isinstance(payload, dict):
            self.mismatched_requests.append({
                "reason": "NON_JSON_OR_EMPTY_PAYLOAD",
                "url": request.url,
            })
            return False

        for req_f in ("exportId", "rootCommentId", "replyCommentId", "content"):
            if not payload.get(req_f):
                self.mismatched_requests.append({
                    "reason": "MISSING_REQUIRED_FIELD",
                    "details": f"Missing required field: {req_f}",
                    "payload": payload,
                })
                return False

        req_export_id = str(payload.get("exportId") or "").strip()
        req_root_id = str(payload.get("rootCommentId") or "").strip()
        req_reply_id = str(payload.get("replyCommentId") or "").strip()
        req_finder_id = str(payload.get("_log_finder_id") or payload.get("username") or "").strip()

        mismatches = []
        if req_export_id != self.expected_export_id:
            mismatches.append(f"exportId mismatch: '{req_export_id}' != '{self.expected_export_id}'")
        if req_root_id != self.expected_root_comment_id:
            mismatches.append(f"rootCommentId mismatch: '{req_root_id}' != '{self.expected_root_comment_id}'")
        if req_reply_id != self.expected_root_comment_id:
            mismatches.append(f"replyCommentId mismatch: '{req_reply_id}' != '{self.expected_root_comment_id}'")
        if unicodedata.normalize("NFC", str(payload.get("content"))) != unicodedata.normalize("NFC", self.expected_content):
            mismatches.append("content mismatch")
        if not self.expected_finder_id:
            mismatches.append("expected account not configured")
        elif not req_finder_id:
            mismatches.append("account field missing in request")
        elif req_finder_id != self.expected_finder_id:
            mismatches.append(f"account mismatch: '{req_finder_id}' != '{self.expected_finder_id}'")

        if mismatches:
            self.mismatched_requests.append({
                "reason": "FIELD_MISMATCH",
                "details": mismatches,
                "payload": payload,
            })
            return False

        self.requests.append(payload)
        self.allowed_request = request
        return True

    def capture_response(self, response: Any) -> None:
        """捕获提交回执；仅接受与唯一准许出站 Request 对应的 Response，其余记为无关回执。"""
        url_path = urlparse(response.url).path
        if url_path not in COMMENT_SUBMIT_PATHS:
            return
        try:
            payload = response.json()
        except Exception:
            payload = None
        item = {"status": response.status, "url": response.url, "data": payload}
        if self.allowed_request is not None and getattr(response, "request", None) is self.allowed_request:
            self.responses.append(item)
        else:
            self.uncorrelated_responses.append(item)

    def validate_success_response(self) -> Tuple[bool, str, str]:
        """校验与唯一出站 Request 关联的业务成功回执。返回 (ok, 原生回复 ID, 原因)。"""
        if len(self.responses) != 1:
            return False, "", f"correlated_responses={len(self.responses)}"
        item = self.responses[0]
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if item.get("status") not in (200, 201) or data.get("errCode") != 0:
            return False, "", "NOT_BUSINESS_SUCCESS"
        body = data.get("data") if isinstance(data.get("data"), dict) else {}
        comment = body.get("comment") if isinstance(body.get("comment"), dict) else {}
        reply_id = str(body.get("commentId") or "").strip()
        if not reply_id or str(comment.get("commentId") or "").strip() != reply_id:
            return False, "", "REPLY_ID_MISSING_OR_INCONSISTENT"
        if str(comment.get("replyCommentId") or "").strip() != self.expected_root_comment_id:
            return False, "", "PARENT_MISMATCH"
        if not self.expected_finder_id or str(comment.get("username") or "").strip() != self.expected_finder_id:
            return False, "", "AUTHOR_MISMATCH"
        if unicodedata.normalize("NFC", str(comment.get("commentContent") or "")) != unicodedata.normalize("NFC", self.expected_content):
            return False, "", "CONTENT_MISMATCH"
        return True, reply_id, "OK"


def _normalize_visible_text(value: object) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value or ""))).strip()


@dataclass(frozen=True)
class ObservedChannelProfile:
    """只读验证中的账号配置期望值与平台实测身份契约。

    严格区分 expected_finder_id（配置期望）与 observed_native_username（平台实测），
    绝不允许缺失实测身份时用配置值冒充或默认 identity_verified=True。
    """

    account_key: str
    expected_finder_id: str
    observed_native_username: str
    channel_nickname: str
    identity_verified: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_key": self.account_key,
            "finder_id": self.expected_finder_id,
            "expected_finder_id": self.expected_finder_id,
            "native_username": self.observed_native_username,
            "observed_native_username": self.observed_native_username,
            "channel_nickname": self.channel_nickname,
            "identity_verified": self.identity_verified,
        }


@dataclass(frozen=True)
class ObservedTargetComment:
    """只读验证中的目标作品/父评论期望值与平台实测值契约。

    缺失 text_matched 或 fresh 证据时一律为 False，绝不默认 True。
    """

    expected_post_id: str
    expected_comment_id: str
    expected_comment_text: str
    observed_post_id: str
    observed_comment_id: str
    video_title: str
    author_nickname: str
    observed_comment_text: str
    text_matched: bool
    fresh: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.observed_post_id,
            "comment_id": self.observed_comment_id,
            "expected_post_id": self.expected_post_id,
            "expected_comment_id": self.expected_comment_id,
            "expected_comment_text": self.expected_comment_text,
            "video_title": self.video_title,
            "author_nickname": self.author_nickname,
            "comment_text": self.observed_comment_text,
            "observed_comment_text": self.observed_comment_text,
            "text_matched": self.text_matched,
            "fresh": self.fresh,
        }


@dataclass(frozen=True)
class CalibratedControlState:
    """单个二级回复 DOM 控件的只读校准观测状态。"""

    selector: Optional[str] = None
    found: bool = False
    count: int = 0
    visible: bool = False
    enabled: Optional[bool] = None
    editable: Optional[bool] = None
    is_empty: Optional[bool] = None
    disabled_when_empty: Optional[bool] = None
    enabled_when_filled: Optional[bool] = None
    text: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: Any) -> "CalibratedControlState":
        if isinstance(raw, CalibratedControlState):
            return raw
        if not isinstance(raw, Mapping):
            return cls()
        count_val = raw.get("count", 0)
        count = int(count_val) if isinstance(count_val, int) and not isinstance(count_val, bool) else 0
        return cls(
            selector=str(raw["selector"]) if raw.get("selector") else None,
            found=raw.get("found") is True,
            count=count,
            visible=raw.get("visible") is True,
            enabled=raw.get("enabled") if isinstance(raw.get("enabled"), bool) else None,
            editable=raw.get("editable") if isinstance(raw.get("editable"), bool) else None,
            is_empty=raw.get("is_empty") if isinstance(raw.get("is_empty"), bool) else None,
            disabled_when_empty=(
                raw.get("disabled_when_empty") if isinstance(raw.get("disabled_when_empty"), bool) else None
            ),
            enabled_when_filled=(
                raw.get("enabled_when_filled") if isinstance(raw.get("enabled_when_filled"), bool) else None
            ),
            text=str(raw["text"]) if raw.get("text") is not None else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "selector": self.selector,
            "found": self.found,
            "count": self.count,
            "visible": self.visible,
        }
        if self.enabled is not None:
            out["enabled"] = self.enabled
        if self.editable is not None:
            out["editable"] = self.editable
        if self.is_empty is not None:
            out["is_empty"] = self.is_empty
        if self.disabled_when_empty is not None:
            out["disabled_when_empty"] = self.disabled_when_empty
        if self.enabled_when_filled is not None:
            out["enabled_when_filled"] = self.enabled_when_filled
        if self.text is not None or ("enabled" not in out and "editable" not in out and "disabled_when_empty" not in out):
            out["text"] = self.text
        return out


@dataclass(frozen=True)
class ControlsCalibrationSummary:
    """二级回复四个关键控件（回复触发、输入框、提交按钮、展开按钮）校准汇总。"""

    reply_icon: CalibratedControlState = field(default_factory=CalibratedControlState)
    editor_textarea: CalibratedControlState = field(default_factory=CalibratedControlState)
    submit_button: CalibratedControlState = field(default_factory=CalibratedControlState)
    expand_button: CalibratedControlState = field(default_factory=CalibratedControlState)

    @classmethod
    def from_raw(cls, raw: Any) -> "ControlsCalibrationSummary":
        if isinstance(raw, ControlsCalibrationSummary):
            return raw
        if not isinstance(raw, Mapping):
            return cls()
        return cls(
            reply_icon=CalibratedControlState.from_raw(raw.get("reply_icon")),
            editor_textarea=CalibratedControlState.from_raw(raw.get("editor_textarea")),
            submit_button=CalibratedControlState.from_raw(raw.get("submit_button")),
            expand_button=CalibratedControlState.from_raw(raw.get("expand_button")),
        )

    def is_ready_for_unreplied(self) -> bool:
        """检查未回复样本所需的三大发送控件是否均唯一定位且满足零写只读校准条件。"""
        reply_ok = (
            self.reply_icon.found is True
            and self.reply_icon.count == 1
            and self.reply_icon.visible is True
            and self.reply_icon.enabled is True
            and bool(self.reply_icon.selector)
        )
        editor_ok = (
            self.editor_textarea.found is True
            and self.editor_textarea.count == 1
            and self.editor_textarea.visible is True
            and self.editor_textarea.editable is True
            and self.editor_textarea.is_empty is True
            and bool(self.editor_textarea.selector)
        )
        submit_ok = (
            self.submit_button.found is True
            and self.submit_button.count == 1
            and self.submit_button.visible is True
            and self.submit_button.disabled_when_empty is True
            and bool(self.submit_button.selector)
        )
        return bool(reply_ok and editor_ok and submit_ok)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reply_icon": self.reply_icon.to_dict(),
            "editor_textarea": self.editor_textarea.to_dict(),
            "submit_button": self.submit_button.to_dict(),
            "expand_button": self.expand_button.to_dict(),
        }


@dataclass(frozen=True)
class PlatformVerificationReport:
    """只读平台核验与控件校准强类型结果契约。

    铁律：
    1. identity_verified 缺失绝不默认 True；native_username 缺失绝不用 expected_finder_id 冒充；
       仅当实测 observed_native_username 非空且严格等于 expected_finder_id 时 identity_verified 才为 True。
    2. text_matched 与 fresh 缺失绝不默认 True；必须有实测非空评论文本（当提供 expected_comment_text 时还须规范化等值）。
    3. 区分 REPLIED 与 NOT_REPLIED 的判断条件：
       - NOT_REPLIED 必须同时具备：identity_verified、fresh、text_matched、completeness == "COMPLETE"、
         三大核心控件唯一就绪 (controls_calibration.is_ready_for_unreplied()) 且 editor_closed_cleanly。
       - REPLIED 必须具备：identity_verified、fresh、text_matched 及显式非错误的 completeness
         （已观察到作者回复时，不强求与未回复样本相同的完整分页或展开编辑器校准）。
    4. 任何证据缺失、矛盾或异常均降级为 ok=False, status="UNKNOWN"（或 LOGIN_REQUIRED）。
    """

    ok: bool
    status: str
    completeness: str
    channel_profile: ObservedChannelProfile
    target: ObservedTargetComment
    controls_calibration: ControlsCalibrationSummary
    evidence_files: Dict[str, str]
    mode: str = "PLATFORM_READ_ONLY_CALIBRATION_AND_VERIFICATION"
    reason: Optional[str] = None
    editor_closed_cleanly: bool = True

    @classmethod
    def from_raw(
        cls,
        raw: Any,
        *,
        account_key: str,
        expected_finder_id: str,
        expected_post_id: str,
        expected_comment_id: str,
        expected_video_title: Optional[str] = None,
        expected_comment_text: Optional[str] = None,
    ) -> "PlatformVerificationReport":
        if isinstance(raw, PlatformVerificationReport):
            raw_map: Mapping[str, Any] = raw.to_dict()
        elif isinstance(raw, Mapping):
            raw_map = raw
        else:
            raise SecondaryReplyContractError("平台只读核验返回结果必须为 PlatformVerificationReport 或显式映射字典")

        raw_ok = raw_map.get("ok") is True
        raw_status = str(raw_map.get("status") or "UNKNOWN").strip()
        raw_completeness = str(raw_map.get("completeness") or "").strip()
        raw_reason = str(raw_map.get("reason") or "").strip() or None
        editor_closed_cleanly = raw_map.get("editor_closed_cleanly", True) is True

        raw_profile = raw_map.get("channel_profile")
        if isinstance(raw_profile, ObservedChannelProfile):
            profile_map: Mapping[str, Any] = raw_profile.to_dict()
        elif isinstance(raw_profile, Mapping):
            profile_map = raw_profile
        else:
            profile_map = {}

        observed_native_username = str(
            profile_map.get("observed_native_username") or profile_map.get("native_username") or ""
        ).strip()
        channel_nickname = str(profile_map.get("channel_nickname") or "").strip()
        raw_identity_flag = profile_map.get("identity_verified") is True
        identity_verified = bool(
            raw_identity_flag
            and expected_finder_id
            and observed_native_username
            and observed_native_username == expected_finder_id
        )

        channel_profile = ObservedChannelProfile(
            account_key=account_key,
            expected_finder_id=expected_finder_id,
            observed_native_username=observed_native_username,
            channel_nickname=channel_nickname,
            identity_verified=identity_verified,
        )

        raw_target = raw_map.get("target")
        if isinstance(raw_target, ObservedTargetComment):
            target_map: Mapping[str, Any] = raw_target.to_dict()
        elif isinstance(raw_target, Mapping):
            target_map = raw_target
        else:
            target_map = {}

        observed_post_id = str(
            target_map.get("observed_post_id") or target_map.get("post_id") or ""
        ).strip()
        observed_comment_id = str(
            target_map.get("observed_comment_id") or target_map.get("comment_id") or ""
        ).strip()
        observed_comment_text = str(
            target_map.get("observed_comment_text") or target_map.get("comment_text") or ""
        ).strip()
        author_nickname = str(target_map.get("author_nickname") or "").strip()
        video_title = str(target_map.get("video_title") or expected_video_title or "").strip()

        raw_fresh_flag = target_map.get("fresh") is True
        ids_bound = bool(
            expected_post_id
            and expected_comment_id
            and observed_post_id == expected_post_id
            and observed_comment_id == expected_comment_id
        )
        fresh = bool(raw_fresh_flag and ids_bound)

        raw_text_flag = target_map.get("text_matched") is True
        expected_text_str = str(expected_comment_text or "").strip()
        if expected_text_str:
            text_matched = bool(
                raw_text_flag
                and observed_comment_text
                and _normalize_visible_text(observed_comment_text) == _normalize_visible_text(expected_text_str)
            )
        else:
            text_matched = bool(raw_text_flag and observed_comment_text)

        target = ObservedTargetComment(
            expected_post_id=expected_post_id,
            expected_comment_id=expected_comment_id,
            expected_comment_text=expected_text_str,
            observed_post_id=observed_post_id,
            observed_comment_id=observed_comment_id,
            video_title=video_title,
            author_nickname=author_nickname,
            observed_comment_text=observed_comment_text,
            text_matched=text_matched,
            fresh=fresh,
        )

        controls = ControlsCalibrationSummary.from_raw(raw_map.get("controls_calibration"))
        raw_ev = raw_map.get("evidence_files")
        evidence_files: Dict[str, str] = {}
        if isinstance(raw_ev, Mapping):
            for k, v in raw_ev.items():
                if v is not None and str(v).strip():
                    evidence_files[str(k)] = str(v).strip()

        if raw_status == "LOGIN_REQUIRED":
            return cls(
                ok=False,
                status="LOGIN_REQUIRED",
                completeness=raw_completeness or "UNKNOWN",
                channel_profile=channel_profile,
                target=target,
                controls_calibration=controls,
                evidence_files=evidence_files,
                reason=raw_reason or "LOGIN_REQUIRED",
                editor_closed_cleanly=editor_closed_cleanly,
            )

        missing_reasons: List[str] = []
        if not identity_verified:
            missing_reasons.append("IDENTITY_NOT_VERIFIED")
        if not fresh:
            missing_reasons.append("TARGET_NOT_FRESH_OR_ID_MISMATCH")
        if not text_matched:
            missing_reasons.append("COMMENT_TEXT_NOT_VERIFIED")

        if raw_status == "REPLIED":
            completeness_valid = bool(raw_completeness) and raw_completeness not in ("UNKNOWN", "INVALID", "ERROR")
            if not completeness_valid:
                missing_reasons.append("REPLIED_COMPLETENESS_EVIDENCE_MISSING")
            if raw_ok and not missing_reasons:
                return cls(
                    ok=True,
                    status="REPLIED",
                    completeness=raw_completeness,
                    channel_profile=channel_profile,
                    target=target,
                    controls_calibration=controls,
                    evidence_files=evidence_files,
                    reason=None,
                    editor_closed_cleanly=editor_closed_cleanly,
                )
            return cls(
                ok=False,
                status="UNKNOWN",
                completeness=raw_completeness or "UNKNOWN",
                channel_profile=channel_profile,
                target=target,
                controls_calibration=controls,
                evidence_files=evidence_files,
                reason=raw_reason or "; ".join(missing_reasons) or "REPLIED_EVIDENCE_INCOMPLETE",
                editor_closed_cleanly=editor_closed_cleanly,
            )

        if raw_status == "NOT_REPLIED":
            if raw_completeness != "COMPLETE":
                missing_reasons.append(f"PAGINATION_COMPLETENESS_NOT_COMPLETE({raw_completeness or 'MISSING'})")
            if not controls.is_ready_for_unreplied():
                missing_reasons.append("CONTROLS_CALIBRATION_INCOMPLETE")
            if raw_ok and not missing_reasons:
                return cls(
                    ok=True,
                    status="NOT_REPLIED",
                    completeness="COMPLETE",
                    channel_profile=channel_profile,
                    target=target,
                    controls_calibration=controls,
                    evidence_files=evidence_files,
                    reason=None,
                    editor_closed_cleanly=editor_closed_cleanly,
                )
            return cls(
                ok=False,
                status="UNKNOWN",
                completeness=raw_completeness or "UNKNOWN",
                channel_profile=channel_profile,
                target=target,
                controls_calibration=controls,
                evidence_files=evidence_files,
                reason=raw_reason or "; ".join(missing_reasons) or "NOT_REPLIED_EVIDENCE_INCOMPLETE",
                editor_closed_cleanly=editor_closed_cleanly,
            )

        return cls(
            ok=False,
            status="UNKNOWN",
            completeness=raw_completeness or "UNKNOWN",
            channel_profile=channel_profile,
            target=target,
            controls_calibration=controls,
            evidence_files=evidence_files,
            reason=raw_reason or "; ".join(missing_reasons) or f"UNVERIFIED_STATUS({raw_status})",
            editor_closed_cleanly=editor_closed_cleanly,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "completeness": self.completeness,
            "reason": self.reason,
            "channel_profile": self.channel_profile.to_dict(),
            "target": self.target.to_dict(),
            "controls_calibration": self.controls_calibration.to_dict(),
            "editor_closed_cleanly": self.editor_closed_cleanly,
            "evidence_files": dict(self.evidence_files),
            "mode": self.mode,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


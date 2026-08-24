"""发布标题的表面合同与本地校验。

标题会同时流向平台字段、封面和视频渲染。这里仅处理可在不调用
模型的情况下确定的格式与语义完整性信号；事实保真仍由共享翻译质量
守门器负责，避免在各个 provider 中复制规则。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 新增平台标题、封面展示标题和 Hook 的纯函数合同，供多供应商共用。 |
| 1.1.0 | 2026-08-24 | Codex | 拒绝以 TED/演讲者元信息代替内容主旨的低信息标题，触发供应商降级。 |
| 1.2.0 | 2026-08-24 | Codex | Hook 同样拒绝纯 TED/讲者元信息，避免封面副标题无信息价值。 |
| 1.3.0 | 2026-08-24 | Codex | 拒绝将承诺/预测改写为已被打破、兑现或实现的事实方向漂移标题。 |
| 1.4.0 | 2026-08-24 | Codex | 收紧嘉宾 TED 起句及姓名加演讲的 Hook，统一过滤演讲元信息变体。 |
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class TitleContractError(ValueError):
    """标题不满足可投递的局部合同。"""


_LEADING_OR_TRAILING_PUNCTUATION = re.compile(r"^[，,。；;：:、|｜—–\-+]+|[，,。；;：:、|｜—–\-+]+$")
_INCOMPLETE_NUMERIC_QUESTION = re.compile(
    r"^(?:为什么|为何|怎么|如何|是否|能否|会不会)(?:只有|仅有|仅)?\s*\d+\s*$"
)
_DANGLING_ENDING = re.compile(r"(?:的|得|地|与|和|或|而|将|于|在|以|等|着|了|下)$")
_LOW_INFORMATION_TITLE = re.compile(
    r"(?:^|[，,])(?:TEDx?|演讲者|主讲人|讲者)(?:演讲|谈|探讨|分享|在)|"
    r"TEDx?演讲(?:谈|探讨|分享)|(?:演讲者|主讲人|讲者).*(?:谈|探讨|分享)"
)
_LOW_INFORMATION_HOOK = re.compile(
    r"^(?:TEDx?|(?:[\u4e00-\u9fff]+)?TEDx?演讲(?:[：:].*)?|(?:演讲者|主讲人|讲者)[：:].*)$"
)
_SPEAKER_METADATA_TITLE = re.compile(r"^(?:嘉宾|讲者|主讲人).*(?:TEDx?|演讲)")
_SPEAKER_METADATA_HOOK = re.compile(r"^[A-Za-z][A-Za-z.\-]{5,}(?:演讲|分享)$")
_UNSUPPORTED_OUTCOME_CLAIM = re.compile(
    r"(?:(?:打破|兑现|实现).*(?:承诺|预测|愿景)|(?:承诺|预测|愿景).*(?:打破|兑现|实现|破灭|落空|崩塌))"
)


@dataclass(frozen=True)
class TitleBundle:
    """同一内容在不同展示表面的标题成品。"""

    platform_title: str
    display_title: str
    hook_subtitle: str


def normalize_title(value: str) -> str:
    """折叠空白并移除不可见的首尾空格，保持正文标点不变。"""
    return re.sub(r"\s+", "", str(value or "")).strip()


def validate_platform_title(value: str) -> str:
    """校验 6--16 字的平台标题。"""
    return _validate_title(value, field_name="platform_title", min_length=6, max_length=16)


def validate_display_title(value: str) -> str:
    """校验 10--18 字的封面展示标题。"""
    return _validate_title(value, field_name="display_title", min_length=10, max_length=18)


def validate_hook_subtitle(value: str) -> str:
    """校验可选的封面副标题；空值用于兼容历史 checkpoint。"""
    normalized = normalize_title(value)
    if not normalized:
        return ""
    if len(normalized) > 24:
        raise TitleContractError("hook_subtitle 超过 24 字")
    if _LEADING_OR_TRAILING_PUNCTUATION.search(normalized):
        raise TitleContractError("hook_subtitle 不能以分隔标点开头或结尾")
    if _LOW_INFORMATION_HOOK.fullmatch(normalized) or _SPEAKER_METADATA_HOOK.fullmatch(normalized):
        raise TitleContractError("hook_subtitle 不能仅包含演讲者或栏目元信息")
    return normalized


def validate_title_bundle(
    *,
    platform_title: str,
    display_title: str,
    hook_subtitle: str,
    require_display_title: bool = True,
) -> TitleBundle:
    """校验并规范化一组标题字段。"""
    normalized_display = normalize_title(display_title)
    if require_display_title or normalized_display:
        normalized_display = validate_display_title(normalized_display)
    return TitleBundle(
        platform_title=validate_platform_title(platform_title),
        display_title=normalized_display,
        hook_subtitle=validate_hook_subtitle(hook_subtitle),
    )


def _validate_title(value: str, *, field_name: str, min_length: int, max_length: int) -> str:
    normalized = normalize_title(value)
    if not min_length <= len(normalized) <= max_length:
        raise TitleContractError(
            f"{field_name} 长度必须为 {min_length}-{max_length} 字，当前为 {len(normalized)} 字"
        )
    if _LEADING_OR_TRAILING_PUNCTUATION.search(normalized):
        raise TitleContractError(f"{field_name} 不能以分隔标点开头或结尾")
    if _INCOMPLETE_NUMERIC_QUESTION.fullmatch(normalized):
        raise TitleContractError(f"{field_name} 是不完整的数字疑问残句")
    if _DANGLING_ENDING.search(normalized):
        raise TitleContractError(f"{field_name} 以悬空虚词结尾")
    if _LOW_INFORMATION_TITLE.search(normalized):
        raise TitleContractError(f"{field_name} 以演讲者或栏目元信息代替内容主旨")
    if _SPEAKER_METADATA_TITLE.search(normalized):
        raise TitleContractError(f"{field_name} 以嘉宾或栏目元信息作为内容主语")
    if _UNSUPPORTED_OUTCOME_CLAIM.search(normalized):
        raise TitleContractError(f"{field_name} 将承诺或预测改写为未经来源支持的结果")
    if normalized.count("“") != normalized.count("”") or normalized.count('"') % 2:
        raise TitleContractError(f"{field_name} 引号未闭合")
    return normalized

"""发布文案的基础合同校验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-04 | Codex | 拒绝被翻译 fallback 误当作发布文案的 HTTP 错误页，供文案器与管线双重调用 |
"""

from __future__ import annotations

import re


class GeneratedContentValidationError(ValueError):
    """生成文本不满足可发布内容合同。"""


_GENERIC_ERROR_TITLE = re.compile(
    r"^\s*(?:http\s*)?error\s*[45]\d{2}(?:\s*[:!.-].*)?\s*$|"
    r"^\s*(?:internal\s+)?server\s+error\s*$|"
    r"^\s*(?:bad\s+gateway|gateway\s+timeout|service\s+unavailable)\s*$",
    re.IGNORECASE,
)
_ERROR_PAGE_MARKERS = (
    "error 500",
    "server error",
    "that's an error",
    "that’s an error",
    "there was an error",
    "please try again later",
    "that's all we know",
    "that’s all we know",
    "bad gateway",
    "gateway timeout",
    "service unavailable",
)


def validate_publishable_generated_content(short_title: str, copy: str) -> None:
    """拒绝空内容、纯 HTTP 错误标题及错误页正文。

    标题只在自身完全等于通用错误信息时阻断，避免误伤“如何修复 Error 500”这类
    正常技术主题。正文需同时命中三个错误页特征，才会被认定为上游错误响应。
    """
    title = (short_title or "").strip()
    body = (copy or "").strip()
    if not title:
        raise GeneratedContentValidationError("短标题为空")
    if not body:
        raise GeneratedContentValidationError("发布文案为空")
    if _GENERIC_ERROR_TITLE.fullmatch(title):
        raise GeneratedContentValidationError(f"短标题是上游错误响应: {title!r}")

    normalized_body = body.casefold()
    marker_hits = [marker for marker in _ERROR_PAGE_MARKERS if marker in normalized_body]
    if len(marker_hits) >= 3:
        raise GeneratedContentValidationError(
            "发布文案疑似上游 HTTP 错误页，命中特征: " + ", ".join(marker_hits)
        )
